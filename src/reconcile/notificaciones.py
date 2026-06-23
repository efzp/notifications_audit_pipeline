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
    normalize_db_string,
    normalize_document,
    normalize_email,
)


ESTADO_CUMPLE = "CUMPLE"
ESTADO_NO_CRUZADO = "NO_CRUZADO"
ESTADO_DOCUMENTO_NO_ENCONTRADO = "DOCUMENTO_NO_ENCONTRADO"
ESTADO_ASUNTO_NO_VALIDO = "ASUNTO_NO_VALIDO"
ESTADO_EVENTO_NO_VALIDO = "EVENTO_NO_VALIDO"
ESTADO_CORREO_NO_COINCIDE = "CORREO_NO_COINCIDE"
ESTADO_ARL_NO_COINCIDE = "ARL_NO_COINCIDE"
ESTADO_FUERA_DE_PLAZO = "FUERA_DE_PLAZO"
ESTADO_GUIA_NO_COINCIDE_CEDULA = "GUIA_NO_COINCIDE_CEDULA"
ESTADO_GUIA_NO_COINCIDE = "GUIA_NO_COINCIDE"
ESTADO_REQUIERE_REVISION = "REQUIERE_REVISION_MANUAL"

PLAZO_DIAS_CALENDARIO = 2
GUIA_FECHA_VENTANA_DIAS = 30
ARL_FECHA_VENTANA_DIAS = 30
FUZZY_THRESHOLD = 0.82
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
MAX_EMAIL_LOCAL_PART_DISTANCE = 2
CRUCE_VERSION = "1.0"
CORREO_FECHA_VENTANA_DIAS = 7
GUIA_MATCH_DIGITS = 9
GUIA_ENVIA_MATCH_THRESHOLD = 0.8
FUENTE_FULL = "FULL"
FUENTE_CORREO = "CORREO_CERTIFICADO"
FUENTE_GUIA = "GUIA_CORREO_FISICO"
FUENTE_ARL = "ARL_RADICADO_PDF"
FUENTES_CRUCE = {FUENTE_FULL, FUENTE_CORREO, FUENTE_GUIA, FUENTE_ARL}
STATUS_RANK = {
    ESTADO_CUMPLE: 50,
    ESTADO_FUERA_DE_PLAZO: 40,
    ESTADO_REQUIERE_REVISION: 30,
    ESTADO_CORREO_NO_COINCIDE: 20,
    ESTADO_ARL_NO_COINCIDE: 20,
    ESTADO_GUIA_NO_COINCIDE_CEDULA: 20,
    ESTADO_ASUNTO_NO_VALIDO: 20,
    ESTADO_EVENTO_NO_VALIDO: 20,
    ESTADO_DOCUMENTO_NO_ENCONTRADO: 10,
    ESTADO_GUIA_NO_COINCIDE: 10,
    ESTADO_NO_CRUZADO: 10,
    "SIN_REVISION": 0,
}


def _normalize_fuente_cruce(value: Any) -> str:
    if value in (None, ""):
        return FUENTE_FULL

    normalized = str(value).strip().upper()
    aliases = {
        "FULL": FUENTE_FULL,
        "TODAS": FUENTE_FULL,
        "TODO": FUENTE_FULL,
        "CORREO": FUENTE_CORREO,
        "CORREO_CERTIFICADO": FUENTE_CORREO,
        "GUIA": FUENTE_GUIA,
        "GUIAS": FUENTE_GUIA,
        "GUIA_CORREO_FISICO": FUENTE_GUIA,
        "GUIAS_CORREO_FISICO": FUENTE_GUIA,
        "ARL": FUENTE_ARL,
        "ARLS": FUENTE_ARL,
        "ARL_RADICADO": FUENTE_ARL,
        "ARL_RADICADO_PDF": FUENTE_ARL,
    }
    fuente = aliases.get(normalized, normalized)
    if fuente not in FUENTES_CRUCE:
        raise ValueError(
            "fuente_cruce debe ser una de: "
            + ", ".join(sorted(FUENTES_CRUCE))
        )
    return fuente


def _status_rank(status: Any) -> int:
    return STATUS_RANK.get(str(status or "SIN_REVISION"), 0)


def _should_apply_source_update(previous_status: Any, new_status: Any) -> bool:
    return _status_rank(new_status) > _status_rank(previous_status)


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


def _digits_only(value: Any) -> str:
    if value is None:
        return ""

    return re.sub(r"\D+", "", str(value))


def _right_digits(value: Any, length: int = GUIA_MATCH_DIGITS) -> str | None:
    digits = _digits_only(value)
    if len(digits) < length:
        return None

    return digits[-length:]


def _looks_like_envia(value: Any) -> bool:
    tokens = _tokens(value)
    if not tokens:
        return False

    expected_words = ("envia", "envio", "enviado", "enviar")
    return any(
        SequenceMatcher(None, token, expected).ratio() >= GUIA_ENVIA_MATCH_THRESHOLD
        for token in tokens
        for expected in expected_words
    )


def _guia_lookup_method(expected_row: dict[str, Any]) -> str | None:
    if _right_digits(expected_row.get("correo_o_guia_reportado")):
        return "GUIA_ULTIMOS_9_DIGITOS"
    if _looks_like_envia(expected_row.get("correo_o_guia_reportado")):
        return "GUIA_CEDULA_FECHA_ENVIA"
    return None


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


