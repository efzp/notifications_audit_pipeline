import base64
import binascii
import hashlib
import json
import logging
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

import azure.functions as func

import procesador
import procesador_audiencias
import procesador_arls
import procesador_calificaciones
import procesador_correo
import procesador_correo_pdf
import procesador_guias
import procesador_revision_manual_notificaciones
from src.load import db
from src.load.write_audiencias import write_audiencias_result_to_sql
from src.load.write_arls import write_arls_result_to_sql
from src.load.write_calificaciones import write_calificaciones_result_to_sql
from src.load.write_correo import (
    write_correo_pdf_result_to_sql,
    write_correo_result_to_sql,
)
from src.load.write_guias import write_guias_result_to_sql
from src.load.write_revision_manual_notificaciones import (
    write_revision_manual_notificaciones_result_to_sql,
)
from src.load.write_salas import write_salas_result_to_sql
from src.reconcile.notificaciones import recalcular_cruce_notificaciones
from src.reconcile.resumen_validacion import refrescar_resumen_validacion_radicado
from src.reconcile.revision_manual_notificaciones import aplicar_revision_manual_notificaciones
from src.utils.normalization import normalize_document


app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


def build_json_response(body: dict[str, Any], status_code: int = 200) -> func.HttpResponse:
    """Construye una respuesta HTTP JSON uniforme para todos los endpoints."""
    return func.HttpResponse(
        json.dumps(body, ensure_ascii=False),
        status_code=status_code,
        mimetype="application/json",
    )


def get_request_payload(req: func.HttpRequest) -> dict[str, Any]:
    """Lee y valida que el body sea un objeto JSON."""
    try:
        payload = req.get_json()
    except ValueError as exc:
        raise ValueError("El body debe ser un JSON valido") from exc

    if not isinstance(payload, dict):
        raise ValueError("El body debe ser un objeto JSON")

    return payload


def get_optional_request_payload(req: func.HttpRequest) -> dict[str, Any]:
    """Permite endpoints operativos con body opcional."""
    try:
        raw_body = req.get_body()
    except Exception:
        raw_body = b""

    if not raw_body:
        return {}

    return get_request_payload(req)


def get_id_archivo(payload: dict[str, Any]) -> int:
    """Obtiene el id_archivo que identifica el registro ETL base."""
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


def parse_optional_positive_int_list(
    payload: dict[str, Any],
    field_name: str,
    max_items: int = 100,
) -> list[int] | None:
    raw_value = payload.get(field_name)
    if raw_value is None:
        return None
    if not isinstance(raw_value, list):
        raise ValueError(f"{field_name} debe ser una lista de numeros")
    if not raw_value:
        raise ValueError(f"{field_name} no puede estar vacia")
    if len(raw_value) > max_items:
        raise ValueError(f"{field_name} admite maximo {max_items} elementos")

    values: list[int] = []
    seen: set[int] = set()
    for index, raw_item in enumerate(raw_value):
        if isinstance(raw_item, bool):
            raise ValueError(
                f"{field_name}[{index}] debe ser un numero entero positivo"
            )
        try:
            item = int(raw_item)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{field_name}[{index}] debe ser un numero entero positivo"
            ) from exc
        if item <= 0:
            raise ValueError(
                f"{field_name}[{index}] debe ser un numero entero positivo"
            )
        if item not in seen:
            values.append(item)
            seen.add(item)

    return values


def parse_bool(payload: dict[str, Any], field_name: str, default: bool) -> bool:
    raw_value = payload.get(field_name, default)
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, int) and raw_value in (0, 1):
        return bool(raw_value)
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "si", "yes"}:
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
    """Calcula hash del archivo recibido para detectar reprocesos duplicados."""
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
    """Busca archivos ya procesados con el mismo hash antes de escribir de nuevo."""
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
    """Marca el registro actual como duplicado y referencia el archivo original."""
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
    """Persistencia temprana del hash para trazabilidad del archivo recibido."""
    if not hash_archivo:
        return

    db.execute_update(
        "jnc.etl_archivo_cargado",
        "id_archivo",
        id_archivo,
        {"hash_archivo": hash_archivo},
    )


