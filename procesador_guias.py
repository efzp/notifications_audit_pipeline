import base64
import binascii
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any


PAYLOAD_PATH = Path("payload_guias_correo_fisico.json")

REQUIRED_FIELDS = {
    "tipo_archivo",
    "nombre_archivo",
    "ruta_sharepoint",
    "identifier",
    "file_content_base64",
}

EXPECTED_FILE_TYPE = "GUIAS_CORREO_FISICO"


def load_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo: {path}")

    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    return validate_payload(payload)


def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(field for field in REQUIRED_FIELDS if not payload.get(field))
    if missing:
        raise ValueError(f"Faltan campos obligatorios en el payload: {', '.join(missing)}")

    if payload["tipo_archivo"] != EXPECTED_FILE_TYPE:
        raise ValueError(
            f"tipo_archivo debe ser {EXPECTED_FILE_TYPE}, recibido: {payload['tipo_archivo']}"
        )

    return payload


def decode_file(payload: dict[str, Any]) -> bytes:
    raw_content = payload["file_content_base64"]
    if isinstance(raw_content, str) and "," in raw_content[:100]:
        raw_content = raw_content.split(",", 1)[1]

    try:
        return base64.b64decode(raw_content, validate=False)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise ValueError("file_content_base64 no es un Base64 valido") from exc


def clean_text_value(value: Any) -> str | None:
    if value is None:
        return None

    clean_value = re.sub(r"\s+", " ", str(value)).strip()
    return clean_value or None


def normalize_column_name(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    clean_value = re.sub(r"[^A-Za-z0-9]+", "_", ascii_value)
    return clean_value.strip("_").lower()


def make_unique_headers(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    unique_headers = []

    for header in headers:
        normalized = normalize_column_name(header) or "columna_sin_nombre"
        seen[normalized] = seen.get(normalized, 0) + 1
        if seen[normalized] == 1:
            unique_headers.append(normalized)
        else:
            unique_headers.append(f"{normalized}_{seen[normalized]}")

    return unique_headers


def normalize_cell_value(book, cell) -> Any:
    try:
        import xlrd
    except ImportError as exc:
        raise RuntimeError(
            "xlrd no esta instalado. Agregue xlrd>=2.0.1 a requirements.txt y redeploye la Function."
        ) from exc

    if cell.ctype == xlrd.XL_CELL_EMPTY:
        return None

    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            parsed = xlrd.xldate_as_datetime(cell.value, book.datemode)
        except (ValueError, OverflowError):
            return cell.value

        if parsed.time().hour == 0 and parsed.time().minute == 0 and parsed.time().second == 0:
            return parsed.date().isoformat()

        return parsed.isoformat(sep=" ", timespec="seconds")

    if cell.ctype == xlrd.XL_CELL_NUMBER:
        if float(cell.value).is_integer():
            return str(int(cell.value))
        return cell.value

    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)

    return clean_text_value(cell.value)


def read_sheet_rows(book, sheet) -> dict[str, Any]:
    if sheet.nrows == 0:
        return {
            "nombre_hoja": sheet.name,
            "encabezados_originales": [],
            "encabezados_normalizados": [],
            "total_filas": 0,
            "filas": [],
        }

    raw_headers = [clean_text_value(sheet.cell_value(0, col_index)) or "" for col_index in range(sheet.ncols)]
    normalized_headers = make_unique_headers(raw_headers)
    rows = []

    for row_index in range(1, sheet.nrows):
        row = {
            header: normalize_cell_value(book, sheet.cell(row_index, col_index))
            for col_index, header in enumerate(normalized_headers)
        }
        if not any(value not in (None, "") for value in row.values()):
            continue

        row["hoja_origen"] = sheet.name
        row["numero_fila_excel"] = row_index + 1
        rows.append(row)

    return {
        "nombre_hoja": sheet.name,
        "encabezados_originales": raw_headers,
        "encabezados_normalizados": normalized_headers,
        "total_filas": len(rows),
        "filas": rows,
    }


def validate_common_structure(sheet_results: list[dict[str, Any]]) -> dict[str, Any]:
    if not sheet_results:
        return {
            "estructura_compartida": False,
            "mensaje": "El archivo no contiene hojas",
            "diferencias": [],
        }

    base = sheet_results[0]
    differences = []

    for sheet_result in sheet_results[1:]:
        base_headers = base["encabezados_normalizados"]
        current_headers = sheet_result["encabezados_normalizados"]

        if base_headers == current_headers:
            continue

        differences.append(
            {
                "hoja_base": base["nombre_hoja"],
                "hoja_comparada": sheet_result["nombre_hoja"],
                "mismo_orden": base_headers == current_headers,
                "mismo_conjunto": set(base_headers) == set(current_headers),
                "columnas_base": len(base_headers),
                "columnas_comparada": len(current_headers),
                "solo_en_base": [header for header in base_headers if header not in current_headers],
                "solo_en_comparada": [header for header in current_headers if header not in base_headers],
                "diferencias_posicion": [
                    {
                        "posicion": index + 1,
                        "base": left,
                        "comparada": right,
                    }
                    for index, (left, right) in enumerate(zip(base_headers, current_headers))
                    if left != right
                ],
            }
        )

    return {
        "estructura_compartida": not differences,
        "mensaje": "Todas las hojas comparten estructura" if not differences else "Hay diferencias entre hojas",
        "diferencias": differences,
    }


def load_guias_correo_xls(content: bytes) -> dict[str, Any]:
    try:
        import xlrd
    except ImportError as exc:
        raise RuntimeError(
            "xlrd no esta instalado. Agregue xlrd>=2.0.1 a requirements.txt y redeploye la Function."
        ) from exc

    book = xlrd.open_workbook(file_contents=content)
    sheet_results = [read_sheet_rows(book, book.sheet_by_index(index)) for index in range(book.nsheets)]
    structure = validate_common_structure(sheet_results)

    return {
        "hojas": [
            {
                "nombre_hoja": sheet_result["nombre_hoja"],
                "columnas": len(sheet_result["encabezados_normalizados"]),
                "filas": sheet_result["total_filas"],
                "encabezados_originales": sheet_result["encabezados_originales"],
                "encabezados_normalizados": sheet_result["encabezados_normalizados"],
            }
            for sheet_result in sheet_results
        ],
        "estructura": structure,
        "tabla_guias_correo_fisico": [
            row for sheet_result in sheet_results for row in sheet_result["filas"]
        ],
    }


def process_payload_data(payload: dict[str, Any]) -> dict[str, Any]:
    payload = validate_payload(payload)
    content = decode_file(payload)
    workbook_result = load_guias_correo_xls(content)
    rows = workbook_result["tabla_guias_correo_fisico"]

    return {
        "status": "OK" if workbook_result["estructura"]["estructura_compartida"] else "ERROR_ESTRUCTURA",
        "tipo_archivo": payload["tipo_archivo"],
        "nombre_archivo": payload["nombre_archivo"],
        "ruta_sharepoint": payload["ruta_sharepoint"],
        "tamano_bytes": len(content),
        "hojas": workbook_result["hojas"],
        "estructura": workbook_result["estructura"],
        "total_filas_guias_correo_fisico": len(rows),
        "tabla_guias_correo_fisico": rows,
        "fecha_procesamiento": datetime.utcnow().isoformat(timespec="seconds"),
    }


def process_payload(payload_path: Path = PAYLOAD_PATH) -> dict[str, Any]:
    return process_payload_data(load_payload(payload_path))


def main() -> int:
    payload_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PAYLOAD_PATH

    try:
        result = process_payload(payload_path)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "mensaje": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
