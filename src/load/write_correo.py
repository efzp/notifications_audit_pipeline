from datetime import date, datetime, timedelta
from typing import Any

from src.load import db
from src.load.prepare_sql_rows import (
    prepare_archivo_update_from_correo_result,
    prepare_correo_certificado_rows,
    prepare_error_rows,
    prepare_regla_rows,
)
from src.load.timing import timed_step
from src.reconcile.notificaciones import recalcular_cruce_notificaciones
from src.utils.normalization import normalize_date


CORREO_INSERT_BATCH_SIZE = 5000


def _as_date(value: Any) -> date | None:
    normalized = normalize_date(value)
    if normalized is None:
        return None
    if isinstance(normalized, date):
        return normalized
    try:
        return datetime.fromisoformat(str(normalized)).date()
    except ValueError:
        return None


def _affected_reference_window(
    rows: list[dict[str, Any]],
    date_fields: tuple[str, ...],
    margin_days: int,
) -> tuple[date, date] | None:
    dates = []
    for row in rows:
        for field_name in date_fields:
            value = _as_date(row.get(field_name))
            if value is not None:
                dates.append(value)
    if not dates:
        return None

    return min(dates) - timedelta(days=margin_days), max(dates) + timedelta(days=margin_days)


def write_correo_result_to_sql(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    recalcular_cruce = bool(result.get("_recalcular_cruce", True))
    summary = {
        "status": "OK",
        "id_archivo": id_archivo,
        "filas_leidas": int(result.get("total_filas_correo_certificado") or 0),
        "filas_corregidas": int(
            result.get("filas_corregidas_correo_certificado") or 0
        ),
        "filas_rechazadas": int(
            result.get("filas_rechazadas_correo_certificado") or 0
        ),
        "correos_insertados": 0,
        "errores_insertados": 0,
        "reglas_insertadas": 0,
        "cruce_notificaciones": {},
        "timings": {},
        "mensaje": "Resultado de correo certificado escrito en Azure SQL",
    }

    def transaction():
        timings = summary["timings"]

        timed_step(
            timings,
            "update_archivo_en_proceso",
            lambda: db.execute_update(
                "jnc.etl_archivo_cargado",
                "id_archivo",
                id_archivo,
                {"estado_proceso": "EN_PROCESO"},
            ),
        )

        timed_step(
            timings,
            "delete_notificacion_correo_certificado",
            lambda: db.delete_by_archivo("jnc.notificacion_correo_certificado", id_archivo),
        )
        timed_step(
            timings,
            "delete_etl_error_procesamiento",
            lambda: db.delete_by_archivo("jnc.etl_error_procesamiento", id_archivo),
        )
        timed_step(
            timings,
            "delete_etl_ejecucion_regla",
            lambda: db.delete_by_archivo("jnc.etl_ejecucion_regla", id_archivo),
        )

        correo_rows = timed_step(
            timings,
            "prepare_notificacion_correo_certificado",
            lambda: prepare_correo_certificado_rows(id_archivo, result)
            if result.get("status") == "OK"
            else [],
        )
        error_rows = timed_step(
            timings,
            "prepare_error_rows",
            lambda: prepare_error_rows(id_archivo, result),
        )
        regla_rows = timed_step(
            timings,
            "prepare_regla_rows",
            lambda: prepare_regla_rows(id_archivo, result, "CORREO_CERTIFICADO"),
        )

        summary["correos_insertados"] = timed_step(
            timings,
            "insert_notificacion_correo_certificado",
            lambda: db.insert_many(
                "jnc.notificacion_correo_certificado",
                correo_rows,
                fast_executemany=True,
                batch_size=CORREO_INSERT_BATCH_SIZE,
            ),
        )
        if result.get("tipo_archivo") in {
            "CORREO_CERTIFICADO_PDF",
            "PDF_CORREO_CERTIFICADO",
        }:
            if len(correo_rows) != 1 or summary["correos_insertados"] != 1:
                raise ValueError(
                    "Cada PDF de correo certificado debe producir exactamente una fila"
                )
            table_columns = db.get_table_columns(
                "jnc.notificacion_correo_certificado"
            )
            result_columns = [
                column
                for column in (
                    "id_notificacion_correo",
                    "estado_correo",
                    "codigo_certificado",
                    "nombre_archivo",
                )
                if column in table_columns
            ]
            inserted_rows = db.fetch_rows(
                "jnc.notificacion_correo_certificado",
                result_columns,
                "[id_archivo] = ?",
                [id_archivo],
            )
            if len(inserted_rows) != 1:
                raise ValueError(
                    "No fue posible identificar de forma unica la fila insertada por el PDF"
                )
            inserted_row = inserted_rows[0]
            summary.update(
                {
                    "id_notificacion_correo": inserted_row.get(
                        "id_notificacion_correo"
                    ),
                    "cedula_detectada": result.get("cedula_detectada"),
                    "cedula_normalizada": result.get("cedula_normalizada"),
                    "tipo_destinatario_detectado": result.get(
                        "tipo_destinatario_detectado"
                    ),
                    "estado_correo": inserted_row.get("estado_correo"),
                    "codigo_certificado": inserted_row.get(
                        "codigo_certificado"
                    ),
                    "nombre_archivo": inserted_row.get("nombre_archivo")
                    or result.get("nombre_archivo"),
                }
            )
        summary["errores_insertados"] = timed_step(
            timings,
            "insert_etl_error_procesamiento",
            lambda: db.insert_many("jnc.etl_error_procesamiento", error_rows),
        )
        summary["reglas_insertadas"] = timed_step(
            timings,
            "insert_etl_ejecucion_regla",
            lambda: db.insert_many("jnc.etl_ejecucion_regla", regla_rows),
        )

        archivo_update = timed_step(
            timings,
            "prepare_archivo_update",
            lambda: prepare_archivo_update_from_correo_result(id_archivo, result),
        )
        archivo_update.pop("id_archivo", None)
        timed_step(
            timings,
            "update_archivo_final",
            lambda: db.execute_update(
                "jnc.etl_archivo_cargado",
                "id_archivo",
                id_archivo,
                archivo_update,
            ),
        )

        if result.get("status") == "OK" and recalcular_cruce:
            affected_window = _affected_reference_window(
                correo_rows,
                ("fecha", "fecha_2", "fecha_3"),
                7,
            )
            if affected_window:
                summary["cruce_notificaciones"] = timed_step(
                    timings,
                    "recalcular_cruce_notificaciones",
                    lambda: recalcular_cruce_notificaciones(
                        id_archivo_salas=None,
                        solo_pendientes=False,
                        fecha_referencia_desde=affected_window[0],
                        fecha_referencia_hasta=affected_window[1],
                    ),
                )
            else:
                summary["cruce_notificaciones"] = {
                    "omitido": True,
                    "motivo": "No se detectaron fechas en el correo certificado cargado",
                }
        elif result.get("status") == "OK":
            summary["cruce_notificaciones"] = {
                "omitido": True,
                "motivo": "Recalculo omitido por solicitud",
            }

        if result.get("status") != "OK":
            summary["status"] = "ERROR"
            summary["mensaje"] = "Resultado de correo certificado escrito con errores"

        return summary

    return db.run_in_transaction(transaction)


def write_correo_pdf_result_to_sql(
    id_archivo: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Persiste un PDF sin ejecutar el cruce en la misma llamada."""
    pdf_result = dict(result)
    pdf_result["_recalcular_cruce"] = False
    return write_correo_result_to_sql(id_archivo, pdf_result)
