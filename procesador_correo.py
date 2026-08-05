import base64
import binascii
import csv
import io
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path


PAYLOAD_PATH = Path("payload_correo_certificado.json")

REQUIRED_FIELDS = {
    "tipo_archivo",
    "nombre_archivo",
    "ruta_sharepoint",
    "identifier",
    "file_content_base64",
}

EXPECTED_FILE_TYPE = "CORREO_CERTIFICADO"
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


def load_payload(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo: {path}")

    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    return validate_payload(payload)


def validate_payload(payload: dict) -> dict:
    missing = sorted(field for field in REQUIRED_FIELDS if not payload.get(field))
    if missing:
        raise ValueError(f"Faltan campos obligatorios en el payload: {', '.join(missing)}")

    if payload["tipo_archivo"] != EXPECTED_FILE_TYPE:
        raise ValueError(
            f"tipo_archivo debe ser {EXPECTED_FILE_TYPE}, recibido: {payload['tipo_archivo']}"
        )

    return payload


def decode_file(payload: dict) -> bytes:
    try:
        return base64.b64decode(payload["file_content_base64"], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("file_content_base64 no es un Base64 valido") from exc


def decode_csv_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise ValueError("No fue posible decodificar el CSV de correo certificado")


def detect_delimiter(csv_text: str) -> str:
    sample = csv_text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t")
        return dialect.delimiter
    except csv.Error:
        return ";"


def normalize_column_name(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    clean_value = re.sub(r"[^A-Za-z0-9]+", "_", ascii_value)
    return clean_value.strip("_").lower()


def load_certified_email_csv(content: bytes) -> dict:
    csv_text = decode_csv_text(content)
    delimiter = detect_delimiter(csv_text)
    reader = csv.reader(io.StringIO(csv_text), delimiter=delimiter)
    try:
        raw_headers = next(reader)
    except StopIteration as exc:
        raise ValueError("El CSV de correo certificado esta vacio") from exc

    if not raw_headers:
        raise ValueError("El CSV de correo certificado no contiene encabezados")

    raw_headers = [header or "" for header in raw_headers]
    normalized_headers = [normalize_column_name(header) for header in raw_headers]
    rows = []
    repaired_rows = []
    alignment_errors = []
    total_rows = 0

    for line_number, values in enumerate(reader, start=2):
        total_rows += 1
        aligned_values, was_repaired, alignment_error = align_csv_row(
            values,
            normalized_headers,
        )
        if alignment_error:
            alignment_errors.append(
                {
                    "tipo_error": "fila_csv_desalineada",
                    "mensaje": alignment_error,
                    "numero_linea_csv": line_number,
                    "cantidad_columnas": len(values),
                }
            )
            continue

        row = {
            normalized_header: aligned_values[index]
            for index, normalized_header in enumerate(normalized_headers)
            if normalized_header
        }
        row["numero_linea_csv"] = line_number
        rows.append(row)
        if was_repaired:
            repaired_rows.append(line_number)

    return {
        "delimitador": delimiter,
        "encabezados_originales": raw_headers,
        "encabezados_normalizados": normalized_headers,
        "filas_crudas": rows,
        "total_filas_leidas": total_rows,
        "filas_reparadas": repaired_rows,
        "errores_alineacion": alignment_errors,
    }


def clean_text_value(value: object) -> str | None:
    if value is None:
        return None

    clean_value = re.sub(r"\s+", " ", str(value)).strip()
    return clean_value or None


def split_names_email(value: object) -> dict[str, str | None]:
    clean_value = clean_text_value(value)
    if not clean_value:
        return {"nombres": None, "correo": None}

    match = EMAIL_PATTERN.search(clean_value)
    correo = clean_text_value(match.group(0)).lower() if match else None
    nombres = clean_value

    if match:
        nombres = f"{clean_value[:match.start()]} {clean_value[match.end():]}"
        nombres = re.sub(r"[()<>]", " ", nombres)

    return {
        "nombres": clean_text_value(nombres),
        "correo": correo,
    }


def extract_subject_numbers(value: object) -> list[str]:
    clean_value = clean_text_value(value)
    if not clean_value:
        return []

    numbers = []
    seen = set()

    for match in re.finditer(r"(?<!\d)(?:\d[\d.,]*)?\d(?!\d)", clean_value):
        number = re.sub(r"[.,]", "", match.group(0))
        if len(number) <= 5 or number in seen:
            continue

        numbers.append(number)
        seen.add(number)

    return numbers


def parse_datetime_value(value: str) -> datetime | None:
    for date_format in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y",
    ):
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue

    return None


def is_date_bundle(value: object) -> bool:
    clean_value = clean_text_value(value)
    if not clean_value:
        return False

    parts = [clean_text_value(part) for part in re.split(r"\s+/\s+", clean_value)]
    date_parts = [part for part in parts if part]
    return bool(date_parts) and all(parse_datetime_value(part) for part in date_parts)


def align_csv_row(
    values: list[str],
    normalized_headers: list[str],
) -> tuple[list[str], bool, str | None]:
    """Repara filas cuyo campo Nombres - Email contiene comas sin escapar."""
    expected_count = len(normalized_headers)
    aligned_values = list(values)

    while len(aligned_values) > expected_count and not clean_text_value(aligned_values[-1]):
        aligned_values.pop()

    try:
        date_index = normalized_headers.index("fecha")
    except ValueError:
        return aligned_values, False, "El encabezado no contiene la columna Fecha"

    expected_date = (
        aligned_values[date_index]
        if date_index < len(aligned_values)
        else None
    )
    repaired = False
    if not is_date_bundle(expected_date):
        candidate_index = next(
            (
                index
                for index in range(date_index + 1, min(len(aligned_values), date_index + 6))
                if is_date_bundle(aligned_values[index])
            ),
            None,
        )
        if candidate_index is not None and date_index == 1:
            merged_recipient = ", ".join(
                value.strip()
                for value in aligned_values[:candidate_index]
                if value.strip()
            )
            aligned_values = [merged_recipient, *aligned_values[candidate_index:]]
            repaired = True

    while len(aligned_values) > expected_count and not clean_text_value(aligned_values[-1]):
        aligned_values.pop()
    if len(aligned_values) > expected_count:
        return (
            aligned_values,
            repaired,
            "La fila contiene columnas adicionales que no se pudieron reconstruir",
        )
    if len(aligned_values) < expected_count:
        aligned_values.extend([""] * (expected_count - len(aligned_values)))

    return aligned_values, repaired, None


def format_short_date(value: str) -> str:
    parsed_date = parse_datetime_value(value)
    if not parsed_date:
        return value

    return parsed_date.date().isoformat()


def split_date_values(value: object) -> dict[str, str | None]:
    clean_value = clean_text_value(value)
    if not clean_value:
        return {"fecha": None, "fecha_2": None, "fecha_3": None}

    parts = [clean_text_value(part) for part in re.split(r"\s+/\s+", clean_value)]
    dates = [part for part in parts if part]

    if len(dates) > 3:
        dates = sorted(
            dates,
            key=lambda date_value: parse_datetime_value(date_value) or datetime.min,
            reverse=True,
        )[:3]

    dates = [format_short_date(date_value) for date_value in dates]

    return {
        "fecha": dates[0] if len(dates) > 0 else None,
        "fecha_2": dates[1] if len(dates) > 1 else None,
        "fecha_3": dates[2] if len(dates) > 2 else None,
    }


def clean_certified_email_rows(rows: list[dict]) -> list[dict]:
    clean_rows = []

    for row in rows:
        clean_row = {}

        for column_name, value in row.items():
            if column_name == "nombres_email":
                clean_row.update(split_names_email(value))
            elif column_name == "numero_linea_csv":
                clean_row[column_name] = value
            elif column_name == "fecha":
                clean_row.update(split_date_values(value))
            elif column_name == "asunto":
                clean_row[column_name] = clean_text_value(value)
                clean_row["numeros_asunto"] = extract_subject_numbers(value)
            elif column_name == "adjuntos":
                clean_row[column_name] = clean_text_value(value)
                clean_row["numeros_adjuntos"] = extract_subject_numbers(value)
            else:
                clean_row[column_name] = clean_text_value(value)

        clean_rows.append(clean_row)

    return clean_rows


def validate_certified_email_row(row: dict) -> list[str]:
    errors = []
    if not row.get("fecha") or parse_datetime_value(str(row["fecha"])) is None:
        errors.append("fecha no valida")

    email = clean_text_value(row.get("correo"))
    if not email or EMAIL_PATTERN.fullmatch(email) is None:
        errors.append("correo destinatario no valido")

    subject = clean_text_value(row.get("asunto"))
    if not subject:
        errors.append("asunto vacio")
    elif is_date_bundle(subject):
        errors.append("el asunto contiene una fecha y evidencia desplazamiento")

    event = clean_text_value(row.get("evento"))
    if not event:
        errors.append("evento vacio")
    elif is_date_bundle(event):
        errors.append("el evento contiene una fecha y evidencia desplazamiento")
    else:
        normalized_event = normalize_column_name(event).replace("_", " ")
        subject_markers = (
            "constancia de asistencia",
            "comunicacion dictamen",
            "valoracion virtual",
            "valoracion presencial",
        )
        if any(marker in normalized_event for marker in subject_markers):
            errors.append("el evento contiene un asunto y evidencia desplazamiento")

    return errors


def filter_valid_certified_email_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    valid_rows = []
    validation_errors = []
    for row in rows:
        errors = validate_certified_email_row(row)
        if not errors:
            valid_rows.append(row)
            continue
        validation_errors.append(
            {
                "tipo_error": "fila_correo_certificado_invalida",
                "mensaje": "; ".join(errors),
                "numero_linea_csv": row.get("numero_linea_csv"),
            }
        )
    return valid_rows, validation_errors


def process_payload_data(payload: dict) -> dict:
    payload = validate_payload(payload)
    content = decode_file(payload)

    csv_in_memory = load_certified_email_csv(content)
    raw_rows = csv_in_memory["filas_crudas"]
    clean_rows = clean_certified_email_rows(raw_rows)
    valid_rows, validation_errors = filter_valid_certified_email_rows(clean_rows)
    processing_errors = [
        *csv_in_memory["errores_alineacion"],
        *validation_errors,
    ]
    status = (
        "ERROR"
        if csv_in_memory["total_filas_leidas"] > 0 and not valid_rows
        else "OK"
    )

    return {
        "status": status,
        "tipo_archivo": payload["tipo_archivo"],
        "nombre_archivo": payload["nombre_archivo"],
        "ruta_sharepoint": payload["ruta_sharepoint"],
        "tamano_bytes": len(content),
        "delimitador_csv": csv_in_memory["delimitador"],
        "encabezados_originales": csv_in_memory["encabezados_originales"],
        "encabezados_normalizados": csv_in_memory["encabezados_normalizados"],
        "total_filas_correo_certificado": csv_in_memory["total_filas_leidas"],
        "filas_corregidas_correo_certificado": len(csv_in_memory["filas_reparadas"]),
        "filas_rechazadas_correo_certificado": len(processing_errors),
        "lineas_corregidas_correo_certificado": csv_in_memory["filas_reparadas"],
        "mensaje_error": processing_errors,
        "tabla_correo_certificado": valid_rows,
    }


def process_payload(payload_path: Path = PAYLOAD_PATH) -> dict:
    return process_payload_data(load_payload(payload_path))


def main() -> int:
    payload_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PAYLOAD_PATH

    try:
        result = process_payload(payload_path)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "mensaje": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
