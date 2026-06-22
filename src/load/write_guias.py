from datetime import timedelta
from typing import Any

from src.load import db
from src.load.prepare_sql_rows import (
    prepare_archivo_update_from_guias_result,
    prepare_error_rows,
    prepare_guia_correo_fisico_rows,
    prepare_regla_rows,
)
from src.load.timing import timed_step
from src.reconcile.notificaciones import recalcular_cruce_notificaciones
from src.utils.normalization import normalize_date


def _affected_reference_window(
    rows: list[dict[str, Any]],
    date_fields: tuple[str, ...],
    margin_days: int,
) -> tuple[Any, Any] | None:
    dates = []
    for row in rows:
        for field_name in date_fields:
            value = normalize_date(row.get(field_name))
            if value is not None:
                dates.append(value)
    if not dates:
        return None

    return min(dates) - timedelta(days=margin_days), max(dates) + timedelta(days=margin_days)


def write_guias_result_to_sql(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "status": "OK",
        "id_archivo": id_archivo,
        "guias_insertadas": 0,
        "errores_insertados": 0,
        "reglas_insertadas": 0,
        "cruce_notificaciones": {},
        "timings": {},
        "mensaje": "Resultado de guias de correo fisico escrito en Azure SQL",
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
            "delete_guia_correo_fisico",
            lambda: db.delete_by_archivo("jnc.guia_correo_fisico", id_archivo),
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

        guia_rows = timed_step(
            timings,
            "prepare_guia_correo_fisico",
            lambda: prepare_guia_correo_fisico_rows(id_archivo, result)
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
            lambda: prepare_regla_rows(id_archivo, result, "GUIAS_CORREO_FISICO"),
        )

        summary["guias_insertadas"] = timed_step(
            timings,
            "insert_guia_correo_fisico",
            lambda: db.insert_many(
                "jnc.guia_correo_fisico",
                guia_rows,
                fast_executemany=False,
            ),
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
            lambda: prepare_archivo_update_from_guias_result(id_archivo, result),
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

        if result.get("status") == "OK":
            affected_window = _affected_reference_window(
                guia_rows,
                ("fec_entrega", "fecha_entrega"),
                30,
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
                    "motivo": "No se detectaron fechas de entrega en las guias cargadas",
                }

        if result.get("status") != "OK":
            summary["status"] = "ERROR"
            summary["mensaje"] = "Resultado de guias de correo fisico escrito con errores"

        return summary

    return db.run_in_transaction(transaction)
