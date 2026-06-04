from typing import Any

from src.load import db
from src.load.prepare_sql_rows import (
    prepare_archivo_update_from_audiencias_result,
    prepare_audiencia_caso_rows,
    prepare_error_rows,
    prepare_estructura_acta_rows,
    prepare_regla_rows,
)
from src.load.timing import timed_step


def _estructura_acta_key(row: dict[str, Any]) -> tuple[Any, ...]:
    fecha = row.get("fecha_audiencia")
    if hasattr(fecha, "isoformat"):
        fecha = fecha.isoformat()

    return (
        row.get("id_archivo"),
        row.get("numero_acta_normalizado"),
        fecha,
        row.get("sala_normalizada"),
    )


def write_audiencias_result_to_sql(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "status": "OK",
        "id_archivo": id_archivo,
        "estructuras_acta_insertadas": 0,
        "casos_acta_insertados": 0,
        "errores_insertados": 0,
        "reglas_insertadas": 0,
        "timings": {},
        "mensaje": "Resultado de actas de audiencia PDF escrito en Azure SQL",
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
            "delete_audiencia_caso",
            lambda: db.delete_by_archivo("jnc.audiencia_caso", id_archivo),
        )
        timed_step(
            timings,
            "delete_etl_estructura_acta",
            lambda: db.delete_by_archivo("jnc.etl_estructura_acta", id_archivo),
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

        estructura_rows = timed_step(
            timings,
            "prepare_etl_estructura_acta",
            lambda: prepare_estructura_acta_rows(id_archivo, result)
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
            lambda: prepare_regla_rows(id_archivo, result, "ACTA_AUDIENCIA_PDF"),
        )

        summary["estructuras_acta_insertadas"] = timed_step(
            timings,
            "insert_etl_estructura_acta",
            lambda: db.insert_many("jnc.etl_estructura_acta", estructura_rows),
        )
        estructura_id_by_key = timed_step(
            timings,
            "fetch_estructura_acta_id_map",
            lambda: {
                _estructura_acta_key(row): row.get("id_estructura_acta")
                for row in db.fetch_rows(
                    "jnc.etl_estructura_acta",
                    [
                        "id_estructura_acta",
                        "id_archivo",
                        "numero_acta_normalizado",
                        "fecha_audiencia",
                        "sala_normalizada",
                    ],
                    "[id_archivo] = ?",
                    [id_archivo],
                )
            },
        )
        caso_rows = timed_step(
            timings,
            "prepare_audiencia_caso",
            lambda: prepare_audiencia_caso_rows(
                id_archivo,
                result,
                estructura_id_by_key,
            )
            if result.get("status") == "OK"
            else [],
        )
        summary["casos_acta_insertados"] = timed_step(
            timings,
            "insert_audiencia_caso",
            lambda: db.insert_many("jnc.audiencia_caso", caso_rows),
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
            lambda: prepare_archivo_update_from_audiencias_result(id_archivo, result),
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
            summary["status"] = "ERROR"
            summary["mensaje"] = "Resultado de actas de audiencia PDF escrito con errores"

        return summary

    return db.run_in_transaction(transaction)
