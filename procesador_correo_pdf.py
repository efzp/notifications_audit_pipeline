import base64
import binascii
import io
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from procesador_correo import EMAIL_PATTERN, extract_subject_numbers


EXPECTED_FILE_TYPES = {
    "CORREO_CERTIFICADO_PDF",
    "PDF_CORREO_CERTIFICADO",
}
REQUIRED_FIELDS = {
    "tipo_archivo",
    "nombre_archivo",
    "ruta_sharepoint",
    "identifier",
    "file_content_base64",
}

STATUS_OPENED = "El destinatario abrio la notificacion"
STATUS_DESTINATION_SERVER = "Traza entrega al servidor de destino"
STATUS_DELIVERY_FAILED = "No fue posible la entrega al destinatario"
STATUS_RECEIPT = "Acuse de recibo"

FILENAME_PATTERN = re.compile(
    r"^\s*\d+\s*T\s+COMUNICACI[OÓ]N\s+DICTAMEN\s+"
    r"(?P<nombre>.+?)\s+CC\s+(?P<cedula>\d+)\s+"
    r"(?P<destinatario>.+?)(?:__[A-Za-z0-9]+)?\.pdf\s*$",
    re.IGNORECASE,
)
DATE_PATTERN = re.compile(r"(?<!\d)\d{1,2}/\d{1,2}/\d{4}")

# Use Unicode escapes so the pattern behaves identically when deployed on Linux.
FILENAME_PATTERN = re.compile(
    r"^\s*\d+\s*T\s+COMUNICACI(?:O|\u00d3)N\s+DICTAMEN\s+"
    r"(?P<nombre>.+?)\s+CC\s+(?P<cedula>\d+)\s+"
    r"(?P<destinatario>.+?)(?:__[A-Za-z0-9]+)?\.pdf\s*$",
    re.IGNORECASE,
)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    clean_value = re.sub(r"\s+", " ", str(value)).strip()
    return clean_value or None


def _ascii_compact(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9@.]+", "", ascii_value)


def _decode_pdf(payload: dict[str, Any]) -> bytes:
    raw_content = payload["file_content_base64"]
    if isinstance(raw_content, str) and "," in raw_content[:100]:
        raw_content = raw_content.split(",", 1)[1]
    try:
        content = base64.b64decode(raw_content, validate=False)
    except (binascii.Error, TypeError, ValueError) as exc:
        raise ValueError("file_content_base64 no es un Base64 valido") from exc
    if not content.startswith(b"%PDF"):
        raise ValueError("El contenido recibido no corresponde a un PDF")
    return content


def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(field for field in REQUIRED_FIELDS if not payload.get(field))
    if missing:
        raise ValueError(f"Faltan campos obligatorios en el payload: {', '.join(missing)}")
    file_type = str(payload["tipo_archivo"]).strip().upper()
    if file_type not in EXPECTED_FILE_TYPES:
        raise ValueError(
            "tipo_archivo debe ser CORREO_CERTIFICADO_PDF, recibido: "
            f"{payload['tipo_archivo']}"
        )
    if Path(str(payload["nombre_archivo"])).suffix.lower() != ".pdf":
        raise ValueError("nombre_archivo debe tener extension .pdf")
    return payload


