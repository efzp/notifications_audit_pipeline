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
    reader = csv.DictReader(io.StringIO(csv_text), delimiter=delimiter)

    if not reader.fieldnames:
        raise ValueError("El CSV de correo certificado no contiene encabezados")

    raw_headers = [header or "" for header in reader.fieldnames]
    normalized_headers = [normalize_column_name(header) for header in raw_headers]
    rows = []

    for line_number, row in enumerate(reader, start=2):
        rows.append(
            {
                normalized_header: row.get(raw_header)
                for raw_header, normalized_header in zip(raw_headers, normalized_headers)
            }
            | {"numero_linea_csv": line_number}
        )

    return {
        "delimitador": delimiter,
        "encabezados_originales": raw_headers,
        "encabezados_normalizados": normalized_headers,
        "filas_crudas": rows,
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

    match = re.search(r"\(([^()]*@[^()]*)\)", clean_value)
    correo = clean_text_value(match.group(1)).lower() if match else None
    nombres = clean_value

    if match:
        nombres = f"{clean_value[:match.start()]} {clean_value[match.end():]}"

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


def process_payload_data(payload: dict) -> dict:
    payload = validate_payload(payload)
    content = decode_file(payload)

    csv_in_memory = load_certified_email_csv(content)
    raw_rows = csv_in_memory["filas_crudas"]
    clean_rows = clean_certified_email_rows(raw_rows)

    return {
        "status": "OK",
        "tipo_archivo": payload["tipo_archivo"],
        "nombre_archivo": payload["nombre_archivo"],
        "ruta_sharepoint": payload["ruta_sharepoint"],
        "tamano_bytes": len(content),
        "delimitador_csv": csv_in_memory["delimitador"],
        "encabezados_originales": csv_in_memory["encabezados_originales"],
        "encabezados_normalizados": csv_in_memory["encabezados_normalizados"],
        "total_filas_correo_certificado": len(raw_rows),
        "tabla_correo_certificado": clean_rows,
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