def mark_processing_error(id_archivo: int | None, message: str) -> None:
    """Intenta reflejar errores del endpoint en etl_archivo_cargado."""
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
    """
    Orquestador comun para endpoints que procesan un archivo y escriben a SQL.

    Flujo:
    1. Lee payload e identifica el id_archivo efectivo.
    2. Calcula hash del contenido y evita duplicados ya procesados.
    3. Ejecuta el procesador especifico del tipo de archivo.
    4. Delega la escritura transaccional al writer correspondiente.
    """
    logging.info("%s ejecutada", route_name)
    id_archivo = None
    id_archivo_solicitud = None

    try:
        payload = get_request_payload(req)
        id_archivo_solicitud = get_id_archivo(payload)
        id_archivo = (
            parse_optional_int(payload, "id_archivo_reproceso")
            or parse_optional_int(payload, "id_archivo_destino")
            or id_archivo_solicitud
        )
        force_reprocess = parse_bool(payload, "forzar_reproceso", False)
        hash_archivo = compute_payload_file_hash(payload)
        register_file_hash(id_archivo_solicitud, hash_archivo)
        if id_archivo != id_archivo_solicitud:
            register_file_hash(id_archivo, hash_archivo)

        duplicate_row = find_processed_duplicate(
            id_archivo,
            payload.get("tipo_archivo"),
            hash_archivo,
        )
        if duplicate_row and not force_reprocess:
            return build_json_response(
                mark_duplicate_file(id_archivo, hash_archivo, duplicate_row),
                status_code=200,
            )

        result = processor(payload)
        if force_reprocess:
            result["_forzar_reproceso"] = True
        if "recalcular_cruce" in payload:
            result["_recalcular_cruce"] = parse_bool(payload, "recalcular_cruce", True)
        summary = writer(id_archivo, result)
        if id_archivo != id_archivo_solicitud:
            db.execute_update(
                "jnc.etl_archivo_cargado",
                "id_archivo",
                id_archivo_solicitud,
                {
                    "estado_proceso": "DUPLICADO",
                    "mensaje_error": (
                        "Reproceso redirigido al id_archivo="
                        f"{id_archivo}."
                    ),
                    "fecha_fin_proceso": utc_now_iso(),
                },
            )
            summary["id_archivo_solicitud"] = id_archivo_solicitud
            summary["id_archivo_reprocesado"] = id_archivo
        return build_json_response(summary, status_code=200)
    except Exception as exc:
        logging.exception("Error procesando %s", route_name)
        message = str(exc)
        mark_processing_error(id_archivo, message)
        if id_archivo_solicitud is not None and id_archivo_solicitud != id_archivo:
            mark_processing_error(id_archivo_solicitud, message)
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
    """Orquestador para endpoints que solo transforman/leen y no escriben SQL."""
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


