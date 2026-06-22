from datetime import date, datetime, timedelta
from typing import Any

from src.load import db
from src.load.prepare_sql_rows import (
    prepare_archivo_update_from_arls_result,
    prepare_arl_radicado_rows,
    prepare_error_rows,
    prepare_regla_rows,
)
from src.load.timing import timed_step
from src.reconcile.notificaciones import recalcular_cruce_notificaciones


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def write_arls_result_to_sql(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "status": "OK",
        "id_archivo": id_archivo,
        "arls_radicado_insertados": 0,
        "errores_insertados": 0,
        "reglas_insertadas": 0,
        "timings": {},
        "mensaje": "Resultado de radicados ARL PDF escrito en Azure SQL",
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
            "delete_notificacion_arl_radicado",
            lambda: db.delete_by_archivo("jnc.notificacion_arl_radicado", id_archivo),
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

        arl_rows = timed_step(
            timings,
            "prepare_notificacion_arl_radicado",
            lambda: prepare_arl_radicado_rows(id_archivo, result)
            if result.get("status") in {"OK", "OK_CON_ALERTAS"}
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
            lambda: prepare_regla_rows(id_archivo, result, "ARL_RADICADO_PDF"),
        )

        summary["arls_radicado_insertados"] = timed_step(
            timings,
            "insert_notificacion_arl_radicado",
            lambda: db.insert_many("jnc.notificacion_arl_radicado", arl_rows),
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
            lambda: prepare_archivo_update_from_arls_result(id_archivo, result),
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

        if result.get("status") != "OK":
            summary["status"] = result.get("status") or "ERROR"
            summary["mensaje"] = "Resultado de radicados ARL PDF escrito con alertas"

        if arl_rows:
            date_values = [
                parsed_date
                for row in arl_rows
                if (
                    parsed_date := _as_date(
                        row.get("fecha_recibo_comunicacion") or row.get("fecha_correo")
                    )
                )
            ]
            if date_values:
                min_date = min(date_values)
                max_date = max(date_values)
                summary["cruce_notificaciones"] = timed_step(
                    timings,
                    "recalcular_cruce_notificaciones_arl",
                    lambda: recalcular_cruce_notificaciones(
                        solo_pendientes=False,
                        fecha_referencia_desde=min_date - timedelta(days=30),
                        fecha_referencia_hasta=max_date,
                    ),
                )

        return summary

    return db.run_in_transaction(transaction)
