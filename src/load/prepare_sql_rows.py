from datetime import datetime, timezone
from typing import Any

from src.load.mappings import (
    AUDIENCIA_CASO_FIELD_MAP,
    CASO_FIELD_MAP,
    CORREO_CERTIFICADO_FIELD_MAP,
    CORREO_CERTIFICADO_JSON_FIELDS,
    ESTRUCTURA_ACTA_FIELD_MAP,
    ESTRUCTURA_ACTA_JSON_FIELDS,
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

GUIA_CORREO_FISICO_MAX_LENGTHS = {
    "hoja_origen": 255,
    "guia": 100,
    "estado": 255,
    "cuenta": 100,
    "servicio": 100,
    "regional_destino": 255,
    "ciudad_destino": 255,
    "nom_departamento": 255,
    "nombre_destinatario": 500,
    "direccion_destinatario": 1000,
    "numero_documento": 100,
    "dice_contener": 500,
    "tel_destinatario": 100,
    "nom_remitente": 500,
    "dir_remitente": 1000,
    "tel_remitente": 100,
    "cod_novedad": 100,
    "des_novedad": 500,
    "tipo_novedad": 255,
    "imputabilidad": 255,
    "cod_servicio": 100,
    "factura": 100,
    "ctro_costo": 100,
    "accion_notaguia": 500,
    "num_cliente": 100,
    "ced_destinatario": 100,
    "ced_destinatario_normalizada": 100,
    "regionalo": 255,
    "des_estadog": 255,
    "cartaporte": 100,
    "cubrimiento": 100,
    "hash_guia": 64,
}

GUIA_CORREO_FISICO_DATE_FIELDS = {
    "fec_captura",
    "fec_entrega",
    "fec_novedad",
    "fec_aproxentrega",
}

AUDIENCIA_CASO_MAX_LENGTHS = {
    "numero_acta": 100,
    "numero_acta_normalizado": 100,
    "sala": 255,
    "sala_normalizada": 50,
    "numero_radicado": 100,
    "numero_radicado_normalizado": 100,
    "nombre_paciente": 500,
    "nombre_paciente_normalizado": 500,
    "tipo_identificacion": 50,
    "numero_identificacion": 50,
    "numero_identificacion_normalizado": 50,
    "entidad_remitente": 500,
    "entidad_remitente_normalizado": 500,
    "medico_ponente": 500,
    "medico_ponente_normalizado": 500,
    "medico_principal": 500,
    "medico_principal_normalizado": 500,
    "terapeuta_psicologa": 500,
    "terapeuta_psicologa_normalizado": 500,
}

CASO_HASH_EXCLUDED_FIELDS = {
    "id_archivo",
    "tabla_caso_json",
    "hash_caso",
    "activo",
    "fecha_creacion",
    "fecha_actualizacion",
}

ESTRUCTURA_ACTA_HASH_EXCLUDED_FIELDS = {
    "id_archivo",
    "tabla_acta_json",
    "hash_estructura_acta",
    "fecha_creacion",
}

AUDIENCIA_CASO_HASH_EXCLUDED_FIELDS = {
    "id_archivo",
    "id_estructura_acta",
    "fila_caso_json",
    "hash_audiencia_caso",
    "fecha_creacion",
    "fecha_actualizacion",
    "activo",
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


def truncate_text_fields(row: dict[str, Any], max_lengths: dict[str, int]) -> dict[str, Any]:
    return {
        key: value[: max_lengths[key]]
        if key in max_lengths and isinstance(value, str)
        else value
        for key, value in row.items()
    }


def _prepare_archivo_identity_update(result: dict[str, Any]) -> dict[str, Any]:
    update: dict[str, Any] = {}
    nombre_archivo = result.get("nombre_archivo")
    if nombre_archivo:
        update["nombre_archivo"] = str(nombre_archivo)

    extension_archivo = result.get("extension_archivo")
    if not extension_archivo and nombre_archivo and "." in str(nombre_archivo):
        extension_archivo = "." + str(nombre_archivo).rsplit(".", 1)[1]
    if extension_archivo:
        update["extension_archivo"] = str(extension_archivo)

    for field_name in ("tipo_archivo", "ruta_sharepoint", "carpeta_origen", "carpeta_destino"):
        value = result.get(field_name)
        if value:
            update[field_name] = str(value)

    return update


def prepare_archivo_update_from_salas_result(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    hojas = result.get("hojas_con_fecha") or []
    mensaje_error = result.get("mensaje_error") or []
    hojas_validas = sum(1 for hoja in hojas if hoja.get("estructura_valida"))

    return {
        "id_archivo": id_archivo,
        **_prepare_archivo_identity_update(result),
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
        **_prepare_archivo_identity_update(result),
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


def prepare_archivo_update_from_audiencias_result(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    total_actas = result.get("total_actas_audiencia_pdf") or len(
        result.get("tabla_estructura_acta") or result.get("tabla_actas_audiencia_pdf") or []
    )
    total_casos = result.get("total_casos_acta") or len(
        result.get("tabla_audiencia_caso") or result.get("tabla_acta_audiencia_casos") or []
    )

    return {
        "id_archivo": id_archivo,
        **_prepare_archivo_identity_update(result),
        "procesador_status": result.get("status"),
        "tamano_bytes": result.get("tamano_bytes"),
        "total_actas_audiencia_pdf": total_actas,
        "casos_detectados": total_casos,
        "estado_proceso": "PROCESADO"
        if result.get("status") == "OK"
        else "ERROR_PROCESAMIENTO",
        "fecha_fin_proceso": utc_now_iso(),
    }


def prepare_archivo_update_from_guias_result(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    total_rows = result.get("total_filas_guias_correo_fisico") or len(
        result.get("tabla_guias_correo_fisico") or []
    )

    return {
        "id_archivo": id_archivo,
        **_prepare_archivo_identity_update(result),
        "procesador_status": result.get("status"),
        "tamano_bytes": result.get("tamano_bytes"),
        "total_filas_guias_correo_fisico": total_rows,
        "encabezados_originales_json": json_dumps_safe(
            [
                header
                for hoja in result.get("hojas") or []
                for header in hoja.get("encabezados_originales") or []
            ]
        ),
        "encabezados_normalizados_json": json_dumps_safe(
            [
                header
                for hoja in result.get("hojas") or []
                for header in hoja.get("encabezados_normalizados") or []
            ]
        ),
        "mensaje_error": json_dumps_safe(result.get("estructura"))
        if result.get("status") != "OK"
        else None,
        "estado_proceso": "PROCESADO"
        if result.get("status") == "OK"
        else "ERROR_ESTRUCTURA",
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
        mapped_row["origen_tabla"] = source_row.get("origen_tabla") or "tabla_casos"
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
        mapped_row["origen_tabla"] = source_row.get("origen_tabla") or "tabla_notificaciones"
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


def prepare_estructura_acta_rows(
    id_archivo: int,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []

    for source_row in (
        result.get("tabla_estructura_acta") or result.get("tabla_actas_audiencia_pdf") or []
    ):
        mapped_row = map_fields(source_row, ESTRUCTURA_ACTA_FIELD_MAP)

        for field_name in ESTRUCTURA_ACTA_JSON_FIELDS:
            mapped_row[field_name] = json_dumps_safe(mapped_row.get(field_name))

        mapped_row["id_archivo"] = id_archivo
        mapped_row["fecha_audiencia"] = normalize_date(mapped_row.get("fecha_audiencia"))
        mapped_row["tabla_acta_json"] = json_dumps_safe(source_row)
        mapped_row["fecha_creacion"] = utc_now_iso()

        hash_payload = business_hash_payload(
            mapped_row,
            ESTRUCTURA_ACTA_HASH_EXCLUDED_FIELDS,
        )
        mapped_row["hash_estructura_acta"] = sha256_dict(hash_payload)
        rows.append(mapped_row)

    return rows


def prepare_audiencia_caso_rows(
    id_archivo: int,
    result: dict[str, Any],
    estructura_id_by_key: dict[tuple[Any, ...], int] | None = None,
) -> list[dict[str, Any]]:
    estructura_rows = (
        result.get("tabla_estructura_acta") or result.get("tabla_actas_audiencia_pdf") or []
    )
    case_rows = result.get("tabla_audiencia_caso") or []
    if not case_rows and estructura_rows:
        from procesador_audiencias import build_audiencia_case_rows

        case_rows = build_audiencia_case_rows(estructura_rows[0])

    parent = estructura_rows[0] if estructura_rows else {}
    rows = []

    for source_row in case_rows:
        mapped_row = map_fields(source_row, AUDIENCIA_CASO_FIELD_MAP)
        mapped_row["id_archivo"] = id_archivo
        mapped_row["numero_acta"] = mapped_row.get("numero_acta") or parent.get("numero_acta")
        mapped_row["numero_acta_normalizado"] = (
            mapped_row.get("numero_acta_normalizado")
            or parent.get("numero_acta_normalizado")
        )
        mapped_row["fecha_audiencia"] = normalize_date(
            mapped_row.get("fecha_audiencia") or parent.get("fecha_audiencia")
        )
        mapped_row["sala"] = mapped_row.get("sala") or parent.get("sala")
        mapped_row["sala_normalizada"] = mapped_row.get("sala_normalizada") or parent.get(
            "sala_normalizada"
        )
        mapped_row["numero_radicado_normalizado"] = normalize_radicado(
            mapped_row.get("numero_radicado")
        )
        mapped_row["nombre_paciente_normalizado"] = normalize_db_string(
            mapped_row.get("nombre_paciente")
        )
        mapped_row["numero_identificacion_normalizado"] = normalize_document(
            mapped_row.get("numero_identificacion")
        )
        mapped_row["entidad_remitente_normalizado"] = normalize_db_string(
            mapped_row.get("entidad_remitente")
        )
        mapped_row["medico_ponente_normalizado"] = normalize_db_string(
            mapped_row.get("medico_ponente")
        )
        mapped_row["medico_principal_normalizado"] = normalize_db_string(
            mapped_row.get("medico_principal")
        )
        mapped_row["terapeuta_psicologa_normalizado"] = normalize_db_string(
            mapped_row.get("terapeuta_psicologa")
        )
        mapped_row["fila_caso_json"] = json_dumps_safe(source_row)
        mapped_row["activo"] = 1
        mapped_row["fecha_creacion"] = utc_now_iso()

        if estructura_id_by_key:
            key = (
                mapped_row.get("id_archivo"),
                mapped_row.get("numero_acta_normalizado"),
                mapped_row.get("fecha_audiencia"),
                mapped_row.get("sala_normalizada"),
            )
            mapped_row["id_estructura_acta"] = estructura_id_by_key.get(key)

        mapped_row = truncate_text_fields(mapped_row, AUDIENCIA_CASO_MAX_LENGTHS)
        hash_payload = business_hash_payload(
            mapped_row,
            AUDIENCIA_CASO_HASH_EXCLUDED_FIELDS,
        )
        mapped_row["hash_audiencia_caso"] = sha256_dict(hash_payload)
        rows.append(mapped_row)

    return rows


def prepare_guia_correo_fisico_rows(
    id_archivo: int,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []

    for source_row in result.get("tabla_guias_correo_fisico") or []:
        mapped_row = dict(source_row)
        mapped_row["id_archivo"] = id_archivo
        for field_name in GUIA_CORREO_FISICO_DATE_FIELDS:
            if field_name in mapped_row:
                mapped_row[field_name] = normalize_date(mapped_row.get(field_name))
        numero_documento = normalize_document(mapped_row.get("numero_documento"))
        cedula_destinatario = normalize_document(mapped_row.get("ced_destinatario"))
        if numero_documento == "0":
            numero_documento = None
        if cedula_destinatario == "0":
            cedula_destinatario = None
        mapped_row["ced_destinatario_normalizada"] = (
            numero_documento
            or cedula_destinatario
        )
        mapped_row["fila_guia_json"] = json_dumps_safe(source_row)
        mapped_row["fecha_creacion"] = utc_now_iso()

        hash_payload = {
            key: value
            for key, value in mapped_row.items()
            if key not in {
                "id_archivo",
                "fila_guia_json",
                "hash_guia",
                "fecha_creacion",
                "fecha_actualizacion",
            }
        }
        mapped_row["hash_guia"] = sha256_dict(hash_payload)
        mapped_row = truncate_text_fields(mapped_row, GUIA_CORREO_FISICO_MAX_LENGTHS)
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

    if result.get("status") != "OK" and result.get("estructura"):
        rows.append(
            {
                "id_archivo": id_archivo,
                "etapa": "VALIDACION_ESTRUCTURA",
                "tipo_error": "estructura_invalida",
                "detalle_error": result["estructura"].get("mensaje")
                or json_dumps_safe(result["estructura"]),
                "hoja_origen": None,
                "severidad": "ERROR",
                "requiere_revision": 1,
                "fecha_error": utc_now_iso(),
                "detalle_error_json": json_dumps_safe(result["estructura"]),
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

    if source_key == "ACTA_AUDIENCIA_PDF":
        actas = result.get("tabla_estructura_acta") or result.get("tabla_actas_audiencia_pdf") or []
        casos = result.get("tabla_audiencia_caso") or result.get("tabla_acta_audiencia_casos") or []

        return [
            _regla_row(
                id_archivo,
                "LEER_PDF_ACTA_AUDIENCIA",
                "LECTURA",
                len(actas),
                len(actas),
                status,
                "Extraccion de texto y metadatos desde PDF de acta de audiencia",
            ),
            _regla_row(
                id_archivo,
                "GENERAR_TABLA_ACTA_AUDIENCIA_PDF",
                "TRANSFORMACION",
                len(actas),
                len(actas),
                status,
                "Preparacion de actas de audiencia PDF",
            ),
            _regla_row(
                id_archivo,
                "GENERAR_TABLA_CASOS_ACTA_AUDIENCIA",
                "TRANSFORMACION",
                len(casos),
                len(casos),
                status,
                "Preparacion de casos detectados en acta de audiencia",
            ),
        ]

    if source_key == "GUIAS_CORREO_FISICO":
        rows = result.get("tabla_guias_correo_fisico") or []
        hojas = result.get("hojas") or []

        return [
            _regla_row(
                id_archivo,
                "LEER_XLS_GUIAS_CORREO_FISICO",
                "LECTURA",
                len(hojas),
                len(hojas),
                status,
                "Lectura de archivo XLS de guias de correo fisico",
            ),
            _regla_row(
                id_archivo,
                "GENERAR_TABLA_GUIAS_CORREO_FISICO",
                "TRANSFORMACION",
                len(rows),
                len(rows),
                status,
                "Preparacion de guias de correo fisico",
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


def prepare_all_from_audiencias_result(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "jnc.etl_archivo_cargado": prepare_archivo_update_from_audiencias_result(
            id_archivo,
            result,
        ),
        "jnc.etl_estructura_acta": prepare_estructura_acta_rows(id_archivo, result),
        "jnc.audiencia_caso": prepare_audiencia_caso_rows(id_archivo, result),
        "jnc.etl_error_procesamiento": prepare_error_rows(id_archivo, result),
        "jnc.etl_ejecucion_regla": prepare_regla_rows(
            id_archivo,
            result,
            "ACTA_AUDIENCIA_PDF",
        ),
    }


def prepare_all_from_guias_result(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "jnc.etl_archivo_cargado": prepare_archivo_update_from_guias_result(
            id_archivo,
            result,
        ),
        "jnc.guia_correo_fisico": prepare_guia_correo_fisico_rows(id_archivo, result),
        "jnc.etl_error_procesamiento": prepare_error_rows(id_archivo, result),
        "jnc.etl_ejecucion_regla": prepare_regla_rows(
            id_archivo,
            result,
            "GUIAS_CORREO_FISICO",
        ),
    }
