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
from src.load.timing import timed_step
from src.reconcile.notificaciones import recalcular_cruce_notificaciones


RAW_ORIGIN = "RAW_INPUT_SALAS"


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


def _chunks(values: list[str], size: int = 900):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _delete_raw_rows_for_consolidated_radicados(radicados: list[str]) -> dict[str, int]:
    clean_radicados = sorted({radicado for radicado in radicados if radicado})
    if not clean_radicados:
        return {"notificaciones_raw_eliminadas": 0, "casos_raw_eliminados": 0}

    deleted_notifications = 0
    deleted_cases = 0
    for chunk in _chunks(clean_radicados):
        placeholders = ", ".join("?" for _ in chunk)
        deleted_notifications += db.execute_sql(
            (
                "DELETE FROM jnc.notificacion_esperada "
                "WHERE origen_tabla = ? "
                f"AND numero_radicado_normalizado IN ({placeholders})"
            ),
            [RAW_ORIGIN, *chunk],
        )
        deleted_cases += db.execute_sql(
            (
                "DELETE FROM jnc.caso_calificado "
                "WHERE origen_tabla = ? "
                f"AND numero_radicado_normalizado IN ({placeholders})"
            ),
            [RAW_ORIGIN, *chunk],
        )

    return {
        "notificaciones_raw_eliminadas": deleted_notifications,
        "casos_raw_eliminados": deleted_cases,
    }


def _backfill_sala_from_audiencia_caso() -> dict[str, int]:
    notificaciones_actualizadas = db.execute_sql(
        """
        UPDATE ne
        SET
            hoja_trabajo_sala = COALESCE(ne.hoja_trabajo_sala, ac.sala),
            hoja_trabajo_sala_normalizada = COALESCE(
                ne.hoja_trabajo_sala_normalizada,
                ac.sala_normalizada
            ),
            pestana_sala_normalizada = COALESCE(
                ne.pestana_sala_normalizada,
                ac.sala_normalizada
            ),
            hoja_trabajo_fecha_audiencia = COALESCE(
                ne.hoja_trabajo_fecha_audiencia,
                ac.fecha_audiencia
            ),
            fecha_actualizacion = SYSUTCDATETIME()
        FROM jnc.notificacion_esperada ne
        INNER JOIN jnc.audiencia_caso ac
            ON ac.numero_radicado_normalizado = ne.numero_radicado_normalizado
        WHERE ne.numero_radicado_normalizado IS NOT NULL
          AND (
              ne.hoja_trabajo_sala_normalizada IS NULL
              OR ne.hoja_trabajo_sala IS NULL
              OR ne.hoja_trabajo_fecha_audiencia IS NULL
          )
        """
    )
    casos_actualizados = db.execute_sql(
        """
        UPDATE cc
        SET
            hoja_trabajo_sala = COALESCE(cc.hoja_trabajo_sala, ac.sala),
            hoja_trabajo_sala_normalizada = COALESCE(
                cc.hoja_trabajo_sala_normalizada,
                ac.sala_normalizada
            ),
            pestana_sala_normalizada = COALESCE(
                cc.pestana_sala_normalizada,
                ac.sala_normalizada
            ),
            hoja_trabajo_fecha_audiencia = COALESCE(
                cc.hoja_trabajo_fecha_audiencia,
                ac.fecha_audiencia
            ),
            fecha_actualizacion = SYSUTCDATETIME()
        FROM jnc.caso_calificado cc
        INNER JOIN jnc.audiencia_caso ac
            ON ac.numero_radicado_normalizado = cc.numero_radicado_normalizado
        WHERE cc.numero_radicado_normalizado IS NOT NULL
          AND (
              cc.hoja_trabajo_sala_normalizada IS NULL
              OR cc.hoja_trabajo_sala IS NULL
              OR cc.hoja_trabajo_fecha_audiencia IS NULL
          )
        """
    )
    return {
        "notificaciones_sala_actualizadas": notificaciones_actualizadas,
        "casos_sala_actualizados": casos_actualizados,
    }


