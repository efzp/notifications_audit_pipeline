import base64
import binascii
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

import azure.functions as func

import procesador
import procesador_audiencias
import procesador_arls
import procesador_calificaciones
import procesador_correo
import procesador_guias
import procesador_revision_manual_guias
from src.load import db
from src.load.write_audiencias import write_audiencias_result_to_sql
from src.load.write_arls import write_arls_result_to_sql
from src.load.write_calificaciones import write_calificaciones_result_to_sql
from src.load.write_correo import write_correo_result_to_sql
from src.load.write_guias import write_guias_result_to_sql
from src.load.write_revision_manual_guias import (
    write_revision_manual_guias_result_to_sql,
)
from src.load.write_salas import write_salas_result_to_sql
from src.reconcile.notificaciones import recalcular_cruce_notificaciones
from src.reconcile.revision_manual_guias import aplicar_revision_manual_guias


app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


def build_json_response(body: dict[str, Any], status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(body, ensure_ascii=False),
        status_code=status_code,
        mimetype="application/json",
    )


def get_request_payload(req: func.HttpRequest) -> dict[str, Any]:
    try:
        payload = req.get_json()
    except ValueError as exc:
        raise ValueError("El body debe ser un JSON valido") from exc

    if not isinstance(payload, dict):
        raise ValueError("El body debe ser un objeto JSON")

    return payload


def get_optional_request_payload(req: func.HttpRequest) -> dict[str, Any]:
    try:
        raw_body = req.get_body()
    except Exception:
        raw_body = b""

    if not raw_body:
        return {}

    return get_request_payload(req)


def get_id_archivo(payload: dict[str, Any]) -> int:
    raw_id = payload.get("id_archivo")
    if raw_id in (None, ""):
        raise ValueError("El payload debe incluir id_archivo")

    try:
        return int(raw_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("id_archivo debe ser numerico") from exc


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def parse_optional_int(payload: dict[str, Any], field_name: str) -> int | None:
    raw_value = payload.get(field_name)
    if raw_value in (None, ""):
        return None

    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} debe ser numerico") from exc


def parse_optional_positive_int(payload: dict[str, Any], field_name: str) -> int | None:
    value = parse_optional_int(payload, field_name)
    if value is not None and value <= 0:
        raise ValueError(f"{field_name} debe ser mayor que cero")
    return value


def parse_bool(payload: dict[str, Any], field_name: str, default: bool) -> bool:
    raw_value = payload.get(field_name, default)
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, int) and raw_value in (0, 1):
        return bool(raw_value)
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "si", "sí", "yes"}:
            return True
        if normalized in {"0", "false", "no"}:
            return False

    raise ValueError(f"{field_name} debe ser booleano")


def parse_optional_text(payload: dict[str, Any], field_name: str) -> str | None:
    raw_value = payload.get(field_name)
    if raw_value in (None, ""):
        return None
    return str(raw_value)


def compute_payload_file_hash(payload: dict[str, Any]) -> str | None:
    raw_content = payload.get("file_content_base64")
    if not raw_content:
        return None

    if isinstance(raw_content, str) and "," in raw_content[:100]:
        raw_content = raw_content.split(",", 1)[1]

    try:
        file_bytes = base64.b64decode(raw_content, validate=False)
    except (binascii.Error, TypeError) as exc:
        raise ValueError("file_content_base64 no es un Base64 valido") from exc

    return hashlib.sha256(file_bytes).hexdigest()


def find_processed_duplicate(
    id_archivo: int,
    tipo_archivo: str | None,
    hash_archivo: str | None,
) -> dict[str, Any] | None:
    if not hash_archivo:
        return None

    where = (
        "[hash_archivo] = ? "
        "AND [id_archivo] <> ? "
        "AND [estado_proceso] IN ('PROCESADO', 'PROCESADO_CON_ALERTAS')"
    )
    params: list[Any] = [hash_archivo, id_archivo]

    if tipo_archivo:
        where = (
            "[hash_archivo] = ? "
            "AND [tipo_archivo] = ? "
            "AND [id_archivo] <> ? "
            "AND [estado_proceso] IN ('PROCESADO', 'PROCESADO_CON_ALERTAS')"
        )
        params = [hash_archivo, tipo_archivo, id_archivo]

    rows = db.fetch_rows(
        "jnc.etl_archivo_cargado",
        ["id_archivo", "nombre_archivo", "estado_proceso", "fecha_fin_proceso"],
        where,
        params,
    )
    if not rows:
        return None

    return rows[0]


