import base64
import binascii
import hashlib
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
    if not hash_archivo or not tipo_archivo:
        return None

    rows = db.fetch_rows(
        "jnc.etl_archivo_cargado",
        ["id_archivo", "nombre_archivo", "estado_proceso", "fecha_fin_proceso"],
        (
            "[hash_archivo] = ? "
            "AND [tipo_archivo] = ? "
            "AND [id_archivo] <> ? "
            "AND [estado_proceso] IN ('PROCESADO', 'PROCESADO_CON_ALERTAS')"
        ),
        [hash_archivo, tipo_archivo, id_archivo],
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
