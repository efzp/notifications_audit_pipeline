import json
import logging
from datetime import datetime, timezone
from typing import Any

import azure.functions as func

import procesador
import procesador_correo
from src.load import db
from src.load.write_correo import write_correo_result_to_sql
from src.load.write_salas import write_salas_result_to_sql


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
        result = processor(payload)
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
