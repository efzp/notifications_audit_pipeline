import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

from src.load import db
from src.reconcile.resumen_validacion import refrescar_resumen_validacion_radicado
from src.utils.normalization import (
    json_dumps_safe,
    normalize_date,
    normalize_document,
    normalize_email,
)


ESTADO_CUMPLE = "CUMPLE"
ESTADO_NO_CRUZADO = "NO_CRUZADO"
ESTADO_DOCUMENTO_NO_ENCONTRADO = "DOCUMENTO_NO_ENCONTRADO"
ESTADO_ASUNTO_NO_VALIDO = "ASUNTO_NO_VALIDO"
ESTADO_EVENTO_NO_VALIDO = "EVENTO_NO_VALIDO"
ESTADO_CORREO_NO_COINCIDE = "CORREO_NO_COINCIDE"
ESTADO_FUERA_DE_PLAZO = "FUERA_DE_PLAZO"
ESTADO_REQUIERE_REVISION = "REQUIERE_REVISION_MANUAL"

PLAZO_DIAS_CALENDARIO = 2
FUZZY_THRESHOLD = 0.82
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
MAX_EMAIL_LOCAL_PART_DISTANCE = 2
CRUCE_VERSION = "1.0"
CORREO_FECHA_VENTANA_DIAS = 7


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _normalize_match_text(value: Any) -> str:
    if value is None:
        return ""

    normalized = unicodedata.normalize("NFKD", str(value).lower())
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_value).strip()


def _tokens(value: Any) -> list[str]:
    return _normalize_match_text(value).split()


def _best_token_score(tokens: list[str], expected: str) -> float:
    if not tokens:
        return 0.0

    return max(SequenceMatcher(None, token, expected).ratio() for token in tokens)


def _contains_concept(tokens: list[str], expected: str, threshold: float = FUZZY_THRESHOLD) -> bool:
    return _best_token_score(tokens, expected) >= threshold


def _validate_asunto(asunto: Any) -> tuple[bool, float, str | None]:
    text = _normalize_match_text(asunto)
    tokens = text.split()
    if not text:
        return False, 0.0, None

    communication_score = _best_token_score(tokens, "comunicacion")
    dictamen_score = _best_token_score(tokens, "dictamen")
    calificacion_score = _best_token_score(tokens, "calificacion")
    topic_score = max(dictamen_score, calificacion_score)
    score = round((communication_score + topic_score) / 2, 4)

    if communication_score >= FUZZY_THRESHOLD and topic_score >= FUZZY_THRESHOLD:
        matched_topic = "dictamen" if dictamen_score >= calificacion_score else "calificacion"
        return True, score, matched_topic

    return False, score, None


def _validate_evento(evento: Any) -> tuple[bool, float, str | None]:
    text = _normalize_match_text(evento)
    tokens = text.split()
    if not text:
        return False, 0.0, None

    acuse_score = _best_token_score(tokens, "acuse")
    if acuse_score >= FUZZY_THRESHOLD:
        return True, round(acuse_score, 4), "acuse"

    lectura_score = _best_token_score(tokens, "lectura")
    mensaje_score = _best_token_score(tokens, "mensaje")
    lectura_total = round((lectura_score + mensaje_score) / 2, 4)
    if lectura_score >= FUZZY_THRESHOLD and mensaje_score >= FUZZY_THRESHOLD:
        return True, lectura_total, "lectura_mensaje"

    destinatario_score = _best_token_score(tokens, "destinatario")
    abrio_score = max(
        _best_token_score(tokens, "abrio"),
        _best_token_score(tokens, "abierto"),
        _best_token_score(tokens, "apertura"),
    )
    notificacion_score = _best_token_score(tokens, "notificacion")
    apertura_total = round(
        (destinatario_score + abrio_score + notificacion_score) / 3,
        4,
    )
    if (
        destinatario_score >= FUZZY_THRESHOLD
        and abrio_score >= FUZZY_THRESHOLD
        and notificacion_score >= FUZZY_THRESHOLD
    ):
        return True, apertura_total, "destinatario_abrio_notificacion"

    return False, max(acuse_score, lectura_total, apertura_total), None


def _load_json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return [value]

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []

    return parsed if isinstance(parsed, list) else [parsed]


