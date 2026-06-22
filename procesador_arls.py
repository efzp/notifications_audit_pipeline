import base64
import binascii
import json
import re
import unicodedata
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from src.utils.normalization import (
    clean_text,
    json_dumps_safe,
    normalize_date,
    normalize_db_string,
    normalize_document,
    sha256_dict,
)


PAYLOAD_PATH = Path("payload_arls.json")

REQUIRED_FIELDS = {
    "tipo_archivo",
    "nombre_archivo",
    "ruta_sharepoint",
    "identifier",
    "file_content_base64",
}

EXPECTED_FILE_TYPE = "ARL_RADICADO_PDF"

SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

DATE_NUMERIC_PATTERN = re.compile(
    r"\b(?P<day>\d{1,2})[/-](?P<month>\d{1,2})[/-](?P<year>\d{2,4})"
    r"(?:\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})(?:\s*(?P<ampm>a\.?\s*m\.?|p\.?\s*m\.?|AM|PM))?)?",
    re.IGNORECASE,
)
DATE_TEXT_PATTERN = re.compile(
    r"\b(?P<day>\d{1,2})\s+de\s+(?P<month>[A-Za-zÁÉÍÓÚÑáéíóúñ]+)"
    r"\s+(?:de\s+)?(?P<year>\d{4})(?:\s+a\s+las\s+(?P<hour>\d{1,2}):(?P<minute>\d{2}))?",
    re.IGNORECASE,
)
DOCUMENT_CONTEXT_PATTERN = re.compile(
    r"(?<!\d)(?:C\.?\s*C\.?|CC|CEDULA|CÉDULA)\s*[:#.\-]?\s*(?P<document>\d[\d.\s-]{4,14}\d)(?!\d)",
    re.IGNORECASE,
)
DOCUMENT_FREE_PATTERN = re.compile(r"(?<!\d)(?P<document>\d{6,11})(?!\d)")

BOLIVAR_PATTERNS = [
    r"SEGUROS\s+BOLIVAR",
    r"SEGUROS\s+BOLÍVAR",
    r"ARL\s+BOLIVAR",
    r"SERVICIOARL2@SEGUROSBOLIVAR\.COM",
    r"SEGUROSBOLIVAR\.COM",
    r"\bBOLIVAR\b",
    r"\bBOLIV\b",
    r"\bBOL\b",
]
COLMENA_PATTERNS = [
    r"COLMENA\s+SEGUROS",
    r"COLMENA\s+ARL",
    r"COLMENA\s+RIESGOS",
    r"NOREPLY@FORMRESPONSE\.COM",
    r"FORMRESPONSE\.COM",
    r"COLMENASEGUROS",
    r"\bCOLMENA\b",
    r"\bCOLM\b",
]


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


def validate_pdf(content: bytes) -> None:
    if not content.startswith(b"%PDF"):
        raise ValueError("El contenido decodificado no parece ser un archivo PDF")


def _normalize_match_text(value: Any) -> str:
    if value is None:
        return ""

    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_value.upper()


def _compact_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def extract_text_pages(content: bytes) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "pypdf no esta instalado. Agregue pypdf a requirements.txt y redeploye la Function."
        ) from exc

    reader = PdfReader(BytesIO(content))
    metadata = {
        str(key).lstrip("/"): str(value)
        for key, value in (reader.metadata or {}).items()
        if value is not None
    }
    pages = []
    for page_index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(
            {
                "numero_pagina": page_index,
                "texto": text,
                "caracteres": len(text),
            }
        )

    return pages, metadata


def _matching_patterns(patterns: list[str], value: Any) -> list[str]:
    text = _normalize_match_text(value)
    return [
        pattern
        for pattern in patterns
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]