def write_salas_result_to_sql(id_archivo: int, result: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "status": "OK",
        "id_archivo": id_archivo,
        "estructura_hoja_insertadas": 0,
        "casos_insertados": 0,
        "notificaciones_insertadas": 0,
        "errores_insertados": 0,
        "reglas_insertadas": 0,
        "cruce_notificaciones": {},
        "prioridad_consolidado": {},
        "backfill_sala": {},
        "timings": {},
        "mensaje": "Resultado de salas escrito en Azure SQL",
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
            "delete_notificacion_esperada",
            lambda: db.delete_by_archivo("jnc.notificacion_esperada", id_archivo),
        )
        timed_step(
            timings,
            "delete_caso_calificado",
            lambda: db.delete_by_archivo("jnc.caso_calificado", id_archivo),
        )
        timed_step(
            timings,
            "delete_etl_estructura_hoja",
            lambda: db.delete_by_archivo("jnc.etl_estructura_hoja", id_archivo),
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
            "prepare_estructura_hoja",
            lambda: prepare_estructura_hoja_rows(id_archivo, result),
        )
        error_rows = timed_step(
            timings,
            "prepare_error_rows",
            lambda: prepare_error_rows(id_archivo, result),
        )
        regla_rows = timed_step(
            timings,
            "prepare_regla_rows",
            lambda: prepare_regla_rows(id_archivo, result, "SALAS"),
        )

        summary["estructura_hoja_insertadas"] = timed_step(
            timings,
            "insert_etl_estructura_hoja",
            lambda: db.insert_many("jnc.etl_estructura_hoja", estructura_rows),
        )

        if result.get("status") == "OK":
            caso_rows = timed_step(
                timings,
                "prepare_caso_calificado",
                lambda: prepare_caso_rows(id_archivo, result),
            )
            if result.get("modo_procesamiento") != RAW_ORIGIN:
                consolidated_radicados = [
                    row.get("numero_radicado_normalizado")
                    for row in caso_rows
                ]
                summary["prioridad_consolidado"] = timed_step(
                    timings,
                    "delete_raw_prioridad_consolidado",
                    lambda: _delete_raw_rows_for_consolidated_radicados(
                        consolidated_radicados
                    ),
                )
            summary["casos_insertados"] = timed_step(
                timings,
                "insert_caso_calificado",
                lambda: db.insert_many("jnc.caso_calificado", caso_rows),
            )

            caso_id_by_radicado = timed_step(
                timings,
                "fetch_caso_id_map",
                lambda: _fetch_case_id_map(id_archivo),
            )
            notificacion_rows = timed_step(
                timings,
                "prepare_notificacion_esperada",
                lambda: prepare_notificacion_rows(id_archivo, result, caso_id_by_radicado),
            )
            notificacion_rows = [
                row for row in notificacion_rows if row.get("id_caso") is not None
            ]
            summary["notificaciones_insertadas"] = timed_step(
                timings,
                "insert_notificacion_esperada",
                lambda: db.insert_many("jnc.notificacion_esperada", notificacion_rows),
            )
            summary["backfill_sala"] = timed_step(
                timings,
                "backfill_sala_desde_audiencia_caso",
                _backfill_sala_from_audiencia_caso,
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
            lambda: prepare_archivo_update_from_salas_result(id_archivo, result),
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
            summary["cruce_notificaciones"] = timed_step(
                timings,
                "recalcular_cruce_notificaciones",
                lambda: recalcular_cruce_notificaciones(
                    id_archivo_salas=id_archivo,
                    solo_pendientes=False,
                ),
            )

        if result.get("status") != "OK":
            summary["status"] = "ERROR"
            summary["mensaje"] = "Resultado de salas escrito con errores de estructura"

        return summary

    return db.run_in_transaction(transaction)