def _extract_document_numbers(value: Any) -> set[str]:
    if value is None:
        return set()

    documents = set()
    for match in re.finditer(r"\d(?:[\d.,\s-]*\d){5,}", str(value)):
        document = normalize_document(match.group(0))
        if document:
            documents.add(document)

    return documents


def _document_candidates(row: dict[str, Any]) -> set[str]:
    documents = set()
    for field_name in ("numeros_asunto_json", "numeros_adjuntos_json"):
        for value in _load_json_list(row.get(field_name)):
            document = normalize_document(value)
            if document:
                documents.add(document)

    for field_name in ("asunto", "adjuntos"):
        documents.update(_extract_document_numbers(row.get(field_name)))

    return documents


def _document_matches(expected_document: str, correo_row: dict[str, Any]) -> tuple[bool, str | None]:
    asunto_documents = {
        normalize_document(value)
        for value in _load_json_list(correo_row.get("numeros_asunto_json"))
    }
    adjunto_documents = {
        normalize_document(value)
        for value in _load_json_list(correo_row.get("numeros_adjuntos_json"))
    }

    if expected_document in asunto_documents:
        return True, "asunto"
    if expected_document in adjunto_documents:
        return True, "adjuntos"

    asunto_documents_from_text = _extract_document_numbers(correo_row.get("asunto"))
    adjunto_documents_from_text = _extract_document_numbers(correo_row.get("adjuntos"))
    if expected_document and expected_document in asunto_documents_from_text:
        return True, "asunto"
    if expected_document and expected_document in adjunto_documents_from_text:
        return True, "adjuntos"

    return False, None


def _parse_date(value: Any) -> date | None:
    normalized = normalize_date(value)
    if not normalized:
        return None

    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


def _days_between(start_value: Any, end_value: Any) -> int | None:
    start_date = _parse_date(start_value)
    end_date = _parse_date(end_value)
    if start_date is None or end_date is None:
        return None

    return (end_date - start_date).days


def _fetch_expected_rows(id_archivo_salas: int | None) -> list[dict[str, Any]]:
    base_columns = [
        "id_notificacion_esperada",
        "id_archivo",
        "id_caso",
        "numero_radicado",
        "numero_radicado_normalizado",
        "cedula",
        "cedula_normalizada",
        "tipo_destinatario",
        "correo_o_guia_reportado",
        "correo_normalizado",
        "hoja_trabajo_fecha_audiencia",
        "fecha_envio_reportada",
        "activo",
    ]
    optional_columns = [
        "estado_revision_notificacion",
        "pendiente_revision",
        "id_notificacion_correo_certificado_match",
        "fecha_revision_notificacion",
        "detalle_revision_json",
    ]
    table_columns = db.get_table_columns("jnc.notificacion_esperada")
    columns = [column for column in [*base_columns, *optional_columns] if column in table_columns]

    where = "[activo] = 1"
    params: list[Any] = []
    if id_archivo_salas is not None:
        where += " AND [id_archivo] = ?"
        params.append(id_archivo_salas)

    return db.fetch_rows("jnc.notificacion_esperada", columns, where, params)


def _expected_reference_date(row: dict[str, Any]) -> date | None:
    return _parse_date(
        row.get("hoja_trabajo_fecha_audiencia")
        or row.get("fecha_envio_reportada")
    )


def _correo_date_window(expected_rows: list[dict[str, Any]]) -> tuple[date, date] | None:
    dates = [
        reference_date
        for row in expected_rows
        if (reference_date := _expected_reference_date(row)) is not None
    ]
    if not dates:
        return None

    return (
        min(dates) - timedelta(days=CORREO_FECHA_VENTANA_DIAS),
        max(dates) + timedelta(days=CORREO_FECHA_VENTANA_DIAS),
    )


