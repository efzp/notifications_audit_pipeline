import base64
import binascii
import json
import re
import sys
import unicodedata
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any


PAYLOAD_PATH = Path("payload_audiencias.json")

REQUIRED_FIELDS = {
    "tipo_archivo",
    "nombre_archivo",
    "ruta_sharepoint",
    "identifier",
    "file_content_base64",
}

EXPECTED_FILE_TYPE = "ACTA_AUDIENCIA_PDF"


DATE_PATTERNS = [
    re.compile(r"\b(?P<year>\d{4})[/-](?P<month>\d{1,2})[/-](?P<day>\d{1,2})\b"),
    re.compile(r"\b(?P<day>\d{1,2})[/-](?P<month>\d{1,2})[/-](?P<year>\d{2,4})\b"),
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


def normalize_whitespace(value: object) -> str | None:
    if value is None:
        return None

    clean_value = re.sub(r"\s+", " ", str(value)).strip()
    return clean_value or None


def normalize_db_string(value: object) -> str | None:
    clean_value = normalize_whitespace(value)
    if not clean_value:
        return None

    normalized = unicodedata.normalize("NFKD", clean_value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    normalized_value = re.sub(r"[^A-Za-z0-9]+", "_", ascii_value)
    return normalized_value.strip("_").lower() or None


def normalize_room_value(value: object) -> str | None:
    clean_value = normalize_whitespace(value)
    if not clean_value:
        return None

    without_prefix = re.sub(
        r"^\s*sala\s+",
        "",
        clean_value,
        flags=re.IGNORECASE,
    )
    return normalize_db_string(without_prefix)


def normalize_year(year: str) -> int:
    value = int(year)
    return 2000 + value if value < 100 else value


def normalize_date(value: object) -> str | None:
    clean_value = normalize_whitespace(value)
    if not clean_value:
        return None

    for pattern in DATE_PATTERNS:
        match = pattern.search(clean_value)
        if not match:
            continue

        groups = match.groupdict()
        day = int(groups["day"])
        month = int(groups["month"])
        year = normalize_year(groups["year"])

        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            continue

    return None


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


def extract_acta_number(text: str, file_name: str) -> str | None:
    for source in (file_name, text[:4000]):
        match = re.search(
            r"\b(?:acta(?:\s+general)?(?:\s+de\s+audiencia)?|audiencia)\s*(?:n(?:o|umero)?\.?\s*)?(?P<number>\d{1,8})\b",
            source,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group("number")

    return None


def extract_room(text: str, file_name: str) -> str | None:
    for source in (file_name, text[:4000]):
        match = re.search(
            r"\bsala\s*(?:n(?:o|umero)?\.?\s*)?(?P<room>[A-Za-z0-9]+)",
            source,
            flags=re.IGNORECASE,
        )
        if match:
            return f"Sala {match.group('room')}"

    return None


def extract_first_date(text: str, file_name: str) -> str | None:
    return normalize_date(file_name) or normalize_date(text[:4000])


def extract_distinct_matches(pattern: str, text: str) -> list[str]:
    seen = set()
    values = []

    for match in re.finditer(pattern, text):
        value = re.sub(r"\D", "", match.group(0))
        if value in seen:
            continue

        values.append(value)
        seen.add(value)

    return values


def strip_role_suffix(value: str | None) -> str | None:
    clean_value = normalize_whitespace(value)
    if not clean_value:
        return None

    return normalize_whitespace(
        re.sub(
            r"\s*\((?:MEDICO|M[EÉ]DICO|FISIOTERAPEUTA|TERAPEUTA|PSIC[OÓ]LOG[AO])\)\s*$",
            "",
            clean_value,
            flags=re.IGNORECASE,
        )
    )


def extract_attendees(text: str) -> list[dict[str, str | None]]:
    compact_text = re.sub(r"\s+", " ", text)
    quorum_match = re.search(
        r"asisten todos los integrantes.*?,\s*(?P<names>.*?)(?:,\s*con quienes|\s+con quienes)",
        compact_text,
        flags=re.IGNORECASE,
    )
    if not quorum_match:
        return []

    attendees = []
    for raw_name, raw_role in re.findall(
        r"([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ\s]+?)\s*\(([^()]+)\)",
        quorum_match.group("names"),
    ):
        role = normalize_whitespace(raw_role)
        attendees.append(
            {
                "nombre": strip_role_suffix(raw_name),
                "rol": role.upper() if role else None,
            }
        )

    return attendees


def extract_medicos_firmantes(attendees: list[dict[str, str | None]]) -> list[str]:
    return [
        attendee["nombre"]
        for attendee in attendees
        if attendee.get("nombre")
        and (
            "medic" in (normalize_db_string(attendee.get("rol") or "") or "")
            or "mdico" in (normalize_db_string(attendee.get("rol") or "") or "")
        )
    ]


def extract_terapeuta_o_psicologo(attendees: list[dict[str, str | None]]) -> str | None:
    for attendee in attendees:
        role = normalize_db_string(attendee.get("rol") or "")
        if attendee.get("nombre") and (
            "terapeuta" in role
            or "fisioterapeuta" in role
            or "psicolog" in role
        ):
            return attendee["nombre"]

    return None


def extract_proyectado_por(text: str) -> str | None:
    for line in text.splitlines():
        match = re.search(
            r"\bproyectad[oa]\s+por\s*:?\s*(?P<value>.+?)\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if not match:
            continue

        value = normalize_whitespace(match.group("value"))
        if value:
            return value[:500]

    compact_text = re.sub(r"\s+", " ", text)
    match = re.search(
        r"\bproyectad[oa]\s+por\s*:?\s*(?P<value>.*?)(?=\s+(?:revisad[oa]\s+por|aprobado|firma|página|$))",
        compact_text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    value = normalize_whitespace(match.group("value"))
    if not value:
        return None

    return value[:500]


def evaluate_signature_status(text: str, expected_names: list[str]) -> dict[str, Any]:
    normalized_text = normalize_db_string(text) or ""
    has_signature_terms = any(
        term in normalized_text
        for term in (
            "firma",
            "firmado",
            "firmante",
            "firma_digital",
            "firmado_digitalmente",
        )
    )
    signed_names = [
        name
        for name in expected_names
        if name and (normalize_db_string(name) or "") in normalized_text
    ]

    if has_signature_terms and expected_names and len(signed_names) >= len(expected_names):
        status = "SI"
    elif has_signature_terms:
        status = "PARCIAL"
    else:
        status = "INDETERMINADO"

    return {
        "documento_cuenta_con_firmas": 1 if status in {"SI", "PARCIAL"} else None,
        "estado_validacion_firmas": status,
        "firmantes_validados": signed_names,
        "criterio_validacion_firmas": (
            "Heuristica basada en texto extraido del PDF; no valida criptograficamente firmas "
            "ni detecta imagenes de firma si no hay texto asociado."
        ),
    }


def split_entity_and_doctor(value: object, doctors: list[str]) -> dict[str, str | None]:
    clean_value = normalize_whitespace(value)
    if not clean_value:
        return {"entidad_remitente": None, "medico_ponente": None}

    for doctor in sorted([doctor for doctor in doctors if doctor], key=len, reverse=True):
        if doctor not in clean_value:
            continue

        entity = normalize_whitespace(clean_value.replace(doctor, " "))
        return {
            "entidad_remitente": entity,
            "medico_ponente": doctor,
        }

    return {
        "entidad_remitente": clean_value,
        "medico_ponente": None,
    }


def build_audiencia_case_rows(acta_row: dict[str, Any]) -> list[dict[str, Any]]:
    doctors = acta_row.get("medicos_firmantes") or []
    therapist = acta_row.get("terapeuta_o_psicologo")
    rows = []

    for case_row in acta_row.get("casos_detectados") or []:
        entity_doctor = split_entity_and_doctor(
            case_row.get("entidad_medico_texto"),
            doctors,
        )
        doctor_speaker = entity_doctor["medico_ponente"]
        principal_doctor = next(
            (doctor for doctor in doctors if doctor and doctor != doctor_speaker),
            None,
        )

        rows.append(
            {
                "numero_orden": case_row.get("numero_orden"),
                "numero_radicado": case_row.get("numero_caso"),
                "nombre_paciente": case_row.get("nombre"),
                "tipo_identificacion": case_row.get("tipo_identificacion"),
                "numero_identificacion": case_row.get("numero_identificacion"),
                "entidad_remitente": entity_doctor["entidad_remitente"],
                "medico_ponente": doctor_speaker,
                "medico_principal": principal_doctor,
                "terapeuta_psicologa": therapist,
                "fecha_audiencia": acta_row.get("fecha_audiencia"),
                "sala": acta_row.get("sala"),
                "sala_normalizada": acta_row.get("sala_normalizada"),
                "numero_acta": acta_row.get("numero_acta"),
                "numero_acta_normalizado": acta_row.get("numero_acta_normalizado"),
                "fila_texto": case_row.get("fila_texto"),
                "fila_caso": case_row,
            }
        )

    return rows


def extract_case_rows(text: str) -> list[dict[str, Any]]:
    compact_text = re.sub(r"\s+", " ", text)
    row_pattern = re.compile(
        r"(?P<orden>\d{1,3})\s+"
        r"(?P<numero_caso>JN\d+(?:\s*-\s*\d+)?)\s+"
        r"(?P<body>.*?)(?="
        r"\s+\d{1,3}\s+JN\d+"
        r"|\s+(?:3\s*-\s*)?DECISIONES\b"
        r"|\s+La cantidad de elementos es de\b"
        r"|\s+Se abre el debate\b"
        r"|\s+ACTA GENERAL DE AUDIENCIA\b"
        r"|\s+Página\s+\d+\s+de\s+\d+"
        r"|$)",
        flags=re.IGNORECASE,
    )
    id_pattern = re.compile(
        r"\b(?P<tipo>CC|CE|TI|RC|PA|PEP|NIT)\s+(?P<numero>\d[\d.,-]*)\b",
        flags=re.IGNORECASE,
    )
    rows = []

    for match in row_pattern.finditer(compact_text):
        body = normalize_whitespace(match.group("body")) or ""
        id_match = id_pattern.search(body)
        if not id_match:
            continue

        nombre = normalize_whitespace(body[: id_match.start()])
        entidad_medico = normalize_whitespace(body[id_match.end() :])
        numero_identificacion = re.sub(r"\D", "", id_match.group("numero"))

        rows.append(
            {
                "numero_orden": int(match.group("orden")),
                "numero_caso": normalize_whitespace(match.group("numero_caso")),
                "nombre": nombre,
                "tipo_identificacion": id_match.group("tipo").upper(),
                "numero_identificacion": numero_identificacion or None,
                "entidad_medico_texto": entidad_medico,
                "fila_texto": normalize_whitespace(match.group(0)),
            }
        )

    return rows


def build_acta_row(payload: dict[str, Any], content: bytes) -> dict[str, Any]:
    pages, metadata = extract_text_pages(content)
    full_text = "\n\n".join(page["texto"] for page in pages).strip()
    file_name = payload["nombre_archivo"]
    numero_acta = extract_acta_number(full_text, file_name)
    sala = extract_room(full_text, file_name)
    fecha_audiencia = extract_first_date(full_text, file_name)
    casos = extract_case_rows(full_text)
    asistentes = extract_attendees(full_text)
    medicos_firmantes = extract_medicos_firmantes(asistentes)
    terapeuta_o_psicologo = extract_terapeuta_o_psicologo(asistentes)
    firma_status = evaluate_signature_status(
        full_text,
        [*medicos_firmantes, terapeuta_o_psicologo],
    )

    return {
        "tipo_archivo": payload["tipo_archivo"],
        "nombre_archivo": file_name,
        "ruta_sharepoint": payload["ruta_sharepoint"],
        "identifier": payload["identifier"],
        "numero_acta": numero_acta,
        "numero_acta_normalizado": normalize_db_string(numero_acta),
        "fecha_audiencia": fecha_audiencia,
        "sala": sala,
        "sala_normalizada": normalize_room_value(sala),
        "numero_paginas": len(pages),
        "cantidad_casos": len(casos),
        "medicos_firmantes": medicos_firmantes,
        "terapeuta_o_psicologo": terapeuta_o_psicologo,
        "proyectado_por": extract_proyectado_por(full_text),
        **firma_status,
        "asistentes_detectados": asistentes,
        "casos_detectados": casos,
        "radicados_detectados": extract_distinct_matches(r"(?<!\d)\d{6,}(?!\d)", full_text),
        "cedulas_detectadas": extract_distinct_matches(r"(?<!\d)\d{7,11}(?!\d)", full_text),
        "texto_completo": full_text,
        "texto_paginas": pages,
        "metadata_pdf": metadata,
    }


def process_payload_data(payload: dict[str, Any]) -> dict[str, Any]:
    payload = validate_payload(payload)
    content = decode_file(payload)
    validate_pdf(content)
    acta_row = build_acta_row(payload, content)
    audiencia_case_rows = build_audiencia_case_rows(acta_row)

    return {
        "status": "OK",
        "tipo_archivo": payload["tipo_archivo"],
        "nombre_archivo": payload["nombre_archivo"],
        "ruta_sharepoint": payload["ruta_sharepoint"],
        "tamano_bytes": len(content),
        "total_actas_audiencia_pdf": 1,
        "total_casos_acta": len(audiencia_case_rows),
        "tabla_estructura_acta": [acta_row],
        "tabla_audiencia_caso": audiencia_case_rows,
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

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
