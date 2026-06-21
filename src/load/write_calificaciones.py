from typing import Any

from src.load import db
from src.load.prepare_sql_rows import (
    prepare_archivo_update_from_calificaciones_result,
    prepare_calificacion_sistema_caso_rows,
    prepare_calificacion_sistema_envio_rows,
    prepare_error_rows,
    prepare_regla_rows,
)
from src.load.timing import timed_step


def write_calificaciones_result_to_sql(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "status": "OK",
        "id_archivo": id_archivo,
        "casos_insertados": 0,
        "envios_entidad_insertados": 0,
        "notificaciones_insertadas": 0,
        "errores_insertados": 0,
        "reglas_insertadas": 0,
        "estructura_hoja_insertadas": 0,
        "timings": {},
        "mensaje": "Resultado de calificaciones del software escrito en Azure SQL",
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
            "delete_calificacion_sistema_envio_entidad",
            lambda: db.delete_by_archivo(
                "jnc.calificacion_sistema_envio_entidad",
                id_archivo,
            ),
        )
        timed_step(
            timings,
            "delete_calificacion_sistema_caso",
            lambda: db.delete_by_archivo("jnc.calificacion_sistema_caso", id_archivo),
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

        caso_rows = timed_step(
            timings,
            "prepare_calificacion_sistema_caso",
            lambda: prepare_calificacion_sistema_caso_rows(id_archivo, result)
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
            lambda: prepare_regla_rows(id_archivo, result, "CALIFICACIONES_SOFTWARE"),
        )

        summary["casos_insertados"] = timed_step(
            timings,
            "insert_calificacion_sistema_caso",
            lambda: db.insert_many("jnc.calificacion_sistema_caso", caso_rows),
        )
        caso_id_by_hash = timed_step(
            timings,
            "fetch_calificacion_sistema_caso_id_map",
            lambda: {
                row["hash_calificacion_sistema_caso"]: row[
                    "id_calificacion_sistema_caso"
                ]
                for row in db.fetch_rows(
                    "jnc.calificacion_sistema_caso",
                    [
                        "id_calificacion_sistema_caso",
                        "hash_calificacion_sistema_caso",
                    ],
                    "[id_archivo] = ?",
                    [id_archivo],
                )
                if row.get("hash_calificacion_sistema_caso")
            },
        )
        envio_rows = timed_step(
            timings,
            "prepare_calificacion_sistema_envio_entidad",
            lambda: prepare_calificacion_sistema_envio_rows(
                id_archivo,
                result,
                caso_id_by_hash,
            )
            if result.get("status") == "OK"
            else [],
        )
        summary["envios_entidad_insertados"] = timed_step(
            timings,
            "insert_calificacion_sistema_envio_entidad",
            lambda: db.insert_many(
                "jnc.calificacion_sistema_envio_entidad",
                envio_rows,
            ),
        )
        summary["notificaciones_insertadas"] = summary["envios_entidad_insertados"]
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
            lambda: prepare_archivo_update_from_calificaciones_result(id_archivo, result),
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
            summary["mensaje"] = "Resultado de calificaciones del software escrito con errores"

        return summary

    return db.run_in_transaction(transaction)