def detect_arl(file_name: str, text: str) -> dict[str, Any]:
    file_bolivar = _matching_patterns(BOLIVAR_PATTERNS, file_name)
    file_colmena = _matching_patterns(COLMENA_PATTERNS, file_name)
    text_bolivar = _matching_patterns(BOLIVAR_PATTERNS, text)
    text_colmena = _matching_patterns(COLMENA_PATTERNS, text)

    bolivar_score = len(text_bolivar) * 2 + len(file_bolivar)
    colmena_score = len(text_colmena) * 2 + len(file_colmena)

    if bolivar_score > colmena_score:
        return {
            "arl_detectada": "SEGUROS_BOLIVAR",
            "arl_normalizada": "seguros_bolivar",
            "metodo_deteccion_arl": "TEXTO_PDF" if text_bolivar else "NOMBRE_ARCHIVO",
            "confianza_arl": 1.0 if text_bolivar else 0.85,
            "patrones": {
                "bolivar_nombre": file_bolivar,
                "bolivar_texto": text_bolivar,
                "colmena_nombre": file_colmena,
                "colmena_texto": text_colmena,
            },
        }

    if colmena_score > bolivar_score:
        return {
            "arl_detectada": "COLMENA_SEGUROS",
            "arl_normalizada": "colmena_seguros",
            "metodo_deteccion_arl": "TEXTO_PDF" if text_colmena else "NOMBRE_ARCHIVO",
            "confianza_arl": 1.0 if text_colmena else 0.85,
            "patrones": {
                "bolivar_nombre": file_bolivar,
                "bolivar_texto": text_bolivar,
                "colmena_nombre": file_colmena,
                "colmena_texto": text_colmena,
            },
        }

    return {
        "arl_detectada": None,
        "arl_normalizada": None,
        "metodo_deteccion_arl": "SIN_PATRON",
        "confianza_arl": 0.0,
        "patrones": {
            "bolivar_nombre": file_bolivar,
            "bolivar_texto": text_bolivar,
            "colmena_nombre": file_colmena,
            "colmena_texto": text_colmena,
        },
    }


def _extract_document_from_source(source: str, contextual_only: bool) -> tuple[str | None, str | None]:
    for pattern in (DOCUMENT_CONTEXT_PATTERN,):
        match = pattern.search(source)
        if match:
            document = normalize_document(match.group("document"))
            if document and 5 <= len(document) <= 11:
                return document, "CON_TEXTO_CC"

    if contextual_only:
        return None, None

    match = DOCUMENT_FREE_PATTERN.search(source)
    if match:
        document = normalize_document(match.group("document"))
        if document and 5 <= len(document) <= 11:
            return document, "NUMERO_SUELTO"

    return None, None


def detect_document(file_name: str, text: str) -> dict[str, Any]:
    document, method = _extract_document_from_source(file_name, contextual_only=False)
    if document:
        return {
            "cedula_detectada": document,
            "cedula_normalizada": document,
            "metodo_deteccion_cedula": f"NOMBRE_ARCHIVO_{method}",
            "confianza_cedula": 0.95 if method == "CON_TEXTO_CC" else 0.85,
        }

    document, method = _extract_document_from_source(text[:5000], contextual_only=False)
    if document:
        return {
            "cedula_detectada": document,
            "cedula_normalizada": document,
            "metodo_deteccion_cedula": f"TEXTO_PDF_{method}",
            "confianza_cedula": 0.90 if method == "CON_TEXTO_CC" else 0.70,
        }

    return {
        "cedula_detectada": None,
        "cedula_normalizada": None,
        "metodo_deteccion_cedula": "SIN_PATRON",
        "confianza_cedula": 0.0,
    }


def _normalize_year(value: str) -> int:
    year = int(value)
    return 2000 + year if year < 100 else year


def _normalize_hour(hour: str | None, minute: str | None, ampm: str | None) -> str | None:
    if not hour or not minute:
        return None

    hour_value = int(hour)
    minute_value = int(minute)
    ampm_text = _normalize_match_text(ampm)
    if ampm_text.startswith("P") and hour_value < 12:
        hour_value += 12
    elif ampm_text.startswith("A") and hour_value == 12:
        hour_value = 0

    return f"{hour_value:02d}:{minute_value:02d}:00"


def _date_from_match(match: re.Match[str]) -> tuple[str | None, str | None]:
    groups = match.groupdict()
    day = int(groups["day"])
    raw_month = groups["month"]
    if raw_month.isdigit():
        month = int(raw_month)
    else:
        month = SPANISH_MONTHS.get(_normalize_match_text(raw_month).lower())
        if month is None:
            return None, None
    year = _normalize_year(groups["year"])

    try:
        date_value = datetime(year, month, day).date().isoformat()
    except ValueError:
        return None, None

    time_value = _normalize_hour(
        groups.get("hour"),
        groups.get("minute"),
        groups.get("ampm"),
    )
    return date_value, time_value


def _find_date(pattern: re.Pattern[str], source: str) -> tuple[str | None, str | None, str | None]:
    match = pattern.search(source)
    if not match:
        return None, None, None

    date_value, time_value = _date_from_match(match)
    return date_value, time_value, match.group(0)