def _extract_pdf_text(content: bytes) -> tuple[str, int]:
    reader = PdfReader(io.BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not _clean_text(text):
        raise ValueError("El PDF no contiene texto extraible")
    return text, len(reader.pages)


def _parse_filename(filename: str) -> dict[str, str]:
    match = FILENAME_PATTERN.match(filename)
    if not match:
        raise ValueError(
            "El nombre del PDF no cumple el patron esperado: "
            "<prefijo> COMUNICACION DICTAMEN <nombre> CC <cedula> <destinatario>.pdf"
        )
    destination = _clean_text(match.group("destinatario")) or ""
    destination_key = _ascii_compact(destination)
    destination_map = {
        "paciente": "PACIENTES",
        "regional": "REGIONAL",
        "juntaregionaldecalificacioninvalidez": "REGIONAL",
        "companiadeseguros": "ASEGURADORAS",
        "afp": "AFP",
        "arl": "ARL",
        "eps": "EPS",
        "empleador": "EMPLEADOR",
    }
    normalized_destination = destination_map.get(destination_key)
    if normalized_destination is None:
        raise ValueError(f"Tipo de destinatario no reconocido en el PDF: {destination}")
    return {
        "nombre_caso_detectado": _clean_text(match.group("nombre")) or "",
        "cedula_detectada": match.group("cedula"),
        "tipo_destinatario_detectado": normalized_destination,
    }


def _extract_section(text: str, start_pattern: str, end_pattern: str) -> str:
    match = re.search(
        rf"{start_pattern}(.*?)(?:{end_pattern})",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(1) if match else ""


def _delivery_section(text: str) -> str:
    return _extract_section(
        text,
        r"Estado\s*/?\s*Status\s*de\s*Entrega",
        r"\*?\s*UTC\s*representa|Sobre\s*del\s*Mensaje",
    )


def normalize_pdf_status(text: str) -> tuple[str, str]:
    section = _delivery_section(text)
    compact = _ascii_compact(section)
    if any(
        token in compact
        for token in (
            "laentregafallo",
            "nofueposiblelaentrega",
            "noentregado",
            "undeliverable",
            "bounced",
        )
    ):
        return STATUS_DELIVERY_FAILED, "LA_ENTREGA_FALLO"
    if (
        "entregadoacasilleropostal" in compact
        or "deliveryconfirmedbyrecipientmailserver" in compact
    ):
        return STATUS_RECEIPT, "ENTREGADO_A_CASILLERO_POSTAL"
    if "entregadoalservidordecorreo" in compact or "relayed" in compact:
        return STATUS_DESTINATION_SERVER, "ENTREGADO_AL_SERVIDOR_DE_CORREO"
    if "abiertohttp" in compact or "openedhttp" in compact:
        return STATUS_OPENED, "ABIERTO"
    raise ValueError("No fue posible reconocer el estado de entrega del PDF")


def _parse_date(value: str) -> str:
    return datetime.strptime(value, "%m/%d/%Y").date().isoformat()


def _last_date(section: str) -> str | None:
    values = DATE_PATTERN.findall(section)
    return _parse_date(values[-1]) if values else None


def _extract_dates(text: str) -> tuple[str | None, str | None]:
    rmail_section = _extract_section(
        text,
        r"Recibido\s*por\s*Sistema\s*RMail\s*:",
        r"C[oó]digo\s*de\s*Cliente|Estad[ií]sticas\s*del\s*Mensaje",
    )
    delivery_section = _delivery_section(text)
    sent_date = _last_date(rmail_section)
    event_date = _last_date(delivery_section)
    if sent_date is None:
        # Some RPost variants place the whole RMail timestamp on one compact line.
        rmail_line = re.search(
            r"Recibido\s*por\s*Sistema\s*RMail\s*:\s*([^\r\n]+)",
            text,
            flags=re.IGNORECASE,
        )
        sent_date = _last_date(rmail_line.group(1)) if rmail_line else None
    if sent_date is None:
        sent_date = event_date
    return sent_date, event_date


def _extract_recipient_email(text: str) -> str:
    match = re.search(
        rf"Para\s*:\s*<?\s*({EMAIL_PATTERN.pattern})\s*>?",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).lower()
    section_emails = EMAIL_PATTERN.findall(_delivery_section(text))
    if section_emails:
        return section_emails[0].lower()
    raise ValueError("No fue posible extraer el correo destinatario del PDF")


def _extract_subject(text: str, file_data: dict[str, str]) -> tuple[str, str | None]:
    match = re.search(
        r"Asunto\s*:\s*(.*?)\s*Para\s*:",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    raw_subject = _clean_text(match.group(1)) if match else None
    if raw_subject and len(raw_subject.split()) >= 2:
        return raw_subject, raw_subject
    canonical = (
        "COMUNICACION DICTAMEN "
        f"{file_data['nombre_caso_detectado']} CC {file_data['cedula_detectada']}"
    )
    return canonical, raw_subject


def _extract_tracking(text: str) -> str:
    match = re.search(
        r"Seguimiento\s*/?\s*Tracking\s*:\s*([A-Fa-f0-9]{20,})",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError("No fue posible extraer el numero de seguimiento del PDF")
    return match.group(1).upper()


def _extract_network_id(text: str) -> str | None:
    match = re.search(
        r"ID\s*de\s*Red\s*/?\s*Network\s*:\s*([^\s]+)",
        text,
        flags=re.IGNORECASE,
    )
    return _clean_text(match.group(1)) if match else None


def _extract_attachments(text: str) -> list[str]:
    section = _extract_section(
        text,
        r"Nombre\s*del\s*Archivo\s*:",
        r"Auditor[ií]a\s*de\s*Ruta\s*de\s*Entrega",
    )
    attachments = []
    seen = set()
    for value in re.findall(r"(?im)^\s*\d+\s+(.+?\.pdf)\s*$", section):
        clean_value = _clean_text(value)
        if clean_value and clean_value not in seen:
            attachments.append(clean_value)
            seen.add(clean_value)
    return attachments


def extract_pdf_notification(
    content: bytes,
    filename: str,
    ruta_sharepoint: str,
    identifier: str,
) -> dict[str, Any]:
    text, page_count = _extract_pdf_text(content)
    file_data = _parse_filename(filename)
    status, raw_status = normalize_pdf_status(text)
    sent_date, event_date = _extract_dates(text)
    if sent_date is None:
        raise ValueError("No fue posible extraer la fecha de envio certificada del PDF")
    email = _extract_recipient_email(text)
    subject, raw_subject = _extract_subject(text, file_data)
    tracking = _extract_tracking(text)
    attachments = _extract_attachments(text)
    attachment_text = "| ".join(attachments) if attachments else None

    audit = {
        **file_data,
        "nombre_archivo": filename,
        "ruta_sharepoint": ruta_sharepoint,
        "identifier": identifier,
        "numero_paginas": page_count,
        "estado_correo_original": raw_status,
        "estado_correo_normalizado": status,
        "asunto_original": raw_subject,
        "correo_destinatario": email,
        "fecha_envio": sent_date,
        "fecha_evento": event_date,
        "codigo_seguimiento": tracking,
        "id_red": _extract_network_id(text),
        "adjuntos": attachments,
        "metodo_normalizacion_estado": "RPOST_STATUS_MAPPING_V1",
    }
    numbers_subject = extract_subject_numbers(subject)
    numbers_attachments = extract_subject_numbers(attachment_text)
    if file_data["cedula_detectada"] not in numbers_subject:
        numbers_subject.append(file_data["cedula_detectada"])
    if file_data["cedula_detectada"] not in numbers_attachments:
        numbers_attachments.append(file_data["cedula_detectada"])

    return {
        "numero_linea_csv": 1,
        "fecha": sent_date,
        "fecha_2": event_date,
        "fecha_3": None,
        "nombres": None,
        "correo": email,
        "asunto": subject,
        "asunto_normalizado": _ascii_compact(subject),
        "evento": status,
        "id": tracking,
        "adjuntos": attachment_text,
        "numeros_asunto": numbers_subject,
        "numeros_adjuntos": numbers_attachments,
        "nombre_archivo": filename,
        "fila_correo_certificado": audit,
        **file_data,
    }


def process_payload_data(payload: dict[str, Any]) -> dict[str, Any]:
    payload = validate_payload(payload)
    content = _decode_pdf(payload)
    row = extract_pdf_notification(
        content,
        str(payload["nombre_archivo"]),
        str(payload["ruta_sharepoint"]),
        str(payload["identifier"]),
    )
    return {
        "status": "OK",
        "tipo_archivo": str(payload["tipo_archivo"]),
        "nombre_archivo": str(payload["nombre_archivo"]),
        "ruta_sharepoint": str(payload["ruta_sharepoint"]),
        "identifier": str(payload["identifier"]),
        "extension_archivo": ".pdf",
        "tamano_bytes": len(content),
        "total_filas_correo_certificado": 1,
        "filas_corregidas_correo_certificado": 0,
        "filas_rechazadas_correo_certificado": 0,
        "tabla_correo_certificado": [row],
        "cedula_detectada": row["cedula_detectada"],
        "cedula_normalizada": row["cedula_detectada"],
        "tipo_destinatario_detectado": row["tipo_destinatario_detectado"],
        "estado_correo": row["evento"],
        "_recalcular_cruce": False,
    }


def main() -> int:
    payload_path = Path("payload_correo_certificado_pdf.json")
    try:
        with payload_path.open("r", encoding="utf-8") as file:
            result = process_payload_data(json.load(file))
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "mensaje": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