def _fetch_correo_rows(date_window: tuple[date, date] | None = None) -> list[dict[str, Any]]:
    columns = [
        "id_notificacion_correo",
        "id_archivo",
        "numero_linea_csv",
        "fecha",
        "fecha_2",
        "fecha_3",
        "destinatario_email",
        "destinatario_email_normalizado",
        "correo",
        "asunto",
        "adjuntos",
        "estado_correo",
        "numeros_asunto_json",
        "numeros_adjuntos_json",
    ]
    table_columns = db.get_table_columns("jnc.notificacion_correo_certificado")
    existing_columns = [column for column in columns if column in table_columns]
    where = "1 = 1"
    params: list[Any] = []

    if date_window:
        date_columns = [
            column_name
            for column_name in ("fecha", "fecha_2", "fecha_3")
            if column_name in table_columns
        ]
        if date_columns:
            start_date, end_date = date_window
            where = " OR ".join(
                f"([{column_name}] BETWEEN ? AND ?)"
                for column_name in date_columns
            )
            params = [
                value
                for _ in date_columns
                for value in (start_date, end_date)
            ]

    return db.fetch_rows("jnc.notificacion_correo_certificado", existing_columns, where, params)


def _build_correo_index(correo_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in correo_rows:
        for document in _document_candidates(row):
            index.setdefault(document, []).append(row)
    return index


def _correo_date(row: dict[str, Any]) -> Any:
    return row.get("fecha") or row.get("fecha_2") or row.get("fecha_3")


def _correo_email(row: dict[str, Any]) -> str | None:
    return normalize_email(
        row.get("destinatario_email_normalizado")
        or row.get("destinatario_email")
        or row.get("correo")
    )


def _extract_expected_emails(row: dict[str, Any]) -> list[str]:
    raw_values = [
        row.get("correo_o_guia_reportado"),
        row.get("correo_normalizado"),
    ]
    emails: list[str] = []
    seen = set()

    for raw_value in raw_values:
        if raw_value is None:
            continue

        matches = EMAIL_PATTERN.findall(str(raw_value))
        if not matches and "@" in str(raw_value):
            matches = [str(raw_value)]

        for match in matches:
            normalized = normalize_email(match)
            if normalized and normalized not in seen:
                emails.append(normalized)
                seen.add(normalized)

    return emails


def _email_parts(email: str | None) -> tuple[str, str] | None:
    if not email or "@" not in email:
        return None

    local_part, domain = email.rsplit("@", 1)
    if not local_part or not domain:
        return None

    return local_part, domain


def _levenshtein_distance_limited(left: str, right: str, max_distance: int) -> int:
    if left == right:
        return 0

    if abs(len(left) - len(right)) > max_distance:
        return max_distance + 1

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        row_min = current[0]
        for right_index, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            value = min(
                previous[right_index] + 1,
                current[right_index - 1] + 1,
                previous[right_index - 1] + cost,
            )
            current.append(value)
            row_min = min(row_min, value)

        if row_min > max_distance:
            return max_distance + 1

        previous = current

    return previous[-1]


def _match_expected_email(
    expected_emails: list[str],
    correo_email: str | None,
) -> dict[str, Any]:
    if not correo_email:
        return {
            "cumple_correo": False,
            "tipo_match_correo": None,
            "correo_esperado_match": None,
            "distancia_correo": None,
        }

    if correo_email in expected_emails:
        return {
            "cumple_correo": True,
            "tipo_match_correo": "EXACTO",
            "correo_esperado_match": correo_email,
            "distancia_correo": 0,
        }

    correo_parts = _email_parts(correo_email)
    if correo_parts is None:
        return {
            "cumple_correo": False,
            "tipo_match_correo": None,
            "correo_esperado_match": None,
            "distancia_correo": None,
        }

    correo_local, correo_domain = correo_parts
    best_match = None
    best_distance = MAX_EMAIL_LOCAL_PART_DISTANCE + 1

    for expected_email in expected_emails:
        expected_parts = _email_parts(expected_email)
        if expected_parts is None:
            continue

        expected_local, expected_domain = expected_parts
        if expected_domain != correo_domain:
            continue

        distance = _levenshtein_distance_limited(
            expected_local,
            correo_local,
            MAX_EMAIL_LOCAL_PART_DISTANCE,
        )
        if distance < best_distance:
            best_match = expected_email
            best_distance = distance

    if best_match is not None and 0 < best_distance <= MAX_EMAIL_LOCAL_PART_DISTANCE:
        return {
            "cumple_correo": True,
            "tipo_match_correo": "FUZZY_LOCAL_PART",
            "correo_esperado_match": best_match,
            "distancia_correo": best_distance,
        }

    return {
        "cumple_correo": False,
        "tipo_match_correo": None,
        "correo_esperado_match": expected_emails[0] if expected_emails else None,
        "distancia_correo": best_distance if best_match is not None else None,
    }


def _score_candidate(
    expected_row: dict[str, Any],
    correo_row: dict[str, Any],
) -> dict[str, Any]:
    expected_document = normalize_document(
        expected_row.get("cedula_normalizada") or expected_row.get("cedula")
    )
    expected_emails = _extract_expected_emails(expected_row)
    correo_email = _correo_email(correo_row)
    correo_date = _correo_date(correo_row)
    audience_date = expected_row.get("hoja_trabajo_fecha_audiencia")

    document_ok, document_source = (
        _document_matches(expected_document, correo_row)
        if expected_document
        else (False, None)
    )
    asunto_ok, asunto_score, asunto_topic = _validate_asunto(correo_row.get("asunto"))
    evento_ok, evento_score, evento_type = _validate_evento(correo_row.get("estado_correo"))
    email_match = _match_expected_email(expected_emails, correo_email)
    correo_ok = email_match["cumple_correo"]
    days_after_audience = _days_between(audience_date, correo_date)
    plazo_ok = (
        days_after_audience is not None
        and 0 <= days_after_audience <= PLAZO_DIAS_CALENDARIO
    )

    checks = {
        "cumple_documento": document_ok,
        "cumple_asunto": asunto_ok,
        "cumple_evento": evento_ok,
        "cumple_correo": correo_ok,
        "cumple_plazo": plazo_ok,
    }
    total_score = sum(1 for value in checks.values() if value)

    return {
        **checks,
        "score_total": total_score,
        "score_asunto": asunto_score,
        "score_evento": evento_score,
        "fuente_documento_match": document_source,
        "asunto_tipo_match": asunto_topic,
        "evento_tipo_match": evento_type,
        "correos_esperados": expected_emails,
        "correo_esperado": email_match["correo_esperado_match"],
        "correo_certificado": correo_email,
        "tipo_match_correo": email_match["tipo_match_correo"],
        "distancia_correo": email_match["distancia_correo"],
        "fecha_audiencia": normalize_date(audience_date),
        "fecha_envio_certificado": normalize_date(correo_date),
        "dias_despues_audiencia": days_after_audience,
        "correo_row": correo_row,
    }


def _status_from_candidate(candidate: dict[str, Any] | None, has_document_candidates: bool) -> tuple[str, str]:
    if candidate is None:
        if has_document_candidates:
            return ESTADO_DOCUMENTO_NO_ENCONTRADO, (
                "Se encontraron correos certificados, pero la cedula no aparece en asunto ni adjuntos"
            )
        return ESTADO_NO_CRUZADO, "No se encontro evidencia de correo certificado para la cedula"

    if all(
        candidate.get(field_name)
        for field_name in (
            "cumple_documento",
            "cumple_asunto",
            "cumple_evento",
            "cumple_correo",
            "cumple_plazo",
        )
    ):
        return ESTADO_CUMPLE, "Notificacion validada contra correo certificado"

    if not candidate.get("cumple_asunto"):
        return ESTADO_ASUNTO_NO_VALIDO, (
            "El asunto no corresponde a comunicacion de dictamen o calificacion"
        )
    if not candidate.get("cumple_evento"):
        return ESTADO_EVENTO_NO_VALIDO, (
            "El evento no evidencia acuse, lectura o apertura de la notificacion"
        )
    if not candidate.get("cumple_correo"):
        return ESTADO_CORREO_NO_COINCIDE, (
            "El correo certificado no coincide con el correo reportado en la notificacion esperada"
        )
    if not candidate.get("cumple_plazo"):
        return ESTADO_FUERA_DE_PLAZO, (
            "La fecha de envio certificado supera el plazo de 2 dias calendario desde la audiencia"
        )

    return ESTADO_REQUIERE_REVISION, "La evidencia encontrada requiere revision manual"


def _best_candidate(
    expected_row: dict[str, Any],
    correo_index: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, bool]:
    expected_document = normalize_document(
        expected_row.get("cedula_normalizada") or expected_row.get("cedula")
    )
    if not expected_document:
        return None, False

    candidates = correo_index.get(expected_document, [])
    if not candidates:
        return None, False

    scored_candidates = [_score_candidate(expected_row, row) for row in candidates]
    scored_candidates.sort(
        key=lambda item: (
            item["cumple_documento"],
            item["cumple_asunto"],
            item["cumple_evento"],
            item["cumple_correo"],
            item["cumple_plazo"],
            item["score_total"],
            item["score_evento"],
            item["score_asunto"],
        ),
        reverse=True,
    )
    return scored_candidates[0], True


def _build_revision_rows(
    expected_row: dict[str, Any],
    candidate: dict[str, Any] | None,
    has_document_candidates: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    status, pending_detail = _status_from_candidate(candidate, has_document_candidates)
    correo_row = candidate.get("correo_row") if candidate else None
    revision_date = utc_now_iso()

    detail = {
        "estado_revision_notificacion": status,
        "pendiente_revision": pending_detail,
        "numero_radicado_normalizado": expected_row.get("numero_radicado_normalizado"),
        "cedula_normalizada": expected_row.get("cedula_normalizada"),
        "tipo_destinatario": expected_row.get("tipo_destinatario"),
        "id_notificacion_correo_certificado_match": correo_row.get("id_notificacion_correo")
        if correo_row
        else None,
        "id_archivo_correo_certificado_match": correo_row.get("id_archivo")
        if correo_row
        else None,
        "numero_linea_csv_match": correo_row.get("numero_linea_csv") if correo_row else None,
        "checks": {
            key: candidate.get(key) if candidate else False
            for key in (
                "cumple_documento",
                "cumple_asunto",
                "cumple_evento",
                "cumple_correo",
                "cumple_plazo",
            )
        },
        "score_asunto": candidate.get("score_asunto") if candidate else None,
        "score_evento": candidate.get("score_evento") if candidate else None,
        "fuente_documento_match": candidate.get("fuente_documento_match") if candidate else None,
        "asunto_tipo_match": candidate.get("asunto_tipo_match") if candidate else None,
        "evento_tipo_match": candidate.get("evento_tipo_match") if candidate else None,
        "correos_esperados": candidate.get("correos_esperados") if candidate else [],
        "correo_esperado": candidate.get("correo_esperado") if candidate else None,
        "correo_certificado": candidate.get("correo_certificado") if candidate else None,
        "tipo_match_correo": candidate.get("tipo_match_correo") if candidate else None,
        "distancia_correo": candidate.get("distancia_correo") if candidate else None,
        "fecha_audiencia": candidate.get("fecha_audiencia") if candidate else None,
        "fecha_envio_certificado": candidate.get("fecha_envio_certificado") if candidate else None,
        "dias_despues_audiencia": candidate.get("dias_despues_audiencia") if candidate else None,
    }
    detail_json = json_dumps_safe(detail)

    update_row = {
        "id_notificacion_esperada": expected_row["id_notificacion_esperada"],
        "estado_revision_notificacion": status,
        "pendiente_revision": pending_detail,
        "id_notificacion_correo_certificado_match": correo_row.get("id_notificacion_correo")
        if correo_row
        else None,
        "fecha_revision_notificacion": revision_date,
        "detalle_revision_json": detail_json,
        "fecha_actualizacion": revision_date,
    }
    cruce_row = {
        "id_notificacion_esperada": expected_row["id_notificacion_esperada"],
        "id_caso": expected_row.get("id_caso"),
        "id_archivo": expected_row.get("id_archivo"),
        "numero_radicado": expected_row.get("numero_radicado"),
        "numero_radicado_normalizado": expected_row.get("numero_radicado_normalizado"),
        "cedula": expected_row.get("cedula"),
        "cedula_normalizada": expected_row.get("cedula_normalizada"),
        "tipo_destinatario": expected_row.get("tipo_destinatario"),
        "id_notificacion_correo_certificado_match": correo_row.get("id_notificacion_correo")
        if correo_row
        else None,
        "id_archivo_correo_certificado_match": correo_row.get("id_archivo")
        if correo_row
        else None,
        "numero_linea_csv_match": correo_row.get("numero_linea_csv") if correo_row else None,
        "estado_revision_notificacion": status,
        "descripcion_revision": pending_detail,
        "cumple_documento": 1 if candidate and candidate.get("cumple_documento") else 0,
        "cumple_asunto": 1 if candidate and candidate.get("cumple_asunto") else 0,
        "cumple_evento": 1 if candidate and candidate.get("cumple_evento") else 0,
        "cumple_correo": 1 if candidate and candidate.get("cumple_correo") else 0,
        "cumple_plazo": 1 if candidate and candidate.get("cumple_plazo") else 0,
        "score_total": candidate.get("score_total") if candidate else None,
        "score_asunto": candidate.get("score_asunto") if candidate else None,
        "score_evento": candidate.get("score_evento") if candidate else None,
        "fuente_documento_match": candidate.get("fuente_documento_match") if candidate else None,
        "asunto_tipo_match": candidate.get("asunto_tipo_match") if candidate else None,
        "evento_tipo_match": candidate.get("evento_tipo_match") if candidate else None,
        "tipo_match_correo": candidate.get("tipo_match_correo") if candidate else None,
        "distancia_correo": candidate.get("distancia_correo") if candidate else None,
        "correo_esperado": candidate.get("correo_esperado") if candidate else None,
        "correo_certificado": candidate.get("correo_certificado") if candidate else None,
        "fecha_audiencia": candidate.get("fecha_audiencia") if candidate else None,
        "fecha_envio_certificado": candidate.get("fecha_envio_certificado") if candidate else None,
        "dias_despues_audiencia": candidate.get("dias_despues_audiencia") if candidate else None,
        "fecha_revision": revision_date,
        "version_regla_cruce": CRUCE_VERSION,
        "detalle_revision_json": detail_json,
        "activo": 1,
        "fecha_creacion": revision_date,
        "fecha_actualizacion": revision_date,
    }

    return update_row, cruce_row


def _radicado_key(row: dict[str, Any]) -> str | None:
    radicado = (
        row.get("numero_radicado_normalizado")
        or row.get("numero_radicado")
    )
    if not radicado and row.get("id_caso"):
        radicado = f"id_caso:{row.get('id_caso')}"

    return str(radicado) if radicado else None


def _campo_original_key(row: dict[str, Any]) -> str:
    return str(row.get("tipo_destinatario") or "SIN_TIPO_DESTINATARIO")


def _radicado_field_statuses(
    expected_rows: list[dict[str, Any]],
    status_by_expected_id: dict[Any, str],
) -> dict[str, dict[str, list[str]]]:
    statuses: dict[str, dict[str, list[str]]] = {}

    for row in expected_rows:
        radicado = _radicado_key(row)
        if not radicado:
            continue

        field_key = _campo_original_key(row)
        status = status_by_expected_id.get(
            row.get("id_notificacion_esperada"),
            row.get("estado_revision_notificacion") or "SIN_REVISION",
        )
        statuses.setdefault(radicado, {}).setdefault(field_key, []).append(status)

    return statuses


def _radicado_validado_por_campos(field_statuses: dict[str, list[str]]) -> bool:
    return bool(field_statuses) and all(
        any(status == ESTADO_CUMPLE for status in statuses)
        for statuses in field_statuses.values()
    )


def _radicado_extemporaneo_por_campos(field_statuses: dict[str, list[str]]) -> bool:
    if not field_statuses or _radicado_validado_por_campos(field_statuses):
        return False

    return all(
        any(status in {ESTADO_CUMPLE, ESTADO_FUERA_DE_PLAZO} for status in statuses)
        for statuses in field_statuses.values()
    ) and any(
        not any(status == ESTADO_CUMPLE for status in statuses)
        and any(status == ESTADO_FUERA_DE_PLAZO for status in statuses)
        for statuses in field_statuses.values()
    )


def recalcular_cruce_notificaciones(
    id_archivo_salas: int | None = None,
    solo_pendientes: bool = True,
) -> dict[str, Any]:
    all_expected_rows = _fetch_expected_rows(id_archivo_salas)
    expected_rows = all_expected_rows
    if solo_pendientes:
        expected_rows = [
            row
            for row in expected_rows
            if row.get("estado_revision_notificacion") != ESTADO_CUMPLE
        ]

    date_window = _correo_date_window(expected_rows)
    correo_rows = _fetch_correo_rows(date_window)
    correo_index = _build_correo_index(correo_rows)

    updates = []
    cruce_rows = []
    status_by_expected_id = {
        row.get("id_notificacion_esperada"): (
            row.get("estado_revision_notificacion") or "SIN_REVISION"
        )
        for row in all_expected_rows
    }
    summary = {
        "notificaciones_evaluadas": len(expected_rows),
        "notificaciones_actualizadas": 0,
        "correos_evaluados": len(correo_rows),
        "ventana_correo_desde": date_window[0].isoformat() if date_window else None,
        "ventana_correo_hasta": date_window[1].isoformat() if date_window else None,
        "cumplen": 0,
        "pendientes": 0,
        "sin_correo_certificado": 0,
        "cruces_eliminados": 0,
        "cruces_insertados": 0,
        "porcentaje_notificaciones_validadas": 0.0,
        "radicados_evaluados": 0,
        "radicados_validados": 0,
        "radicados_validados_extemporaneos": 0,
        "radicados_pendientes": 0,
        "porcentaje_radicados_validados": 0.0,
        "porcentaje_radicados_validados_extemporaneos": 0.0,
        "resumen_validacion_radicado": {},
    }

    for expected_row in expected_rows:
        candidate, has_document_candidates = _best_candidate(expected_row, correo_index)
        update_row, cruce_row = _build_revision_rows(
            expected_row,
            candidate,
            has_document_candidates,
        )
        updates.append(update_row)
        cruce_rows.append(cruce_row)

        status = update_row["estado_revision_notificacion"]
        status_by_expected_id[expected_row.get("id_notificacion_esperada")] = status

        if status == ESTADO_CUMPLE:
            summary["cumplen"] += 1
        else:
            summary["pendientes"] += 1
        if status == ESTADO_NO_CRUZADO:
            summary["sin_correo_certificado"] += 1

    if summary["notificaciones_evaluadas"]:
        summary["porcentaje_notificaciones_validadas"] = round(
            (summary["cumplen"] / summary["notificaciones_evaluadas"]) * 100,
            2,
        )

    radicado_statuses = _radicado_field_statuses(all_expected_rows, status_by_expected_id)
    summary["radicados_evaluados"] = len(radicado_statuses)
    radicados_validados = set()
    radicados_extemporaneos = set()

    for radicado, field_statuses in radicado_statuses.items():
        if _radicado_validado_por_campos(field_statuses):
            radicados_validados.add(radicado)
        elif _radicado_extemporaneo_por_campos(field_statuses):
            radicados_extemporaneos.add(radicado)

    summary["radicados_validados"] = len(radicados_validados)
    summary["radicados_validados_extemporaneos"] = len(radicados_extemporaneos)
    summary["radicados_pendientes"] = (
        summary["radicados_evaluados"]
        - summary["radicados_validados"]
        - summary["radicados_validados_extemporaneos"]
    )
    if summary["radicados_evaluados"]:
        summary["porcentaje_radicados_validados"] = round(
            (summary["radicados_validados"] / summary["radicados_evaluados"]) * 100,
            2,
        )
        summary["porcentaje_radicados_validados_extemporaneos"] = round(
            (
                summary["radicados_validados_extemporaneos"]
                / summary["radicados_evaluados"]
            )
            * 100,
            2,
        )

    if cruce_rows:
        if not solo_pendientes and id_archivo_salas is not None:
            summary["cruces_eliminados"] = db.delete_by_archivo(
                "jnc.resultado_cruce_notificacion",
                id_archivo_salas,
            )
        elif not solo_pendientes:
            summary["cruces_eliminados"] = db.delete_all(
                "jnc.resultado_cruce_notificacion",
            )
        else:
            summary["cruces_eliminados"] = db.delete_by_column_values(
                "jnc.resultado_cruce_notificacion",
                "id_notificacion_esperada",
                [row.get("id_notificacion_esperada") for row in cruce_rows],
            )

        summary["cruces_insertados"] = db.insert_many(
            "jnc.resultado_cruce_notificacion",
            cruce_rows,
        )

    summary["notificaciones_actualizadas"] = db.execute_many_updates(
        "jnc.notificacion_esperada",
        "id_notificacion_esperada",
        updates,
    )
    summary["resumen_validacion_radicado"] = refrescar_resumen_validacion_radicado()
    return summary