def mark_duplicate_file(
    id_archivo: int,
    hash_archivo: str,
    duplicate_row: dict[str, Any],
) -> dict[str, Any]:
    duplicate_id = duplicate_row.get("id_archivo")
    message = f"Archivo duplicado. Ya fue procesado previamente con id_archivo={duplicate_id}."
    db.execute_update(
        "jnc.etl_archivo_cargado",
        "id_archivo",
        id_archivo,
        {
            "hash_archivo": hash_archivo,
            "estado_proceso": "DUPLICADO",
            "mensaje_error": message,
            "fecha_fin_proceso": utc_now_iso(),
        },
    )
    return {
        "status": "DUPLICADO",
        "id_archivo": id_archivo,
        "id_archivo_original": duplicate_id,
        "estado_proceso": "DUPLICADO",
        "mensaje": message,
    }


def register_file_hash(id_archivo: int, hash_archivo: str | None) -> None:
    if not hash_archivo:
        return

    db.execute_update(
        "jnc.etl_archivo_cargado",
        "id_archivo",
        id_archivo,
        {"hash_archivo": hash_archivo},
    )


def mark_processing_error(id_archivo: int | None, message: str) -> None:
    if id_archivo is None:
        return

    try:
        db.execute_update(
            "jnc.etl_archivo_cargado",
            "id_archivo",
            id_archivo,
            {
                "estado_proceso": "ERROR_PROCESAMIENTO",
                "mensaje_error": message,
                "fecha_fin_proceso": utc_now_iso(),
            },
        )
    except Exception:
        logging.exception("No fue posible marcar ERROR_PROCESAMIENTO para id_archivo=%s", id_archivo)


def handle_sql_processing(
    req: func.HttpRequest,
    route_name: str,
    processor,
    writer,
) -> func.HttpResponse:
    logging.info("%s ejecutada", route_name)
    id_archivo = None

    try:
        payload = get_request_payload(req)
        id_archivo = get_id_archivo(payload)
        hash_archivo = compute_payload_file_hash(payload)
        register_file_hash(id_archivo, hash_archivo)

        duplicate_row = find_processed_duplicate(
            id_archivo,
            payload.get("tipo_archivo"),
            hash_archivo,
        )
        if duplicate_row:
            return build_json_response(
                mark_duplicate_file(id_archivo, hash_archivo, duplicate_row),
                status_code=200,
            )

        result = processor(payload)
        if "recalcular_cruce" in payload:
            result["_recalcular_cruce"] = parse_bool(payload, "recalcular_cruce", True)
        summary = writer(id_archivo, result)
        return build_json_response(summary, status_code=200)
    except Exception as exc:
        logging.exception("Error procesando %s", route_name)
        message = str(exc)
        mark_processing_error(id_archivo, message)
        return build_json_response(
            {
                "status": "ERROR_PROCESAMIENTO",
                "id_archivo": id_archivo,
                "errores": 1,
                "mensaje": message,
            },
            status_code=500,
        )


def handle_read_processing(
    req: func.HttpRequest,
    route_name: str,
    processor,
) -> func.HttpResponse:
    logging.info("%s ejecutada", route_name)

    try:
        payload = get_request_payload(req)
        result = processor(payload)
        return build_json_response(result, status_code=200)
    except Exception as exc:
        logging.exception("Error procesando %s", route_name)
        return build_json_response(
            {
                "status": "ERROR_PROCESAMIENTO",
                "errores": 1,
                "mensaje": str(exc),
            },
            status_code=500,
        )


