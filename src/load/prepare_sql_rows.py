from datetime import datetime, timezone
from typing import Any

from src.load.mappings import (
    CASO_FIELD_MAP,
    CORREO_CERTIFICADO_FIELD_MAP,
    CORREO_CERTIFICADO_JSON_FIELDS,
    ESTRUCTURA_HOJA_FIELD_MAP,
    ESTRUCTURA_HOJA_JSON_FIELDS,
    NOTIFICACION_FIELD_MAP,
)
from src.utils.normalization import (
    clean_text,
    json_dumps_safe,
    normalize_date,
    normalize_db_string,
    normalize_document,
    normalize_email,
    normalize_radicado,
    sha256_dict,
)


SCRIPT_VERSION = "1.0"

CASO_HASH_EXCLUDED_FIELDS = {
    "id_archivo",
    "tabla_caso_json",
    "hash_caso",
    "activo",
    "fecha_creacion",
    "fecha_actualizacion",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def map_fields(row: dict[str, Any], field_map: dict[str, str]) -> dict[str, Any]:
    return {
        target_field: row.get(source_field)
        for source_field, target_field in field_map.items()
    }


def business_hash_payload(
    row: dict[str, Any],
    excluded_fields: set[str],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in excluded_fields
    }


def prepare_archivo_update_from_salas_result(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    hojas = result.get("hojas_con_fecha") or []
    mensaje_error = result.get("mensaje_error") or []
    hojas_validas = sum(1 for hoja in hojas if hoja.get("estructura_valida"))

    return {
        "id_archivo": id_archivo,
        "procesador_status": result.get("status"),
        "tamano_bytes": result.get("tamano_bytes"),
        "entradas_xlsx": result.get("entradas_xlsx"),
        "estructura_valida": 1 if result.get("status") == "OK" else 0,
        "hojas_detectadas": len(hojas),
        "hojas_validas": hojas_validas,
        "casos_detectados": len(result.get("tabla_casos") or []),
        "notificaciones_detectadas": len(result.get("tabla_notificaciones") or []),
        "diccionario_estandar_columnas_json": json_dumps_safe(
            result.get("diccionario_estandar_columnas")
        ),
        "mensaje_error": json_dumps_safe(mensaje_error) if mensaje_error else None,
        "estado_proceso": "PROCESADO" if result.get("status") == "OK" else "ERROR_ESTRUCTURA",
        "fecha_fin_proceso": utc_now_iso(),
    }


def prepare_archivo_update_from_correo_result(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    total_rows = result.get("total_filas_correo_certificado") or len(
        result.get("tabla_correo_certificado") or []
    )

    return {
        "id_archivo": id_archivo,
        "procesador_status": result.get("status"),
        "tamano_bytes": result.get("tamano_bytes"),
        "delimitador_csv": result.get("delimitador_csv"),
        "encabezados_originales_json": json_dumps_safe(result.get("encabezados_originales")),
        "encabezados_normalizados_json": json_dumps_safe(result.get("encabezados_normalizados")),
        "total_filas_correo_certificado": total_rows,
        "notificaciones_detectadas": total_rows,
        "estado_proceso": "PROCESADO"
        if result.get("status") == "OK"
        else "ERROR_PROCESAMIENTO",
        "fecha_fin_proceso": utc_now_iso(),
    }


def prepare_estructura_hoja_rows(id_archivo: int, result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []

    for source_row in result.get("hojas_con_fecha") or []:
        mapped_row = map_fields(source_row, ESTRUCTURA_HOJA_FIELD_MAP)

        for field_name in ESTRUCTURA_HOJA_JSON_FIELDS:
            mapped_row[field_name] = json_dumps_safe(mapped_row.get(field_name))

        mapped_row["id_archivo"] = id_archivo
        mapped_row["fecha_creacion"] = utc_now_iso()
        rows.append(mapped_row)

    return rows


def prepare_caso_rows(id_archivo: int, result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    seen_hashes = set()

    for source_row in result.get("tabla_casos") or []:
        mapped_row = map_fields(source_row, CASO_FIELD_MAP)
        mapped_row["id_archivo"] = id_archivo
        mapped_row["numero_radicado_normalizado"] = normalize_radicado(
            mapped_row.get("numero_radicado")
        )
        mapped_row["cedula_normalizada"] = normalize_document(mapped_row.get("cedula"))
        mapped_row["nombre_paciente_normalizado"] = normalize_db_string(
            mapped_row.get("nombre_paciente")
        )
        mapped_row["pestana_fecha"] = normalize_date(mapped_row.get("pestana_fecha"))
        mapped_row["hoja_trabajo_fecha_audiencia"] = normalize_date(
            mapped_row.get("hoja_trabajo_fecha_audiencia")
        )
        mapped_row["fecha_pago_dictamen"] = normalize_date(mapped_row.get("fecha_pago_dictamen"))
        mapped_row["tabla_caso_json"] = json_dumps_safe(source_row)
        mapped_row["origen_tabla"] = "tabla_casos"
        mapped_row["activo"] = 1
        mapped_row["fecha_creacion"] = utc_now_iso()

        hash_payload = business_hash_payload(mapped_row, CASO_HASH_EXCLUDED_FIELDS)
        mapped_row["hash_caso"] = sha256_dict(hash_payload)
        if mapped_row["hash_caso"] in seen_hashes:
            continue

        seen_hashes.add(mapped_row["hash_caso"])
        rows.append(mapped_row)

    return rows


def prepare_notificacion_rows(
    id_archivo: int,
    result: dict[str, Any],
    caso_id_by_radicado: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    rows = []

    for source_row in result.get("tabla_notificaciones") or []:
        mapped_row = map_fields(source_row, NOTIFICACION_FIELD_MAP)
        mapped_row["id_archivo"] = id_archivo

        tipo_destinatario = clean_text(mapped_row.get("tipo_destinatario"))
        mapped_row["tipo_destinatario"] = tipo_destinatario.upper() if tipo_destinatario else None
        mapped_row["numero_radicado_normalizado"] = normalize_radicado(
            mapped_row.get("numero_radicado")
        )
        mapped_row["cedula_normalizada"] = normalize_document(mapped_row.get("cedula"))
        mapped_row["fecha_envio_reportada"] = normalize_date(
            mapped_row.get("fecha_envio_reportada")
        )
        mapped_row["fecha_recibido_reportada"] = normalize_date(
            mapped_row.get("fecha_recibido_reportada")
        )
        mapped_row["pestana_fecha"] = normalize_date(mapped_row.get("pestana_fecha"))
        mapped_row["hoja_trabajo_fecha_audiencia"] = normalize_date(
            mapped_row.get("hoja_trabajo_fecha_audiencia")
        )
        correo_o_guia = clean_text(mapped_row.get("correo_o_guia_reportado"))
        mapped_row["correo_normalizado"] = (
            normalize_email(correo_o_guia) if correo_o_guia and "@" in correo_o_guia else None
        )

        if caso_id_by_radicado:
            mapped_row["id_caso"] = caso_id_by_radicado.get(
                mapped_row["numero_radicado_normalizado"]
            )

        mapped_row["tabla_notificacion_json"] = json_dumps_safe(source_row)
        mapped_row["origen_tabla"] = "tabla_notificaciones"
        mapped_row["activo"] = 1
        mapped_row["fecha_creacion"] = utc_now_iso()

        hash_payload = {
            key: value
            for key, value in mapped_row.items()
            if key not in {"tabla_notificacion_json", "hash_notificacion_esperada"}
        }
        mapped_row["hash_notificacion_esperada"] = sha256_dict(hash_payload)
        rows.append(mapped_row)

    return rows


def prepare_correo_certificado_rows(
    id_archivo: int,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []

    for source_row in result.get("tabla_correo_certificado") or []:
        mapped_row = map_fields(source_row, CORREO_CERTIFICADO_FIELD_MAP)

        for field_name in CORREO_CERTIFICADO_JSON_FIELDS:
            mapped_row[field_name] = json_dumps_safe(mapped_row.get(field_name))

        mapped_row["id_archivo"] = id_archivo
        mapped_row["fecha"] = normalize_date(mapped_row.get("fecha"))
        mapped_row["fecha_2"] = normalize_date(mapped_row.get("fecha_2"))
        mapped_row["fecha_3"] = normalize_date(mapped_row.get("fecha_3"))
        mapped_row["destinatario_email_normalizado"] = normalize_email(
            source_row.get("correo")
        )
        mapped_row["destinatario_nombre_normalizado"] = normalize_db_string(
            source_row.get("nombres")
        )
        mapped_row["nombres"] = source_row.get("nombres")
        mapped_row["correo"] = source_row.get("correo")
        mapped_row["asunto_normalizado"] = normalize_db_string(source_row.get("asunto"))
        mapped_row["fila_correo_certificado_json"] = json_dumps_safe(source_row)
        mapped_row["fecha_creacion"] = utc_now_iso()

        hash_payload = {
            key: value
            for key, value in mapped_row.items()
            if key not in {"fila_correo_certificado_json", "hash_correo"}
        }
        mapped_row["hash_correo"] = sha256_dict(hash_payload)
        rows.append(mapped_row)

    return rows


def prepare_error_rows(id_archivo: int, result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []

    for error in result.get("mensaje_error") or []:
        rows.append(
            {
                "id_archivo": id_archivo,
                "etapa": "VALIDACION_ESTRUCTURA",
                "tipo_error": error.get("tipo_error"),
                "detalle_error": error.get("mensaje") or json_dumps_safe(error),
                "hoja_origen": error.get("pestana"),
                "severidad": "ERROR",
                "requiere_revision": 1,
                "fecha_error": utc_now_iso(),
                "detalle_error_json": json_dumps_safe(error),
            }
        )

    return rows


def _regla_row(
    id_archivo: int,
    nombre_regla: str,
    tipo_regla: str,
    registros_evaluados: int,
    registros_afectados: int,
    resultado: str,
    observacion: str | None = None,
) -> dict[str, Any]:
    return {
        "id_archivo": id_archivo,
        "nombre_regla": nombre_regla,
        "tipo_regla": tipo_regla,
        "version_script": SCRIPT_VERSION,
        "registros_evaluados": registros_evaluados,
        "registros_afectados": registros_afectados,
        "resultado": resultado,
        "observacion": observacion,
        "fecha_ejecucion": utc_now_iso(),
    }


def prepare_regla_rows(id_archivo: int, result: dict[str, Any], source: str) -> list[dict[str, Any]]:
    source_key = source.upper()
    status = "OK" if result.get("status") == "OK" else "ERROR"

    if source_key == "SALAS":
        hojas = result.get("hojas_con_fecha") or []
        casos = result.get("tabla_casos") or []
        notificaciones = result.get("tabla_notificaciones") or []
        hojas_validas = sum(1 for hoja in hojas if hoja.get("estructura_valida"))

        return [
            _regla_row(
                id_archivo,
                "VALIDAR_ESTRUCTURA_HOJAS",
                "VALIDACION",
                len(hojas),
                hojas_validas,
                status,
                "Validacion de estructura de hojas de salas",
            ),
            _regla_row(
                id_archivo,
                "GENERAR_TABLA_CASOS",
                "TRANSFORMACION",
                len(casos),
                len(casos),
                status,
                "Preparacion de casos calificados",
            ),
            _regla_row(
                id_archivo,
                "GENERAR_TABLA_NOTIFICACIONES",
                "TRANSFORMACION",
                len(notificaciones),
                len(notificaciones),
                status,
                "Preparacion de notificaciones esperadas",
            ),
        ]

    if source_key == "CORREO_CERTIFICADO":
        correos = result.get("tabla_correo_certificado") or []
        total_rows = result.get("total_filas_correo_certificado") or len(correos)

        return [
            _regla_row(
                id_archivo,
                "LEER_CSV_CORREO_CERTIFICADO",
                "LECTURA",
                total_rows,
                total_rows,
                status,
                "Lectura de reporte CSV de correo certificado",
            ),
            _regla_row(
                id_archivo,
                "GENERAR_TABLA_CORREO_CERTIFICADO",
                "TRANSFORMACION",
                len(correos),
                len(correos),
                status,
                "Preparacion de notificaciones de correo certificado",
            ),
        ]

    raise ValueError(f"source no soportado: {source}")


def prepare_all_from_salas_result(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "jnc.etl_archivo_cargado": prepare_archivo_update_from_salas_result(
            id_archivo,
            result,
        ),
        "jnc.etl_estructura_hoja": prepare_estructura_hoja_rows(id_archivo, result),
        "jnc.caso_calificado": prepare_caso_rows(id_archivo, result),
        "jnc.notificacion_esperada": prepare_notificacion_rows(id_archivo, result),
        "jnc.etl_error_procesamiento": prepare_error_rows(id_archivo, result),
        "jnc.etl_ejecucion_regla": prepare_regla_rows(id_archivo, result, "SALAS"),
    }


def prepare_all_from_correo_result(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "jnc.etl_archivo_cargado": prepare_archivo_update_from_correo_result(
            id_archivo,
            result,
        ),
        "jnc.notificacion_correo_certificado": prepare_correo_certificado_rows(
            id_archivo,
            result,
        ),
        "jnc.etl_error_procesamiento": prepare_error_rows(id_archivo, result),
        "jnc.etl_ejecucion_regla": prepare_regla_rows(
            id_archivo,
            result,
            "CORREO_CERTIFICADO",
        ),
    }