def handle_recalcular_cruce_notificaciones(
    req: func.HttpRequest,
    require_cedula: bool = False,
) -> func.HttpResponse:
    """Reejecuta reglas de cruce de notificaciones contra evidencia disponible."""
    logging.info("recalcular_cruce_notificaciones ejecutada")

    try:
        payload = get_optional_request_payload(req)
        cedula_raw = payload.get("cedula_normalizada") or payload.get("cedula")
        cedula_normalizada = normalize_document(cedula_raw)
        if cedula_raw not in (None, "") and cedula_normalizada is None:
            raise ValueError("cedula debe contener al menos un digito")
        if require_cedula and cedula_normalizada is None:
            raise ValueError("El payload debe incluir cedula o cedula_normalizada")
        solo_refrescar_resumen = parse_bool(
            payload,
            "solo_refrescar_resumen",
            False,
        )
        if solo_refrescar_resumen:
            if require_cedula:
                raise ValueError(
                    "solo_refrescar_resumen no aplica al recalculo exclusivo por cedula"
                )
            started_at = perf_counter()
            resumen = db.run_in_transaction(
                refrescar_resumen_validacion_radicado,
            )
            duracion_segundos = round(perf_counter() - started_at, 4)
            logging.info(
                "refrescar_resumen_validacion_radicado completado en %.4f segundos",
                duracion_segundos,
            )
            return build_json_response(
                {
                    "status": "OK",
                    "modo": "SOLO_REFRESCAR_RESUMEN",
                    "solo_refrescar_resumen": True,
                    "cruce_notificaciones": {
                        "resumen_validacion_radicado": resumen,
                        "timings_segundos": {
                            "refresh_resumen_validacion_radicado": duracion_segundos,
                            "total_recalculo": duracion_segundos,
                        },
                    },
                },
                status_code=200,
            )

        id_archivo_salas = parse_optional_int(payload, "id_archivo_salas")
        id_archivos_salas = parse_optional_positive_int_list(
            payload,
            "id_archivos_salas",
        )
        if id_archivo_salas is not None and id_archivo_salas <= 0:
            raise ValueError("id_archivo_salas debe ser mayor que cero")
        if id_archivo_salas is not None and id_archivos_salas is not None:
            raise ValueError(
                "Use id_archivo_salas o id_archivos_salas, pero no ambos"
            )
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
            batch_size is None
            and id_archivos_salas is None
            and cedula_normalizada is None,
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
                id_archivos_salas=id_archivos_salas,
                cedulas_objetivo=[cedula_normalizada]
                if cedula_normalizada
                else None,
            )
        )
        return build_json_response(
            {
                "status": "OK",
                "id_archivo_salas": id_archivo_salas,
                "id_archivos_salas": id_archivos_salas,
                "id_archivo_evidencia": id_archivo_evidencia,
                "cedula_normalizada": cedula_normalizada,
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


def handle_aplicar_revision_manual_notificaciones(req: func.HttpRequest) -> func.HttpResponse:
    """Aplica decisiones de revision manual sobre notificaciones pendientes."""
    logging.info("aplicar_revision_manual_notificaciones ejecutada")

    try:
        payload = get_optional_request_payload(req)
        id_archivo = parse_optional_int(payload, "id_archivo")
        batch_size = parse_optional_positive_int(payload, "batch_size")
        refrescar_resumen = parse_bool(payload, "refrescar_resumen", True)

        summary = db.run_in_transaction(
            lambda: aplicar_revision_manual_notificaciones(
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
                "revision_manual_notificaciones": summary,
                "revision_manual_guias": summary,
            },
            status_code=200,
        )
    except Exception as exc:
        logging.exception("Error aplicando revision manual de notificaciones")
        return build_json_response(
            {
                "status": "ERROR_PROCESAMIENTO",
                "errores": 1,
                "mensaje": str(exc),
            },
            status_code=500,
        )


# Endpoints de ingesta: reciben archivo en base64, procesan contenido y escriben tablas SQL.


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


@app.route(route="procesar_correo_certificado_pdf", methods=["POST"])
def procesar_correo_certificado_pdf(req: func.HttpRequest) -> func.HttpResponse:
    return handle_sql_processing(
        req,
        "procesar_correo_certificado_pdf",
        procesador_correo_pdf.process_payload_data,
        write_correo_pdf_result_to_sql,
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


@app.route(route="procesar_revision_manual_notificaciones", methods=["POST"])
def procesar_revision_manual_notificaciones(req: func.HttpRequest) -> func.HttpResponse:
    return handle_sql_processing(
        req,
        "procesar_revision_manual_notificaciones",
        procesador_revision_manual_notificaciones.process_payload_data,
        write_revision_manual_notificaciones_result_to_sql,
    )


@app.route(route="procesar_revision_manual_guias", methods=["POST"])
def procesar_revision_manual_guias_legacy(req: func.HttpRequest) -> func.HttpResponse:
    # Alias legacy: mantiene compatibilidad con consumidores que aun llaman "guias".
    return procesar_revision_manual_notificaciones(req)


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
    # Alias funcional del procesador de calificaciones del sistema JNC.
    return handle_sql_processing(
        req,
        "procesar_sistema_jnc",
        procesador_calificaciones.process_payload_data,
        write_calificaciones_result_to_sql,
    )


# Endpoints operativos: recalculan resultados derivados sin recibir un archivo nuevo.


@app.route(route="recalcular_cruce_notificaciones", methods=["POST"])
def recalcular_cruce_notificaciones_route(req: func.HttpRequest) -> func.HttpResponse:
    return handle_recalcular_cruce_notificaciones(req)


@app.route(route="recalcular_cruce_notificaciones_cedula", methods=["POST"])
def recalcular_cruce_notificaciones_cedula_route(
    req: func.HttpRequest,
) -> func.HttpResponse:
    return handle_recalcular_cruce_notificaciones(req, require_cedula=True)


@app.route(route="aplicar_revision_manual_notificaciones", methods=["POST"])
def aplicar_revision_manual_notificaciones_route(req: func.HttpRequest) -> func.HttpResponse:
    return handle_aplicar_revision_manual_notificaciones(req)


@app.route(route="aplicar_revision_manual_guias", methods=["POST"])
def aplicar_revision_manual_guias_legacy_route(req: func.HttpRequest) -> func.HttpResponse:
    # Alias legacy del endpoint actual de revision manual de notificaciones.
    return handle_aplicar_revision_manual_notificaciones(req)