def handle_recalcular_cruce_notificaciones(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("recalcular_cruce_notificaciones ejecutada")

    try:
        payload = get_optional_request_payload(req)
        id_archivo_salas = parse_optional_int(payload, "id_archivo_salas")
        id_archivo_evidencia = parse_optional_int(payload, "id_archivo_evidencia")
        solo_pendientes = parse_bool(payload, "solo_pendientes", False)
        batch_size = parse_optional_positive_int(payload, "batch_size")
        after_id_notificacion_esperada = parse_optional_int(
            payload,
            "after_id_notificacion_esperada",
        )
        if (
            after_id_notificacion_esperada is not None
            and after_id_notificacion_esperada < 0
        ):
            raise ValueError("after_id_notificacion_esperada no puede ser negativo")
        refrescar_resumen = parse_bool(
            payload,
            "refrescar_resumen",
            batch_size is None,
        )
        fuente_cruce = (
            parse_optional_text(payload, "fuente_cruce")
            or parse_optional_text(payload, "fuente_actualizada")
        )

        summary = db.run_in_transaction(
            lambda: recalcular_cruce_notificaciones(
                id_archivo_salas=id_archivo_salas,
                id_archivo_evidencia=id_archivo_evidencia,
                solo_pendientes=solo_pendientes,
                batch_size=batch_size,
                after_id_notificacion_esperada=after_id_notificacion_esperada,
                refrescar_resumen=refrescar_resumen,
                fuente_cruce=fuente_cruce,
            )
        )
        return build_json_response(
            {
                "status": "OK",
                "id_archivo_salas": id_archivo_salas,
                "id_archivo_evidencia": id_archivo_evidencia,
                "solo_pendientes": solo_pendientes,
                "batch_size": batch_size,
                "after_id_notificacion_esperada": after_id_notificacion_esperada,
                "refrescar_resumen": refrescar_resumen,
                "fuente_cruce": fuente_cruce,
                "cruce_notificaciones": summary,
            },
            status_code=200,
        )
    except Exception as exc:
        logging.exception("Error recalculando cruce_notificaciones")
        return build_json_response(
            {
                "status": "ERROR_PROCESAMIENTO",
                "errores": 1,
                "mensaje": str(exc),
            },
            status_code=500,
        )


def handle_aplicar_revision_manual_guias(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("aplicar_revision_manual_guias ejecutada")

    try:
        payload = get_optional_request_payload(req)
        id_archivo = parse_optional_int(payload, "id_archivo")
        batch_size = parse_optional_positive_int(payload, "batch_size")
        refrescar_resumen = parse_bool(payload, "refrescar_resumen", True)

        summary = db.run_in_transaction(
            lambda: aplicar_revision_manual_guias(
                id_archivo=id_archivo,
                batch_size=batch_size,
                refrescar_resumen=refrescar_resumen,
            )
        )
        return build_json_response(
            {
                "status": "OK",
                "id_archivo": id_archivo,
                "batch_size": batch_size,
                "refrescar_resumen": refrescar_resumen,
                "revision_manual_guias": summary,
            },
            status_code=200,
        )
    except Exception as exc:
        logging.exception("Error aplicando revision manual de guias")
        return build_json_response(
            {
                "status": "ERROR_PROCESAMIENTO",
                "errores": 1,
                "mensaje": str(exc),
            },
            status_code=500,
        )


@app.route(route="procesar_input_salas", methods=["POST"])
def procesar_input_salas(req: func.HttpRequest) -> func.HttpResponse:
    return handle_sql_processing(
        req,
        "procesar_input_salas",
        procesador.process_payload_data,
        write_salas_result_to_sql,
    )


@app.route(route="procesar_correo_certificado", methods=["POST"])
def procesar_correo_certificado(req: func.HttpRequest) -> func.HttpResponse:
    return handle_sql_processing(
        req,
        "procesar_correo_certificado",
        procesador_correo.process_payload_data,
        write_correo_result_to_sql,
    )


@app.route(route="procesar_input_pdf_audiencias", methods=["POST"])
def procesar_input_pdf_audiencias(req: func.HttpRequest) -> func.HttpResponse:
    return handle_sql_processing(
        req,
        "procesar_input_pdf_audiencias",
        procesador_audiencias.process_payload_data,
        write_audiencias_result_to_sql,
    )


@app.route(route="procesar_guias_correo_fisico", methods=["POST"])
def procesar_guias_correo_fisico(req: func.HttpRequest) -> func.HttpResponse:
    return handle_sql_processing(
        req,
        "procesar_guias_correo_fisico",
        procesador_guias.process_payload_data,
        write_guias_result_to_sql,
    )


@app.route(route="procesar_revision_manual_guias", methods=["POST"])
def procesar_revision_manual_guias(req: func.HttpRequest) -> func.HttpResponse:
    return handle_sql_processing(
        req,
        "procesar_revision_manual_guias",
        procesador_revision_manual_guias.process_payload_data,
        write_revision_manual_guias_result_to_sql,
    )


@app.route(route="procesar_arls_radicado_pdf", methods=["POST"])
def procesar_arls_radicado_pdf(req: func.HttpRequest) -> func.HttpResponse:
    return handle_sql_processing(
        req,
        "procesar_arls_radicado_pdf",
        procesador_arls.process_payload_data,
        write_arls_result_to_sql,
    )


@app.route(route="procesar_calificaciones_software", methods=["POST"])
def procesar_calificaciones_software(req: func.HttpRequest) -> func.HttpResponse:
    return handle_sql_processing(
        req,
        "procesar_calificaciones_software",
        procesador_calificaciones.process_payload_data,
        write_calificaciones_result_to_sql,
    )


@app.route(route="procesar_sistema_jnc", methods=["POST"])
def procesar_sistema_jnc(req: func.HttpRequest) -> func.HttpResponse:
    return handle_sql_processing(
        req,
        "procesar_sistema_jnc",
        procesador_calificaciones.process_payload_data,
        write_calificaciones_result_to_sql,
    )


@app.route(route="recalcular_cruce_notificaciones", methods=["POST"])
def recalcular_cruce_notificaciones_route(req: func.HttpRequest) -> func.HttpResponse:
    return handle_recalcular_cruce_notificaciones(req)


@app.route(route="aplicar_revision_manual_guias", methods=["POST"])
def aplicar_revision_manual_guias_route(req: func.HttpRequest) -> func.HttpResponse:
    return handle_aplicar_revision_manual_guias(req)
