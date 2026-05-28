from typing import Any

from src.load import db
from src.load.prepare_sql_rows import (
    prepare_archivo_update_from_correo_result,
    prepare_correo_certificado_rows,
    prepare_error_rows,
    prepare_regla_rows,
)


def write_correo_result_to_sql(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "status": "OK",
        "id_archivo": id_archivo,
        "correos_insertados": 0,
        "errores_insertados": 0,
        "reglas_insertadas": 0,
        "mensaje": "Resultado de correo certificado escrito en Azure SQL",
    }

    def transaction():
        db.execute_update(
            "jnc.etl_archivo_cargado",
            "id_archivo",
            id_archivo,
            {"estado_proceso": "EN_PROCESO"},
        )

        db.delete_by_archivo("jnc.notificacion_correo_certificado", id_archivo)
        db.delete_by_archivo("jnc.etl_error_procesamiento", id_archivo)
        db.delete_by_archivo("jnc.etl_ejecucion_regla", id_archivo)

        correo_rows = (
            prepare_correo_certificado_rows(id_archivo, result)
            if result.get("status") == "OK"
            else []
        )
        error_rows = prepare_error_rows(id_archivo, result)
        regla_rows = prepare_regla_rows(id_archivo, result, "CORREO_CERTIFICADO")

        summary["correos_insertados"] = db.insert_many(
            "jnc.notificacion_correo_certificado",
            correo_rows,
        )
        summary["errores_insertados"] = db.insert_many(
            "jnc.etl_error_procesamiento",
            error_rows,
        )
        summary["reglas_insertadas"] = db.insert_many("jnc.etl_ejecucion_regla", regla_rows)

        archivo_update = prepare_archivo_update_from_correo_result(id_archivo, result)
        archivo_update.pop("id_archivo", None)
        db.execute_update(
            "jnc.etl_archivo_cargado",
            "id_archivo",
            id_archivo,
            archivo_update,
        )

        if result.get("status") != "OK":
            summary["status"] = "ERROR"
            summary["mensaje"] = "Resultado de correo certificado escrito con errores"

        return summary

    return db.run_in_transaction(transaction)
