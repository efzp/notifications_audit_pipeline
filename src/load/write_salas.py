from typing import Any

from src.load import db
from src.load.prepare_sql_rows import (
    prepare_archivo_update_from_salas_result,
    prepare_caso_rows,
    prepare_error_rows,
    prepare_estructura_hoja_rows,
    prepare_notificacion_rows,
    prepare_regla_rows,
)


def _fetch_case_id_map(id_archivo: int) -> dict[str, int]:
    rows = db.fetch_rows(
        "jnc.caso_calificado",
        ["id_caso", "numero_radicado_normalizado", "hash_caso"],
        "[id_archivo] = ?",
        [id_archivo],
    )

    case_id_by_key = {}
    for row in rows:
        if row.get("numero_radicado_normalizado"):
            case_id_by_key[row["numero_radicado_normalizado"]] = row["id_caso"]
        if row.get("hash_caso"):
            case_id_by_key[row["hash_caso"]] = row["id_caso"]

    return case_id_by_key


def write_salas_result_to_sql(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "status": "OK",
        "id_archivo": id_archivo,
        "estructura_hoja_insertadas": 0,
        "casos_insertados": 0,
        "notificaciones_insertadas": 0,
        "errores_insertados": 0,
        "reglas_insertadas": 0,
        "mensaje": "Resultado de salas escrito en Azure SQL",
    }

    def transaction():
        db.execute_update(
            "jnc.etl_archivo_cargado",
            "id_archivo",
            id_archivo,
            {"estado_proceso": "EN_PROCESO"},
        )

        db.delete_by_archivo("jnc.notificacion_esperada", id_archivo)
        db.delete_by_archivo("jnc.caso_calificado", id_archivo)
        db.delete_by_archivo("jnc.etl_estructura_hoja", id_archivo)
        db.delete_by_archivo("jnc.etl_error_procesamiento", id_archivo)
        db.delete_by_archivo("jnc.etl_ejecucion_regla", id_archivo)

        estructura_rows = prepare_estructura_hoja_rows(id_archivo, result)
        error_rows = prepare_error_rows(id_archivo, result)
        regla_rows = prepare_regla_rows(id_archivo, result, "SALAS")

        summary["estructura_hoja_insertadas"] = db.insert_many(
            "jnc.etl_estructura_hoja",
            estructura_rows,
        )

        if result.get("status") == "OK":
            caso_rows = prepare_caso_rows(id_archivo, result)
            summary["casos_insertados"] = db.insert_many("jnc.caso_calificado", caso_rows)

            caso_id_by_radicado = _fetch_case_id_map(id_archivo)
            notificacion_rows = prepare_notificacion_rows(
                id_archivo,
                result,
                caso_id_by_radicado,
            )
            notificacion_rows = [
                row for row in notificacion_rows if row.get("id_caso") is not None
            ]
            summary["notificaciones_insertadas"] = db.insert_many(
                "jnc.notificacion_esperada",
                notificacion_rows,
            )

        summary["errores_insertados"] = db.insert_many(
            "jnc.etl_error_procesamiento",
            error_rows,
        )
        summary["reglas_insertadas"] = db.insert_many("jnc.etl_ejecucion_regla", regla_rows)

        archivo_update = prepare_archivo_update_from_salas_result(id_archivo, result)
        archivo_update.pop("id_archivo", None)
        db.execute_update(
            "jnc.etl_archivo_cargado",
            "id_archivo",
            id_archivo,
            archivo_update,
        )

        if result.get("status") != "OK":
            summary["status"] = "ERROR"
            summary["mensaje"] = "Resultado de salas escrito con errores de estructura"

        return summary

    return db.run_in_transaction(transaction)