def detect_dates(text: str) -> dict[str, Any]:
    compact = _compact_text(text)
    received_patterns = [
        (
            "BOLIVAR_FECHA_HORA_RECIBIDO",
            re.compile(r"Fecha\s+y\s+hora\s+de\s+recibido\s*:\s*(.{0,90})", re.IGNORECASE),
        ),
        (
            "COLMENA_FECHA_RADICADO",
            re.compile(r"Fecha\s+de\s*Radicado\s*(.{0,90})", re.IGNORECASE),
        ),
        (
            "COLMENA_RADICADO",
            re.compile(r"\bRadicado\s+(.{0,90})", re.IGNORECASE),
        ),
    ]
    email_patterns = [
        (
            "EMAIL_ENVIADO",
            re.compile(r"Enviado\s+el\s*:\s*(.{0,120})", re.IGNORECASE),
        ),
        (
            "EMAIL_FECHA_OUTLOOK",
            re.compile(r"\bFecha\s*[A-Za-zÁÉÍÓÚÑáéíóúñ]{0,12}\s+(.{0,70})", re.IGNORECASE),
        ),
    ]

    received_date = None
    received_time = None
    received_source = None
    received_text = None
    for method, pattern in received_patterns:
        context_match = pattern.search(compact)
        if not context_match:
            continue
        context = context_match.group(1)
        for date_pattern in (DATE_TEXT_PATTERN, DATE_NUMERIC_PATTERN):
            received_date, received_time, matched_text = _find_date(date_pattern, context)
            if received_date:
                received_source = method
                received_text = matched_text
                break
        if received_date:
            break

    email_date = None
    email_time = None
    email_source = None
    email_text = None
    for method, pattern in email_patterns:
        context_match = pattern.search(compact)
        if not context_match:
            continue
        context = context_match.group(1)
        for date_pattern in (DATE_TEXT_PATTERN, DATE_NUMERIC_PATTERN):
            email_date, email_time, matched_text = _find_date(date_pattern, context)
            if email_date:
                email_source = method
                email_text = matched_text
                break
        if email_date:
            break

    if not received_date:
        received_date = email_date
        received_time = email_time
        received_source = email_source
        received_text = email_text

    return {
        "fecha_recibo_comunicacion": received_date,
        "hora_recibo_comunicacion": received_time,
        "fecha_correo": email_date,
        "hora_correo": email_time,
        "metodo_deteccion_fecha": received_source or "SIN_PATRON",
        "confianza_fecha": 1.0
        if received_source in {"BOLIVAR_FECHA_HORA_RECIBIDO", "COLMENA_FECHA_RADICADO", "COLMENA_RADICADO"}
        else 0.75 if received_source else 0.0,
        "patrones_fecha": {
            "fecha_recibo_texto": received_text,
            "fecha_correo_texto": email_text,
            "metodo_correo": email_source,
        },
    }


def process_payload_data(payload: dict[str, Any]) -> dict[str, Any]:
    payload = validate_payload(payload)
    content = decode_file(payload)
    validate_pdf(content)

    pages, metadata = extract_text_pages(content)
    text = "\n".join(page["texto"] for page in pages)
    file_name = str(payload.get("nombre_archivo") or "")

    arl_result = detect_arl(file_name, text)
    document_result = detect_document(file_name, text)
    date_result = detect_dates(text)

    row = {
        "nombre_archivo": file_name,
        "ruta_sharepoint": payload.get("ruta_sharepoint"),
        "identifier": payload.get("identifier"),
        **arl_result,
        **document_result,
        **date_result,
        "numero_paginas": len(pages),
        "texto_patrones_json": {
            "arl": arl_result.get("patrones"),
            "fecha": date_result.get("patrones_fecha"),
        },
        "texto_completo": text,
        "metadata_pdf_json": metadata,
    }
    row["hash_arl_radicado"] = sha256_dict(
        {
            "arl_normalizada": row.get("arl_normalizada"),
            "cedula_normalizada": row.get("cedula_normalizada"),
            "fecha_recibo_comunicacion": row.get("fecha_recibo_comunicacion"),
            "nombre_archivo": file_name,
        }
    )

    errors = []
    if not row.get("arl_detectada"):
        errors.append("No fue posible detectar ARL en el PDF")
    if not row.get("cedula_normalizada"):
        errors.append("No fue posible detectar cedula en el PDF ni en el nombre")
    if not row.get("fecha_recibo_comunicacion"):
        errors.append("No fue posible detectar fecha de recibo/radicado en el PDF")

    return {
        "status": "OK" if not errors else "OK_CON_ALERTAS",
        "tipo_archivo": payload.get("tipo_archivo"),
        "nombre_archivo": file_name,
        "ruta_sharepoint": payload.get("ruta_sharepoint"),
        "carpeta_origen": payload.get("carpeta_origen"),
        "carpeta_destino": payload.get("carpeta_destino"),
        "tamano_bytes": len(content),
        "total_arls_radicado_pdf": 1,
        "notificaciones_detectadas": 1 if row.get("cedula_normalizada") else 0,
        "tabla_arls_radicado_pdf": [row],
        "mensaje_error": errors,
    }


if __name__ == "__main__":
    result = process_payload_data(load_payload(PAYLOAD_PATH))
    print(json_dumps_safe(result))
