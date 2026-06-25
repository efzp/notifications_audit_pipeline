from typing import Any

from src.load import db
from src.load.prepare_sql_rows import (
    prepare_archivo_update_from_revision_manual_guias_result,
    prepare_error_rows,
    prepare_regla_rows,
    prepare_revision_manual_guia_rows,
)
from src.load.timing import timed_step


def write_revision_manual_guias_result_to_sql(
    id_archivo: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    summary = {
        "status": "OK",
        "id_archivo": id_archivo,
        "revisiones_insertadas": 0,
        "errores_insertados": 0,
        "reglas_insertadas": 0,
        "timings": {},
        "mensaje": "Revision manual de guias escrita en Azure SQL",
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
            "delete_revision_manual_guia",
            lambda: db.delete_by_archivo("jnc.revision_manual_guia", id_archivo),
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

        revision_rows = timed_step(
            timings,
            "prepare_revision_manual_guia",
            lambda: prepare_revision_manual_guia_rows(id_archivo, result)
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
            lambda: prepare_regla_rows(
                id_archivo,
                result,
                "REVISION_MANUAL_GUIAS",
            ),
        )

        summary["revisiones_insertadas"] = timed_step(
            timings,
            "insert_revision_manual_guia",
            lambda: db.insert_many("jnc.revision_manual_guia", revision_rows),
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
            lambda: prepare_archivo_update_from_revision_manual_guias_result(
                id_archivo,
                result,
            ),
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
            summary["mensaje"] = "Revision manual de guias escrita con errores"

        return summary

    return db.run_in_transaction(transaction)