def _fetch_expected_rows(
    id_archivo_salas: int | None,
    batch_size: int | None = None,
    after_id_notificacion_esperada: int | None = None,
    solo_pendientes_filter: bool = False,
    fecha_referencia_desde: date | None = None,
    fecha_referencia_hasta: date | None = None,
    cedulas_normalizadas: list[str] | None = None,
) -> list[dict[str, Any]]:
    base_columns = [
        "id_notificacion_esperada",
        "id_archivo",
        "id_caso",
        "id_calificacion_sistema_caso",
        "numero_radicado",
        "numero_radicado_normalizado",
        "cedula",
        "cedula_normalizada",
        "tipo_destinatario",
        "correo_o_guia_reportado",
        "correo_normalizado",
        "fuente_correo_reportado",
        "id_calificacion_sistema_envio_fallback",
        "hash_negocio_notificacion",
        "hoja_trabajo_fecha_audiencia",
        "fecha_envio_reportada",
        "origen_tabla",
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
    if after_id_notificacion_esperada is not None:
        where += " AND [id_notificacion_esperada] > ?"
        params.append(after_id_notificacion_esperada)
    if solo_pendientes_filter and "estado_revision_notificacion" in table_columns:
        where += " AND COALESCE([estado_revision_notificacion], 'SIN_REVISION') <> ?"
        params.append(ESTADO_CUMPLE)
    if fecha_referencia_desde is not None or fecha_referencia_hasta is not None:
        reference_columns = [
            column_name
            for column_name in ("hoja_trabajo_fecha_audiencia", "fecha_envio_reportada")
            if column_name in table_columns
        ]
        if reference_columns:
            reference_expr = "COALESCE(" + ", ".join(
                f"[{column_name}]" for column_name in reference_columns
            ) + ")"
            if fecha_referencia_desde is not None:
                where += f" AND {reference_expr} >= ?"
                params.append(fecha_referencia_desde)
            if fecha_referencia_hasta is not None:
                where += f" AND {reference_expr} <= ?"
                params.append(fecha_referencia_hasta)
    if cedulas_normalizadas:
        cedulas = sorted({cedula for cedula in cedulas_normalizadas if cedula})
        if cedulas:
            placeholders = ", ".join("?" for _ in cedulas)
            where += f" AND [cedula_normalizada] IN ({placeholders})"
            params.extend(cedulas)

    if batch_size is not None:
        where += " ORDER BY [id_notificacion_esperada] OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY"
        params.append(batch_size)
    elif after_id_notificacion_esperada is not None:
        where += " ORDER BY [id_notificacion_esperada]"

    return db.fetch_rows("jnc.notificacion_esperada", columns, where, params)


def _fetch_arl_cedulas_by_archivo(id_archivo: int) -> list[str]:
    try:
        table_columns = db.get_table_columns("jnc.notificacion_arl_radicado")
    except ValueError:
        return []

    columns = [
        column
        for column in ("cedula_normalizada", "cedula_detectada")
        if column in table_columns
    ]
    if not columns:
        return []

    rows = db.fetch_rows(
        "jnc.notificacion_arl_radicado",
        columns,
        "[activo] = 1 AND [id_archivo] = ?",
        [id_archivo],
    )
    cedulas = {
        normalize_document(row.get("cedula_normalizada") or row.get("cedula_detectada"))
        for row in rows
    }
    return sorted(cedula for cedula in cedulas if cedula)


def _fetch_latest_calificacion_sistema_audiencia_date() -> date | None:
    value = db.fetch_scalar_sql(
        (
            "SELECT MAX(fecha_audiencia) "
            "FROM jnc.calificacion_sistema_caso "
            "WHERE activo = 1 AND fecha_audiencia IS NOT NULL"
        )
    )
    return _parse_date(value)


def _enrich_expected_arl_fields(expected_rows: list[dict[str, Any]]) -> None:
    case_ids = sorted(
        {
            int(row["id_calificacion_sistema_caso"])
            for row in expected_rows
            if row.get("id_calificacion_sistema_caso") is not None
        }
    )
    if not case_ids:
        return

    try:
        table_columns = db.get_table_columns("jnc.calificacion_sistema_caso")
    except ValueError:
        return

    columns = [
        column
        for column in (
            "id_calificacion_sistema_caso",
            "arl",
            "arl_normalizado",
        )
        if column in table_columns
    ]
    if "id_calificacion_sistema_caso" not in columns:
        return

    arl_by_case_id: dict[int, dict[str, Any]] = {}
    chunk_size = 900
    for start in range(0, len(case_ids), chunk_size):
        chunk = case_ids[start:start + chunk_size]
        placeholders = ", ".join("?" for _ in chunk)
        rows = db.fetch_rows(
            "jnc.calificacion_sistema_caso",
            columns,
            (
                "[activo] = 1 "
                f"AND [id_calificacion_sistema_caso] IN ({placeholders})"
            ),
            chunk,
        )
        for row in rows:
            arl_by_case_id[int(row["id_calificacion_sistema_caso"])] = row

    for row in expected_rows:
        case_id = row.get("id_calificacion_sistema_caso")
        if case_id is None:
            continue
        arl_row = arl_by_case_id.get(int(case_id))
        if not arl_row:
            continue
        row["arl_esperada"] = arl_row.get("arl")
        row["arl_esperada_normalizada"] = (
            arl_row.get("arl_normalizado")
            or normalize_db_string(arl_row.get("arl"))
        )


def _filter_raw_by_latest_audiencia_date(
    expected_rows: list[dict[str, Any]],
    latest_audience_date: date | None,
) -> tuple[list[dict[str, Any]], int]:
    if latest_audience_date is None:
        return expected_rows, 0

    filtered_rows = []
    skipped = 0
    for row in expected_rows:
        if row.get("origen_tabla") != "RAW_INPUT_SALAS":
            filtered_rows.append(row)
            continue

        row_date = _parse_date(row.get("hoja_trabajo_fecha_audiencia"))
        if row_date == latest_audience_date:
            filtered_rows.append(row)
        else:
            skipped += 1

    return filtered_rows, skipped


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


def _guia_date_window(expected_rows: list[dict[str, Any]]) -> tuple[date, date] | None:
    dates = [
        reference_date
        for row in expected_rows
        if (reference_date := _expected_reference_date(row)) is not None
    ]
    if not dates:
        return None

    return (
        min(dates) - timedelta(days=GUIA_FECHA_VENTANA_DIAS),
        max(dates) + timedelta(days=GUIA_FECHA_VENTANA_DIAS),
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


def _fetch_guia_rows(date_window: tuple[date, date] | None = None) -> list[dict[str, Any]]:
    columns = [
        "id_guia_correo_fisico",
        "id_archivo",
        "hoja_origen",
        "guia",
        "estado",
        "fec_entrega",
        "fecha_entrega",
        "ced_destinatario",
        "ced_destinatario_normalizada",
        "nombre_destinatario",
        "numero_documento",
        "cartaporte",
        "des_estadog",
    ]
    try:
        table_columns = db.get_table_columns("jnc.guia_correo_fisico")
    except ValueError:
        return []

    existing_columns = [column for column in columns if column in table_columns]
    if not existing_columns:
        return []

    where = "1 = 1"
    params: list[Any] = []
    if date_window:
        date_columns = [
            column_name
            for column_name in ("fec_entrega", "fecha_entrega")
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

    return db.fetch_rows("jnc.guia_correo_fisico", existing_columns, where, params)


def _fetch_arl_radicado_rows(
    date_window: tuple[date, date] | None = None,
    id_archivo_evidencia: int | None = None,
) -> list[dict[str, Any]]:
    columns = [
        "id_notificacion_arl_radicado",
        "id_archivo",
        "arl_detectada",
        "arl_normalizada",
        "cedula_detectada",
        "cedula_normalizada",
        "fecha_recibo_comunicacion",
        "fecha_correo",
        "metodo_deteccion_arl",
        "metodo_deteccion_cedula",
        "metodo_deteccion_fecha",
        "confianza_arl",
        "confianza_cedula",
        "confianza_fecha",
        "nombre_archivo",
        "hash_arl_radicado",
    ]
    try:
        table_columns = db.get_table_columns("jnc.notificacion_arl_radicado")
    except ValueError:
        return []

    existing_columns = [column for column in columns if column in table_columns]
    if not existing_columns:
        return []

    where = "[activo] = 1"
    params: list[Any] = []
    if id_archivo_evidencia is not None:
        where += " AND [id_archivo] = ?"
        params.append(id_archivo_evidencia)
    if date_window:
        date_columns = [
            column_name
            for column_name in ("fecha_recibo_comunicacion", "fecha_correo")
            if column_name in table_columns
        ]
        if date_columns:
            start_date, end_date = date_window
            where += " AND (" + " OR ".join(
                f"([{column_name}] BETWEEN ? AND ?)"
                for column_name in date_columns
            ) + ")"
            params = [
                value
                for _ in date_columns
                for value in (start_date, end_date)
            ]

    return db.fetch_rows("jnc.notificacion_arl_radicado", existing_columns, where, params)


def _build_correo_index(correo_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in correo_rows:
        for document in _document_candidates(row):
            index.setdefault(document, []).append(row)
    return index


def _build_arl_document_index(arl_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in arl_rows:
        document = normalize_document(
            row.get("cedula_normalizada") or row.get("cedula_detectada")
        )
        if document:
            index.setdefault(document, []).append(row)
    return index


def _guia_estado_entregado(row: dict[str, Any]) -> bool:
    estado = _normalize_match_text(row.get("estado") or row.get("des_estadog"))
    return "entregad" in estado


def _guia_destinatario_es_devolucion(row: dict[str, Any]) -> bool:
    nombre_destinatario = _normalize_match_text(row.get("nombre_destinatario"))
    nombre_compacto = re.sub(r"[^a-z0-9]+", "", nombre_destinatario)
    return "jnci" in nombre_compacto


def _guia_number(row: dict[str, Any]) -> str | None:
    for field_name in ("guia", "cartaporte", "numero_guia", "correo_o_guia"):
        guide_key = _right_digits(row.get(field_name))
        if guide_key:
            return guide_key

    return None


def _guia_delivery_date(row: dict[str, Any]) -> date | None:
    return _parse_date(row.get("fec_entrega") or row.get("fecha_entrega"))


def _guia_document(row: dict[str, Any]) -> str:
    for field_name in (
        "numero_documento",
        "ced_destinatario_normalizada",
        "ced_destinatario",
    ):
        document = normalize_document(row.get(field_name))
        if document and document != "0":
            return document

    return ""


def _build_guia_index(guia_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in guia_rows:
        if not _guia_estado_entregado(row):
            continue
        if _guia_destinatario_es_devolucion(row):
            continue

        guide_key = _guia_number(row)
        if guide_key:
            index.setdefault(guide_key, []).append(row)

    return index


def _build_guia_document_index(guia_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in guia_rows:
        if not _guia_estado_entregado(row):
            continue
        if _guia_destinatario_es_devolucion(row):
            continue

        document = _guia_document(row)
        if document:
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


def _score_guia_candidate(
    expected_row: dict[str, Any],
    guia_row: dict[str, Any],
    metodo_busqueda: str = "GUIA_ULTIMOS_9_DIGITOS",
) -> dict[str, Any]:
    expected_document = normalize_document(
        expected_row.get("cedula_normalizada") or expected_row.get("cedula")
    )
    expected_guide_key = _right_digits(expected_row.get("correo_o_guia_reportado"))
    guia_key = _guia_number(guia_row)
    guia_document = _guia_document(guia_row)
    reference_date = _expected_reference_date(expected_row)
    delivery_date = _guia_delivery_date(guia_row)
    days_after_reference = (
        (delivery_date - reference_date).days
        if reference_date is not None and delivery_date is not None
        else None
    )
    document_ok = bool(expected_document and expected_document == guia_document)
    date_in_window = (
        days_after_reference is not None
        and 0 <= days_after_reference <= GUIA_FECHA_VENTANA_DIAS
    )
    plazo_ok = (
        days_after_reference is not None
        and 0 <= days_after_reference <= PLAZO_DIAS_CALENDARIO
    )
    fuera_de_plazo = (
        days_after_reference is not None
        and PLAZO_DIAS_CALENDARIO < days_after_reference <= GUIA_FECHA_VENTANA_DIAS
    )
    estado_entregado = _guia_estado_entregado(guia_row)
    if metodo_busqueda == "GUIA_ULTIMOS_9_DIGITOS":
        guia_ok = bool(expected_guide_key and expected_guide_key == guia_key)
    elif metodo_busqueda == "GUIA_CEDULA_FALLBACK":
        guia_ok = bool(document_ok and estado_entregado)
    else:
        guia_ok = bool(document_ok and date_in_window and estado_entregado)
    checks = {
        "cumple_guia": guia_ok,
        "cumple_documento": document_ok,
        "cumple_evento": estado_entregado,
        "cumple_correo": guia_ok,
        "cumple_plazo": plazo_ok,
        "guia_fecha_en_ventana": date_in_window,
        "guia_fuera_de_plazo": fuera_de_plazo,
    }

    return {
        **checks,
        "score_total": sum(1 for value in checks.values() if value),
        "guia_esperada": expected_guide_key,
        "guia_fisica": guia_key,
        "metodo_busqueda": metodo_busqueda,
        "cedula_esperada": expected_document,
        "cedula_guia": guia_document,
        "estado_guia": guia_row.get("estado") or guia_row.get("des_estadog"),
        "fecha_referencia": normalize_date(reference_date),
        "fecha_entrega_guia": normalize_date(delivery_date),
        "dias_despues_referencia": days_after_reference,
        "id_archivo_guia": guia_row.get("id_archivo"),
        "id_guia_correo_fisico": guia_row.get("id_guia_correo_fisico"),
        "hoja_origen_guia": guia_row.get("hoja_origen"),
        "guia_row": guia_row,
    }


def _arl_evidence_date(row: dict[str, Any]) -> date | None:
    return _parse_date(row.get("fecha_recibo_comunicacion") or row.get("fecha_correo"))


def _arl_marker(value: Any) -> str | None:
    text = _normalize_match_text(value).upper()
    if not text:
        return None
    if "BOLIVAR" in text or "BOLIV" in text or "SEGUROS B" in text:
        return "BOLIVAR"
    if "COLMENA" in text or "COLMEN" in text or "COLM" in text:
        return "COLMENA"
    return None


def _arl_names_compatible(expected_value: Any, evidence_value: Any) -> bool:
    expected_marker = _arl_marker(expected_value)
    evidence_marker = _arl_marker(evidence_value)
    return bool(expected_marker and evidence_marker and expected_marker == evidence_marker)


def _score_arl_candidate(
    expected_row: dict[str, Any],
    arl_row: dict[str, Any],
) -> dict[str, Any]:
    expected_document = normalize_document(
        expected_row.get("cedula_normalizada") or expected_row.get("cedula")
    )
    arl_document = normalize_document(
        arl_row.get("cedula_normalizada") or arl_row.get("cedula_detectada")
    )
    reference_date = _expected_reference_date(expected_row)
    evidence_date = _arl_evidence_date(arl_row)
    days_after_reference = (
        (evidence_date - reference_date).days
        if reference_date is not None and evidence_date is not None
        else None
    )
    expected_arl = (
        expected_row.get("arl_esperada_normalizada")
        or expected_row.get("arl_esperada")
    )
    evidence_arl = arl_row.get("arl_normalizada") or arl_row.get("arl_detectada")
    document_ok = bool(expected_document and expected_document == arl_document)
    arl_ok = _arl_names_compatible(expected_arl, evidence_arl)
    date_in_window = (
        days_after_reference is not None
        and 0 <= days_after_reference <= ARL_FECHA_VENTANA_DIAS
    )
    plazo_ok = (
        days_after_reference is not None
        and 0 <= days_after_reference <= PLAZO_DIAS_CALENDARIO
    )
    fuera_de_plazo = (
        days_after_reference is not None
        and PLAZO_DIAS_CALENDARIO < days_after_reference <= ARL_FECHA_VENTANA_DIAS
    )
    checks = {
        "cumple_documento": document_ok,
        "cumple_evento": bool(evidence_date),
        "cumple_correo": arl_ok,
        "cumple_plazo": plazo_ok,
        "arl_fecha_en_ventana": date_in_window,
        "arl_fuera_de_plazo": fuera_de_plazo,
    }

    return {
        **checks,
        "score_total": sum(1 for value in checks.values() if value),
        "metodo_busqueda": "ARL_CEDULA_ENTIDAD_FECHA",
        "cedula_esperada": expected_document,
        "cedula_arl": arl_document,
        "arl_esperada": expected_row.get("arl_esperada"),
        "arl_esperada_normalizada": expected_row.get("arl_esperada_normalizada"),
        "arl_detectada": arl_row.get("arl_detectada"),
        "arl_normalizada": arl_row.get("arl_normalizada"),
        "fecha_referencia": normalize_date(reference_date),
        "fecha_recibo_comunicacion": normalize_date(evidence_date),
        "dias_despues_referencia": days_after_reference,
        "id_archivo_arl": arl_row.get("id_archivo"),
        "id_notificacion_arl_radicado": arl_row.get("id_notificacion_arl_radicado"),
        "metodo_deteccion_arl": arl_row.get("metodo_deteccion_arl"),
        "metodo_deteccion_cedula": arl_row.get("metodo_deteccion_cedula"),
        "metodo_deteccion_fecha": arl_row.get("metodo_deteccion_fecha"),
        "nombre_archivo_arl": arl_row.get("nombre_archivo"),
        "hash_arl_radicado": arl_row.get("hash_arl_radicado"),
        "arl_row": arl_row,
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


def _status_from_guia_candidate(
    guia_candidate: dict[str, Any] | None,
    has_guia_lookup: bool,
) -> tuple[str | None, str | None]:
    if not has_guia_lookup:
        return None, None

    if guia_candidate is None:
        return ESTADO_GUIA_NO_COINCIDE, (
            "No se encontro guia entregada que coincida por numero de guia o por cedula "
            "y fecha de entrega dentro de la ventana posterior"
        )

    if not guia_candidate.get("guia_fecha_en_ventana"):
        return ESTADO_GUIA_NO_COINCIDE, (
            "La guia existe, pero la fecha de entrega no cae dentro de la ventana posterior"
        )

    if not guia_candidate.get("cumple_documento"):
        return ESTADO_GUIA_NO_COINCIDE_CEDULA, (
            "La guia y fecha coinciden, pero la cedula digitalizada no coincide"
        )

    if guia_candidate.get("cumple_plazo"):
        if guia_candidate.get("metodo_busqueda") == "GUIA_CEDULA_FECHA_ENVIA":
            return ESTADO_CUMPLE, (
                "Notificacion validada contra guia de correo fisico por cedula y fecha"
            )
        if guia_candidate.get("metodo_busqueda") == "GUIA_CEDULA_FALLBACK":
            return ESTADO_CUMPLE, (
                "Notificacion validada contra guia de correo fisico por cedula"
            )
        return ESTADO_CUMPLE, "Notificacion validada contra guia de correo fisico"

    if guia_candidate.get("guia_fuera_de_plazo"):
        return ESTADO_FUERA_DE_PLAZO, (
            "La guia fue entregada entre 3 y 20 dias despues de la fecha de referencia"
        )

    return ESTADO_GUIA_NO_COINCIDE, "La guia no cumple los criterios de validacion"


def _status_from_arl_candidate(
    arl_candidate: dict[str, Any] | None,
    has_arl_lookup: bool,
) -> tuple[str | None, str | None]:
    if not has_arl_lookup:
        return None, None

    if arl_candidate is None:
        return ESTADO_NO_CRUZADO, (
            "No se encontro evidencia ARL que coincida por cedula, entidad ARL y fecha"
        )

    if not arl_candidate.get("cumple_documento"):
        return ESTADO_DOCUMENTO_NO_ENCONTRADO, (
            "La evidencia ARL encontrada no coincide con la cedula esperada"
        )
    if not arl_candidate.get("cumple_correo"):
        return ESTADO_ARL_NO_COINCIDE, (
            "La evidencia ARL coincide por cedula, pero no coincide con la entidad ARL esperada"
        )
    if not arl_candidate.get("arl_fecha_en_ventana"):
        return ESTADO_FUERA_DE_PLAZO, (
            "La evidencia ARL existe, pero la fecha de recibo no cae en la ventana posterior"
        )
    if arl_candidate.get("cumple_plazo"):
        return ESTADO_CUMPLE, "Notificacion ARL validada por cedula, entidad ARL y fecha"
    if arl_candidate.get("arl_fuera_de_plazo"):
        return ESTADO_FUERA_DE_PLAZO, (
            "La evidencia ARL fue recibida entre 3 y 30 dias despues de la fecha de referencia"
        )

    return ESTADO_REQUIERE_REVISION, "La evidencia ARL encontrada requiere revision manual"


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


def _best_arl_candidate(
    expected_row: dict[str, Any],
    arl_document_index: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, bool]:
    if str(expected_row.get("tipo_destinatario") or "").upper() != "ARL":
        return None, False

    expected_document = normalize_document(
        expected_row.get("cedula_normalizada") or expected_row.get("cedula")
    )
    if not expected_document:
        return None, False

    candidates = arl_document_index.get(expected_document, [])
    if not candidates:
        return None, True

    scored_candidates = [_score_arl_candidate(expected_row, row) for row in candidates]
    scored_candidates.sort(
        key=lambda item: (
            item["cumple_documento"],
            item["cumple_correo"],
            item["arl_fecha_en_ventana"],
            item["cumple_plazo"],
            item["arl_fuera_de_plazo"],
            item["score_total"],
        ),
        reverse=True,
    )
    return scored_candidates[0], True


def _best_guia_candidate(
    expected_row: dict[str, Any],
    guia_index: dict[str, list[dict[str, Any]]],
    guia_document_index: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, bool]:
    expected_guide_key = _right_digits(expected_row.get("correo_o_guia_reportado"))
    metodo_busqueda = _guia_lookup_method(expected_row)
    expected_document = normalize_document(
        expected_row.get("cedula_normalizada") or expected_row.get("cedula")
    )
    if expected_guide_key:
        candidates = guia_index.get(expected_guide_key, [])
    elif metodo_busqueda == "GUIA_CEDULA_FECHA_ENVIA":
        if not expected_document:
            return None, False
        candidates = guia_document_index.get(expected_document, [])
    elif (
        str(expected_row.get("tipo_destinatario") or "").upper() == "PACIENTES"
        and expected_document
    ):
        candidates = guia_document_index.get(expected_document, [])
        if not candidates:
            return None, False
        metodo_busqueda = "GUIA_CEDULA_FALLBACK"
    else:
        return None, False

    scored_candidates = (
        [_score_guia_candidate(expected_row, row, metodo_busqueda) for row in candidates]
        if candidates
        else []
    )
    if (
        expected_guide_key
        and expected_document
        and (
            not scored_candidates
            or not any(
                item["guia_fecha_en_ventana"] and item["cumple_documento"]
                for item in scored_candidates
            )
        )
    ):
        fallback_candidates = guia_document_index.get(expected_document, [])
        scored_candidates.extend(
            _score_guia_candidate(expected_row, row, "GUIA_CEDULA_FALLBACK")
            for row in fallback_candidates
            if _guia_number(row) != expected_guide_key
        )

    if not scored_candidates:
        return None, True

    scored_candidates.sort(
        key=lambda item: (
            item["guia_fecha_en_ventana"],
            item["cumple_documento"],
            item["cumple_plazo"],
            item["guia_fuera_de_plazo"],
            item["score_total"],
            item["metodo_busqueda"] == "GUIA_ULTIMOS_9_DIGITOS",
        ),
        reverse=True,
    )
    return scored_candidates[0], True


def _build_revision_rows(
    expected_row: dict[str, Any],
    candidate: dict[str, Any] | None,
    has_document_candidates: bool,
    guia_candidate: dict[str, Any] | None = None,
    has_guia_lookup: bool = False,
    arl_candidate: dict[str, Any] | None = None,
    has_arl_lookup: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    correo_status, correo_pending_detail = _status_from_candidate(
        candidate,
        has_document_candidates,
    )
    guia_status, guia_pending_detail = _status_from_guia_candidate(
        guia_candidate,
        has_guia_lookup,
    )
    arl_status, arl_pending_detail = _status_from_arl_candidate(
        arl_candidate,
        has_arl_lookup,
    )
    if correo_status == ESTADO_CUMPLE:
        fuente_revision = "CORREO_CERTIFICADO"
    elif arl_status == ESTADO_CUMPLE:
        fuente_revision = "ARL_RADICADO_PDF"
    elif guia_status == ESTADO_CUMPLE:
        fuente_revision = "GUIA_CORREO_FISICO"
    elif has_arl_lookup and arl_status:
        fuente_revision = "ARL_RADICADO_PDF"
    elif has_guia_lookup and guia_status:
        fuente_revision = "GUIA_CORREO_FISICO"
    else:
        fuente_revision = "CORREO_CERTIFICADO"

    use_guia = fuente_revision == "GUIA_CORREO_FISICO"
    use_arl = fuente_revision == "ARL_RADICADO_PDF"
    status = (
        arl_status
        if use_arl
        else guia_status if use_guia else correo_status
    )
    pending_detail = (
        arl_pending_detail
        if use_arl
        else guia_pending_detail if use_guia else correo_pending_detail
    )
    guia_lookup_method = (
        guia_candidate.get("metodo_busqueda")
        if guia_candidate
        else _guia_lookup_method(expected_row) if has_guia_lookup else None
    )
    arl_lookup_method = (
        arl_candidate.get("metodo_busqueda")
        if arl_candidate
        else "ARL_CEDULA_ENTIDAD_FECHA" if has_arl_lookup else None
    )
    correo_row = candidate.get("correo_row") if candidate else None
    arl_row = arl_candidate.get("arl_row") if arl_candidate else None
    revision_date = utc_now_iso()
    cumple_documento = (
        arl_candidate.get("cumple_documento") if arl_candidate else False
    ) if use_arl else (
        guia_candidate.get("cumple_documento") if guia_candidate else False
    ) if use_guia else candidate.get("cumple_documento") if candidate else False
    cumple_evento = (
        arl_candidate.get("cumple_evento") if arl_candidate else False
    ) if use_arl else (
        guia_candidate.get("cumple_evento") if guia_candidate else False
    ) if use_guia else candidate.get("cumple_evento") if candidate else False
    cumple_correo = (
        arl_candidate.get("cumple_correo") if arl_candidate else False
    ) if use_arl else (
        guia_candidate.get("cumple_correo") if guia_candidate else False
    ) if use_guia else candidate.get("cumple_correo") if candidate else False
    cumple_plazo = (
        arl_candidate.get("cumple_plazo") if arl_candidate else False
    ) if use_arl else (
        guia_candidate.get("cumple_plazo") if guia_candidate else False
    ) if use_guia else candidate.get("cumple_plazo") if candidate else False
    cumple_asunto = False if use_guia or use_arl else candidate.get("cumple_asunto") if candidate else False
    score_total = (
        arl_candidate.get("score_total") if arl_candidate else 0
    ) if use_arl else (
        guia_candidate.get("score_total") if guia_candidate else 0
    ) if use_guia else candidate.get("score_total") if candidate else None
    fecha_referencia = (
        arl_candidate.get("fecha_referencia")
        if arl_candidate
        else normalize_date(_expected_reference_date(expected_row))
    ) if use_arl else (
        guia_candidate.get("fecha_referencia")
        if guia_candidate
        else normalize_date(_expected_reference_date(expected_row))
    ) if use_guia else candidate.get("fecha_audiencia") if candidate else None
    fecha_evidencia = (
        arl_candidate.get("fecha_recibo_comunicacion") if arl_candidate else None
    ) if use_arl else (
        guia_candidate.get("fecha_entrega_guia") if guia_candidate else None
    ) if use_guia else candidate.get("fecha_envio_certificado") if candidate else None
    dias_despues_referencia = (
        arl_candidate.get("dias_despues_referencia") if arl_candidate else None
    ) if use_arl else (
        guia_candidate.get("dias_despues_referencia") if guia_candidate else None
    ) if use_guia else candidate.get("dias_despues_audiencia") if candidate else None
    fuente_documento_match = (
        "ARL_CEDULA_PDF"
        if use_arl and cumple_documento
        else
        "GUIA_CEDULA_DESTINATARIO"
        if use_guia and cumple_documento
        else candidate.get("fuente_documento_match") if candidate else None
    )
    asunto_tipo_match = None if use_guia or use_arl else candidate.get("asunto_tipo_match") if candidate else None
    evento_tipo_match = (
        "RADICADO_RECIBIDO"
        if use_arl and cumple_evento
        else
        "ENTREGADO"
        if use_guia and cumple_evento
        else candidate.get("evento_tipo_match") if candidate else None
    )
    tipo_match_correo = (
        arl_lookup_method
        if use_arl and cumple_correo
        else
        guia_lookup_method
        if use_guia and cumple_correo
        else candidate.get("tipo_match_correo") if candidate else None
    )
    correo_esperado = (
        arl_candidate.get("arl_esperada") or expected_row.get("arl_esperada")
        if use_arl and arl_candidate
        else
        guia_candidate.get("guia_esperada") or expected_row.get("correo_o_guia_reportado")
        if use_guia and guia_candidate
        else candidate.get("correo_esperado") if candidate else None
    )
    correo_certificado = (
        arl_candidate.get("arl_detectada")
        if use_arl and arl_candidate
        else
        guia_candidate.get("guia_fisica")
        if use_guia and guia_candidate
        else candidate.get("correo_certificado") if candidate else None
    )
    distancia_correo = None if use_guia or use_arl else candidate.get("distancia_correo") if candidate else None
    score_asunto = None if use_guia or use_arl else candidate.get("score_asunto") if candidate else None
    score_evento = None if use_guia or use_arl else candidate.get("score_evento") if candidate else None
    criterio_documento = (
        "cedula_pdf_arl"
        if use_arl
        else
        "cedula_destinatario_guia"
        if use_guia
        else "cedula_en_asunto_o_adjuntos_correo"
    )
    criterio_evento = (
        "fecha_recibo_radicado_arl"
        if use_arl
        else "estado_guia_entregado" if use_guia else "evento_correo_certificado"
    )
    criterio_canal = (
        "entidad_arl"
        if use_arl
        else guia_lookup_method.lower() if use_guia and guia_lookup_method else "correo_destinatario"
    )
    criterio_plazo = (
        "fecha_recibo_comunicacion_arl"
        if use_arl
        else "fecha_entrega_guia" if use_guia else "fecha_envio_certificado"
    )

    detail = {
        "fuente_revision": fuente_revision,
        "estado_revision_notificacion": status,
        "pendiente_revision": pending_detail,
        "numero_radicado_normalizado": expected_row.get("numero_radicado_normalizado"),
        "cedula_normalizada": expected_row.get("cedula_normalizada"),
        "tipo_destinatario": expected_row.get("tipo_destinatario"),
        "fuente_correo_reportado": expected_row.get("fuente_correo_reportado"),
        "id_calificacion_sistema_envio_fallback": expected_row.get(
            "id_calificacion_sistema_envio_fallback"
        ),
        "hash_negocio_notificacion": expected_row.get("hash_negocio_notificacion"),
        "id_notificacion_correo_certificado_match": correo_row.get("id_notificacion_correo")
        if correo_row
        else None,
        "id_archivo_correo_certificado_match": correo_row.get("id_archivo")
        if correo_row
        else None,
        "id_notificacion_arl_radicado_match": arl_row.get("id_notificacion_arl_radicado")
        if arl_row
        else None,
        "id_archivo_arl_radicado_match": arl_row.get("id_archivo")
        if arl_row
        else None,
        "numero_linea_csv_match": correo_row.get("numero_linea_csv") if correo_row else None,
        "checks": {
            "cumple_documento": bool(cumple_documento),
            "cumple_asunto": bool(cumple_asunto),
            "cumple_evento": bool(cumple_evento),
            "cumple_correo": bool(cumple_correo),
            "cumple_plazo": bool(cumple_plazo),
        },
        "criterios_convergentes": {
            "cumple_documento": {
                "cumple": bool(cumple_documento),
                "criterio": criterio_documento,
                "fuente_match": fuente_documento_match,
            },
            "cumple_evento": {
                "cumple": bool(cumple_evento),
                "criterio": criterio_evento,
                "tipo_match": evento_tipo_match,
            },
            "cumple_correo": {
                "cumple": bool(cumple_correo),
                "criterio": criterio_canal,
                "tipo_match": tipo_match_correo,
            },
            "cumple_plazo": {
                "cumple": bool(cumple_plazo),
                "criterio": criterio_plazo,
                "fecha_referencia": fecha_referencia,
                "fecha_evidencia": fecha_evidencia,
                "dias_despues_referencia": dias_despues_referencia,
            },
        },
        "guia_fisica": {
            "aplica": has_guia_lookup,
            "estado_revision_notificacion": guia_status,
            "metodo_busqueda": guia_lookup_method,
            "guia_esperada": guia_candidate.get("guia_esperada") if guia_candidate else _right_digits(expected_row.get("correo_o_guia_reportado")),
            "guia_fisica": guia_candidate.get("guia_fisica") if guia_candidate else None,
            "cedula_esperada": guia_candidate.get("cedula_esperada") if guia_candidate else normalize_document(expected_row.get("cedula_normalizada") or expected_row.get("cedula")),
            "cedula_guia": guia_candidate.get("cedula_guia") if guia_candidate else None,
            "estado_guia": guia_candidate.get("estado_guia") if guia_candidate else None,
            "fecha_referencia": guia_candidate.get("fecha_referencia") if guia_candidate else normalize_date(_expected_reference_date(expected_row)),
            "fecha_entrega_guia": guia_candidate.get("fecha_entrega_guia") if guia_candidate else None,
            "dias_despues_referencia": guia_candidate.get("dias_despues_referencia") if guia_candidate else None,
            "id_archivo_guia": guia_candidate.get("id_archivo_guia") if guia_candidate else None,
            "id_guia_correo_fisico": guia_candidate.get("id_guia_correo_fisico") if guia_candidate else None,
            "hoja_origen_guia": guia_candidate.get("hoja_origen_guia") if guia_candidate else None,
        },
        "arl_radicado_pdf": {
            "aplica": has_arl_lookup,
            "estado_revision_notificacion": arl_status,
            "metodo_busqueda": arl_lookup_method,
            "cedula_esperada": arl_candidate.get("cedula_esperada") if arl_candidate else normalize_document(expected_row.get("cedula_normalizada") or expected_row.get("cedula")),
            "cedula_arl": arl_candidate.get("cedula_arl") if arl_candidate else None,
            "arl_esperada": arl_candidate.get("arl_esperada") if arl_candidate else expected_row.get("arl_esperada"),
            "arl_detectada": arl_candidate.get("arl_detectada") if arl_candidate else None,
            "fecha_referencia": arl_candidate.get("fecha_referencia") if arl_candidate else normalize_date(_expected_reference_date(expected_row)),
            "fecha_recibo_comunicacion": arl_candidate.get("fecha_recibo_comunicacion") if arl_candidate else None,
            "dias_despues_referencia": arl_candidate.get("dias_despues_referencia") if arl_candidate else None,
            "id_archivo_arl": arl_candidate.get("id_archivo_arl") if arl_candidate else None,
            "id_notificacion_arl_radicado": arl_candidate.get("id_notificacion_arl_radicado") if arl_candidate else None,
            "metodo_deteccion_arl": arl_candidate.get("metodo_deteccion_arl") if arl_candidate else None,
            "metodo_deteccion_fecha": arl_candidate.get("metodo_deteccion_fecha") if arl_candidate else None,
            "nombre_archivo_arl": arl_candidate.get("nombre_archivo_arl") if arl_candidate else None,
            "hash_arl_radicado": arl_candidate.get("hash_arl_radicado") if arl_candidate else None,
        },
        "score_asunto": score_asunto,
        "score_evento": score_evento,
        "fuente_documento_match": fuente_documento_match,
        "asunto_tipo_match": asunto_tipo_match,
        "evento_tipo_match": evento_tipo_match,
        "correos_esperados": candidate.get("correos_esperados") if candidate else [],
        "correo_esperado": correo_esperado,
        "correo_certificado": correo_certificado,
        "arl_esperada": expected_row.get("arl_esperada"),
        "arl_detectada": arl_candidate.get("arl_detectada") if arl_candidate else None,
        "tipo_match_correo": tipo_match_correo,
        "distancia_correo": distancia_correo,
        "fecha_audiencia": fecha_referencia,
        "fecha_envio_certificado": fecha_evidencia,
        "dias_despues_audiencia": dias_despues_referencia,
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
        "id_calificacion_sistema_caso": expected_row.get(
            "id_calificacion_sistema_caso"
        ),
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
        "id_notificacion_arl_radicado_match": arl_row.get("id_notificacion_arl_radicado")
        if arl_row
        else None,
        "id_archivo_arl_radicado_match": arl_row.get("id_archivo")
        if arl_row
        else None,
        "numero_linea_csv_match": correo_row.get("numero_linea_csv") if correo_row else None,
        "estado_revision_notificacion": status,
        "descripcion_revision": pending_detail,
        "cumple_documento": 1 if cumple_documento else 0,
        "cumple_asunto": 1 if cumple_asunto else 0,
        "cumple_evento": 1 if cumple_evento else 0,
        "cumple_correo": 1 if cumple_correo else 0,
        "cumple_plazo": 1 if cumple_plazo else 0,
        "score_total": score_total,
        "score_asunto": score_asunto,
        "score_evento": score_evento,
        "fuente_documento_match": fuente_documento_match,
        "asunto_tipo_match": asunto_tipo_match,
        "evento_tipo_match": evento_tipo_match,
        "tipo_match_correo": tipo_match_correo,
        "distancia_correo": distancia_correo,
        "correo_esperado": correo_esperado,
        "correo_certificado": correo_certificado,
        "arl_esperada": expected_row.get("arl_esperada"),
        "arl_detectada": arl_candidate.get("arl_detectada") if arl_candidate else None,
        "fecha_audiencia": fecha_referencia,
        "fecha_envio_certificado": fecha_evidencia,
        "dias_despues_audiencia": dias_despues_referencia,
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


def _refresh_cruce_notificacion_pendiente(
    id_archivo: int | None = None,
    id_notificacion_esperada_values: list[Any] | None = None,
) -> dict[str, int]:
    ids = [
        value
        for value in (id_notificacion_esperada_values or [])
        if value is not None
    ]
    total_deleted = 0
    total_inserted = 0

    def insert_sql(where_clause: str) -> str:
        return f"""
        INSERT INTO jnc.cruce_notificacion_pendiente (
            id_notificacion_esperada,
            id_calificacion_sistema_caso,
            id_caso,
            id_archivo,
            numero_radicado_normalizado,
            cedula_normalizada,
            tipo_destinatario,
            correo_o_guia_reportado,
            correo_normalizado,
            estado_revision_notificacion,
            motivo_pendiente,
            prioridad,
            requiere_auditoria_manual,
            fecha_ultima_revision,
            hash_negocio_notificacion,
            activo,
            fecha_creacion
        )
        SELECT
            ne.id_notificacion_esperada,
            ne.id_calificacion_sistema_caso,
            ne.id_caso,
            ne.id_archivo,
            ne.numero_radicado_normalizado,
            ne.cedula_normalizada,
            ne.tipo_destinatario,
            ne.correo_o_guia_reportado,
            ne.correo_normalizado,
            COALESCE(
                rcn.estado_revision_notificacion,
                ne.estado_revision_notificacion,
                'SIN_REVISION'
            ) AS estado_revision_notificacion,
            COALESCE(rcn.descripcion_revision, ne.pendiente_revision)
                AS motivo_pendiente,
            CASE
                WHEN COALESCE(rcn.estado_revision_notificacion, ne.estado_revision_notificacion, 'SIN_REVISION') = 'REQUIERE_REVISION_MANUAL' THEN 10
                WHEN COALESCE(rcn.estado_revision_notificacion, ne.estado_revision_notificacion, 'SIN_REVISION') = 'NO_CRUZADO' THEN 20
                WHEN COALESCE(rcn.estado_revision_notificacion, ne.estado_revision_notificacion, 'SIN_REVISION') = 'SIN_REVISION' THEN 30
                ELSE 50
            END AS prioridad,
            1 AS requiere_auditoria_manual,
            COALESCE(rcn.fecha_revision, ne.fecha_revision_notificacion)
                AS fecha_ultima_revision,
            ne.hash_negocio_notificacion,
            1 AS activo,
            SYSUTCDATETIME() AS fecha_creacion
        FROM jnc.notificacion_esperada AS ne
        LEFT JOIN jnc.resultado_cruce_notificacion AS rcn
            ON rcn.id_notificacion_esperada = ne.id_notificacion_esperada
           AND rcn.activo = 1
        WHERE ne.activo = 1
          AND COALESCE(
                rcn.estado_revision_notificacion,
                ne.estado_revision_notificacion,
                'SIN_REVISION'
              ) NOT IN ('CUMPLE', 'FUERA_DE_PLAZO')
          AND {where_clause}
        """

    if ids:
        for chunk in [ids[index : index + 900] for index in range(0, len(ids), 900)]:
            placeholders = ", ".join("?" for _ in chunk)
            total_deleted += db.execute_sql(
                (
                    "DELETE FROM jnc.cruce_notificacion_pendiente "
                    f"WHERE id_notificacion_esperada IN ({placeholders})"
                ),
                chunk,
            )
            total_inserted += db.execute_sql(
                insert_sql(
                    f"ne.id_notificacion_esperada IN ({placeholders})"
                ),
                chunk,
            )
    elif id_archivo is not None:
        total_deleted = db.execute_sql(
            "DELETE FROM jnc.cruce_notificacion_pendiente WHERE id_archivo = ?",
            [id_archivo],
        )
        total_inserted = db.execute_sql(
            insert_sql("ne.id_archivo = ?"),
            [id_archivo],
        )
    else:
        total_deleted = db.delete_all("jnc.cruce_notificacion_pendiente")
        total_inserted = db.execute_sql(insert_sql("1 = 1"))

    return {
        "pendientes_eliminados": total_deleted,
        "pendientes_insertados": total_inserted,
    }


def recalcular_cruce_notificaciones(
    id_archivo_salas: int | None = None,
    id_archivo_evidencia: int | None = None,
    solo_pendientes: bool = True,
    batch_size: int | None = None,
    after_id_notificacion_esperada: int | None = None,
    fecha_referencia_desde: date | None = None,
    fecha_referencia_hasta: date | None = None,
    refrescar_resumen: bool = True,
    fuente_cruce: str | None = None,
) -> dict[str, Any]:
    fuente_cruce_normalizada = _normalize_fuente_cruce(fuente_cruce)
    source_scoped_run = fuente_cruce_normalizada != FUENTE_FULL
    evidence_scoped_run = id_archivo_evidencia is not None
    cedulas_evidencia = (
        _fetch_arl_cedulas_by_archivo(id_archivo_evidencia)
        if id_archivo_evidencia is not None
        and fuente_cruce_normalizada == FUENTE_ARL
        else []
    )
    chunked_run = batch_size is not None or after_id_notificacion_esperada is not None
    scoped_run = (
        chunked_run
        or fecha_referencia_desde is not None
        or fecha_referencia_hasta is not None
        or source_scoped_run
        or evidence_scoped_run
    )
    fetched_expected_rows = _fetch_expected_rows(
        id_archivo_salas,
        batch_size=batch_size,
        after_id_notificacion_esperada=after_id_notificacion_esperada,
        solo_pendientes_filter=scoped_run and solo_pendientes,
        fecha_referencia_desde=fecha_referencia_desde,
        fecha_referencia_hasta=fecha_referencia_hasta,
        cedulas_normalizadas=cedulas_evidencia,
    )
    fetched_last_id = max(
        (
            row.get("id_notificacion_esperada")
            for row in fetched_expected_rows
            if row.get("id_notificacion_esperada") is not None
        ),
        default=None,
    )
    all_expected_rows = fetched_expected_rows
    _enrich_expected_arl_fields(all_expected_rows)
    latest_calificacion_audiencia_date = _fetch_latest_calificacion_sistema_audiencia_date()
    aplica_filtro_raw_fecha_maxima = id_archivo_salas is None
    raw_skipped_by_date = 0
    if aplica_filtro_raw_fecha_maxima:
        all_expected_rows, raw_skipped_by_date = _filter_raw_by_latest_audiencia_date(
            all_expected_rows,
            latest_calificacion_audiencia_date,
        )
    expected_rows = all_expected_rows
    if solo_pendientes:
        expected_rows = [
            row
            for row in expected_rows
            if row.get("estado_revision_notificacion") != ESTADO_CUMPLE
        ]

    date_window = _correo_date_window(expected_rows)
    guia_date_window = _guia_date_window(expected_rows)
    arl_date_window = _guia_date_window(expected_rows)
    load_correo = fuente_cruce_normalizada in {FUENTE_FULL, FUENTE_CORREO}
    load_guia = fuente_cruce_normalizada in {FUENTE_FULL, FUENTE_GUIA}
    load_arl = fuente_cruce_normalizada in {FUENTE_FULL, FUENTE_ARL}
    correo_rows = _fetch_correo_rows(date_window) if load_correo else []
    correo_index = _build_correo_index(correo_rows) if load_correo else {}
    guia_rows = _fetch_guia_rows(guia_date_window) if load_guia else []
    guia_index = _build_guia_index(guia_rows) if load_guia else {}
    guia_document_index = _build_guia_document_index(guia_rows) if load_guia else {}
    arl_rows = (
        _fetch_arl_radicado_rows(arl_date_window, id_archivo_evidencia)
        if load_arl
        else []
    )
    arl_document_index = _build_arl_document_index(arl_rows) if load_arl else {}

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
        "notificaciones_leidas": len(fetched_expected_rows),
        "batch_size": batch_size,
        "after_id_notificacion_esperada": after_id_notificacion_esperada,
        "id_archivo_evidencia": id_archivo_evidencia,
        "cedulas_evidencia": cedulas_evidencia,
        "fecha_referencia_desde": fecha_referencia_desde.isoformat()
        if fecha_referencia_desde
        else None,
        "fecha_referencia_hasta": fecha_referencia_hasta.isoformat()
        if fecha_referencia_hasta
        else None,
        "ultimo_id_notificacion_esperada": max(
            (
                row.get("id_notificacion_esperada")
                for row in expected_rows
                if row.get("id_notificacion_esperada") is not None
            ),
            default=None,
        ),
        "ultimo_id_leido": fetched_last_id,
        "next_cursor": None,
        "chunked_run": chunked_run,
        "scoped_run": scoped_run,
        "fuente_cruce": fuente_cruce_normalizada,
        "source_scoped_run": source_scoped_run,
        "refrescar_resumen": refrescar_resumen,
        "filtro_raw_fecha_maxima_aplicado": aplica_filtro_raw_fecha_maxima,
        "raw_omitidas_por_fecha_audiencia": raw_skipped_by_date,
        "fecha_audiencia_calificacion_sistema_maxima": latest_calificacion_audiencia_date.isoformat()
        if latest_calificacion_audiencia_date
        else None,
        "notificaciones_actualizadas": 0,
        "correos_evaluados": len(correo_rows),
        "guias_evaluadas": len(guia_rows),
        "arls_radicado_evaluadas": len(arl_rows),
        "guias_entregadas_indexadas": sum(len(rows) for rows in guia_index.values()),
        "arls_radicado_indexadas": sum(len(rows) for rows in arl_document_index.values()),
        "ventana_correo_desde": date_window[0].isoformat() if date_window else None,
        "ventana_correo_hasta": date_window[1].isoformat() if date_window else None,
        "ventana_guia_desde": guia_date_window[0].isoformat() if guia_date_window else None,
        "ventana_guia_hasta": guia_date_window[1].isoformat() if guia_date_window else None,
        "ventana_arl_desde": arl_date_window[0].isoformat() if arl_date_window else None,
        "ventana_arl_hasta": arl_date_window[1].isoformat() if arl_date_window else None,
        "cumplen": 0,
        "cumplen_por_guia_fisica": 0,
        "cumplen_por_arl_radicado": 0,
        "fuera_de_plazo_por_guia_fisica": 0,
        "fuera_de_plazo_por_arl_radicado": 0,
        "pendientes": 0,
        "sin_correo_certificado": 0,
        "cruces_eliminados": 0,
        "cruces_insertados": 0,
        "notificaciones_omitidas_por_fuente_no_aplicable": 0,
        "notificaciones_conservadas_por_estado_anterior": 0,
        "porcentaje_notificaciones_validadas": 0.0,
        "radicados_evaluados": 0,
        "radicados_validados": 0,
        "radicados_validados_extemporaneos": 0,
        "radicados_pendientes": 0,
        "porcentaje_radicados_validados": 0.0,
        "porcentaje_radicados_validados_extemporaneos": 0.0,
        "cruce_notificacion_pendiente": {},
        "resumen_validacion_radicado": {},
    }
    if batch_size is not None and summary["notificaciones_leidas"] >= batch_size:
        summary["next_cursor"] = summary["ultimo_id_leido"]

    for expected_row in expected_rows:
        candidate = None
        has_document_candidates = False
        guia_candidate = None
        has_guia_lookup = False
        arl_candidate = None
        has_arl_lookup = False
        if load_correo:
            candidate, has_document_candidates = _best_candidate(expected_row, correo_index)
        if load_guia:
            guia_candidate, has_guia_lookup = _best_guia_candidate(
                expected_row,
                guia_index,
                guia_document_index,
            )
        if load_arl:
            arl_candidate, has_arl_lookup = _best_arl_candidate(
                expected_row,
                arl_document_index,
            )
        if fuente_cruce_normalizada == FUENTE_GUIA and not has_guia_lookup:
            summary["notificaciones_omitidas_por_fuente_no_aplicable"] += 1
            continue
        if fuente_cruce_normalizada == FUENTE_ARL and not has_arl_lookup:
            summary["notificaciones_omitidas_por_fuente_no_aplicable"] += 1
            continue

        update_row, cruce_row = _build_revision_rows(
            expected_row,
            candidate,
            has_document_candidates,
            guia_candidate,
            has_guia_lookup,
            arl_candidate,
            has_arl_lookup,
        )
        previous_status = expected_row.get("estado_revision_notificacion") or "SIN_REVISION"
        if source_scoped_run and not _should_apply_source_update(
            previous_status,
            update_row["estado_revision_notificacion"],
        ):
            summary["notificaciones_conservadas_por_estado_anterior"] += 1
            status_by_expected_id[expected_row.get("id_notificacion_esperada")] = previous_status
            continue

        updates.append(update_row)
        cruce_rows.append(cruce_row)

        status = update_row["estado_revision_notificacion"]
        status_by_expected_id[expected_row.get("id_notificacion_esperada")] = status
        detail = json.loads(update_row["detalle_revision_json"])
        if detail.get("fuente_revision") == "GUIA_CORREO_FISICO":
            if status == ESTADO_CUMPLE:
                summary["cumplen_por_guia_fisica"] += 1
            elif status == ESTADO_FUERA_DE_PLAZO:
                summary["fuera_de_plazo_por_guia_fisica"] += 1
        if detail.get("fuente_revision") == "ARL_RADICADO_PDF":
            if status == ESTADO_CUMPLE:
                summary["cumplen_por_arl_radicado"] += 1
            elif status == ESTADO_FUERA_DE_PLAZO:
                summary["fuera_de_plazo_por_arl_radicado"] += 1

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
        if scoped_run:
            summary["cruces_eliminados"] = db.delete_by_column_values(
                "jnc.resultado_cruce_notificacion",
                "id_notificacion_esperada",
                [row.get("id_notificacion_esperada") for row in cruce_rows],
            )
        elif not solo_pendientes and id_archivo_salas is not None:
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
    elif not chunked_run and not solo_pendientes and id_archivo_salas is not None:
        summary["cruces_eliminados"] = db.delete_by_archivo(
            "jnc.resultado_cruce_notificacion",
            id_archivo_salas,
        )

    summary["notificaciones_actualizadas"] = db.execute_many_updates(
        "jnc.notificacion_esperada",
        "id_notificacion_esperada",
        updates,
    )
    summary["cruce_notificacion_pendiente"] = _refresh_cruce_notificacion_pendiente(
        id_archivo=id_archivo_salas,
        id_notificacion_esperada_values=[
            row.get("id_notificacion_esperada") for row in cruce_rows
        ]
        if scoped_run or solo_pendientes
        else None,
    )
    if refrescar_resumen:
        summary["resumen_validacion_radicado"] = refrescar_resumen_validacion_radicado()
    return summary
