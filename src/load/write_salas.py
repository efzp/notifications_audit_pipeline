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
from src.utils.normalization import normalize_document, normalize_radicado


RAW_ORIGIN = "RAW_INPUT_SALAS"


def _canonical_tipo_destinatario(value: Any) -> str | None:
    clean_value = str(value or "").strip().upper()
    if not clean_value:
        return None
    if clean_value == "PACIENTE":
        return "PACIENTES"
    return clean_value


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


def _calificacion_case_ids(
    case_id_by_key: dict[tuple[str | None, str | None], int],
) -> list[int]:
    return sorted({value for value in case_id_by_key.values() if value is not None})


def _fetch_calificacion_case_id_map(
    result: dict[str, Any],
) -> dict[tuple[str | None, str | None], int]:
    keys = {
        (
            normalize_radicado(row.get("numero_radicado")),
            normalize_document(row.get("cedula")),
        )
        for row in result.get("tabla_notificaciones") or []
        if normalize_radicado(row.get("numero_radicado"))
    }
    radicados = sorted({radicado for radicado, _ in keys if radicado})
    if not radicados:
        return {}

    case_id_by_key: dict[tuple[str | None, str | None], int] = {}
    for chunk in _chunks(radicados):
        placeholders = ", ".join("?" for _ in chunk)
        rows = db.fetch_rows(
            "jnc.calificacion_sistema_caso",
            [
                "id_calificacion_sistema_caso",
                "numero_radicado_normalizado",
                "cedula_normalizada",
            ],
            (
                "[activo] = ? "
                f"AND [numero_radicado_normalizado] IN ({placeholders})"
            ),
            [1, *chunk],
        )
        for row in rows:
            exact_key = (
                row.get("numero_radicado_normalizado"),
                row.get("cedula_normalizada"),
            )
            radicado_key = (row.get("numero_radicado_normalizado"), None)
            if exact_key in keys and exact_key not in case_id_by_key:
                case_id_by_key[exact_key] = row["id_calificacion_sistema_caso"]
            if radicado_key not in case_id_by_key:
                case_id_by_key[radicado_key] = row["id_calificacion_sistema_caso"]

    return case_id_by_key


def _fetch_fallback_correo_map(
    calificacion_case_ids: list[int],
) -> dict[tuple[int, str], dict[str, Any]]:
    if not calificacion_case_ids:
        return {}

    fallback_by_key: dict[tuple[int, str], dict[str, Any]] = {}
    for chunk in _chunks(calificacion_case_ids):
        placeholders = ", ".join("?" for _ in chunk)
        rows = db.fetch_rows(
            "jnc.calificacion_sistema_envio_entidad",
            [
                "id_calificacion_sistema_envio",
                "id_calificacion_sistema_caso",
                "tipo_entidad",
                "correo_reportado",
                "correo_normalizado",
            ],
            (
                "[activo] = ? "
                "AND [correo_normalizado] IS NOT NULL "
                f"AND [id_calificacion_sistema_caso] IN ({placeholders})"
            ),
            [1, *chunk],
        )
        for row in rows:
            tipo_destinatario = _canonical_tipo_destinatario(row.get("tipo_entidad"))
            if not tipo_destinatario:
                continue
            key = (row["id_calificacion_sistema_caso"], tipo_destinatario)
            fallback_by_key.setdefault(key, row)

    return fallback_by_key


def _existing_hashes_by_business_hash(rows: list[dict[str, Any]]) -> set[str]:
    hashes = sorted(
        {
            row.get("hash_negocio_notificacion")
            for row in rows
            if row.get("hash_negocio_notificacion")
        }
    )
    if not hashes:
        return set()

    existing_hashes: set[str] = set()
    for chunk in _chunks(hashes):
        placeholders = ", ".join("?" for _ in chunk)
        fetched_rows = db.fetch_rows(
            "jnc.notificacion_esperada",
            ["hash_negocio_notificacion"],
            (
                "[activo] = ? "
                f"AND [hash_negocio_notificacion] IN ({placeholders})"
            ),
            [1, *chunk],
        )
        existing_hashes.update(
            row["hash_negocio_notificacion"]
            for row in fetched_rows
            if row.get("hash_negocio_notificacion")
        )

    return existing_hashes


def _filter_new_business_notifications(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    existing_hashes = _existing_hashes_by_business_hash(rows)
    seen_hashes = set()
    filtered_rows = []
    skipped = 0
    for row in rows:
        business_hash = row.get("hash_negocio_notificacion")
        if business_hash and (
            business_hash in existing_hashes or business_hash in seen_hashes
        ):
            skipped += 1
            continue
        if business_hash:
            seen_hashes.add(business_hash)
        filtered_rows.append(row)

    return filtered_rows, skipped


def _chunks(values: list[Any], size: int = 900):
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


def _backfill_sala_from_calificacion_sistema_caso() -> dict[str, int]:
    notificaciones_actualizadas = db.execute_sql(
        """
        UPDATE ne
        SET
            hoja_trabajo_sala = COALESCE(ne.hoja_trabajo_sala, csc.sala),
            hoja_trabajo_sala_normalizada = COALESCE(
                ne.hoja_trabajo_sala_normalizada,
                csc.sala
            ),
            pestana_sala_normalizada = COALESCE(
                ne.pestana_sala_normalizada,
                csc.sala
            ),
            hoja_trabajo_fecha_audiencia = COALESCE(
                ne.hoja_trabajo_fecha_audiencia,
                csc.fecha_audiencia
            ),
            fecha_actualizacion = SYSUTCDATETIME()
        FROM jnc.notificacion_esperada ne
        INNER JOIN jnc.calificacion_sistema_caso csc
            ON (
                csc.id_calificacion_sistema_caso = ne.id_calificacion_sistema_caso
                OR (
                    ne.id_calificacion_sistema_caso IS NULL
                    AND csc.numero_radicado_normalizado = ne.numero_radicado_normalizado
                )
            )
        WHERE ne.numero_radicado_normalizado IS NOT NULL
          AND csc.activo = 1
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
            hoja_trabajo_sala = COALESCE(cc.hoja_trabajo_sala, csc.sala),
            hoja_trabajo_sala_normalizada = COALESCE(
                cc.hoja_trabajo_sala_normalizada,
                csc.sala
            ),
            pestana_sala_normalizada = COALESCE(
                cc.pestana_sala_normalizada,
                csc.sala
            ),
            hoja_trabajo_fecha_audiencia = COALESCE(
                cc.hoja_trabajo_fecha_audiencia,
                csc.fecha_audiencia
            ),
            fecha_actualizacion = SYSUTCDATETIME()
        FROM jnc.caso_calificado cc
        INNER JOIN jnc.calificacion_sistema_caso csc
            ON csc.numero_radicado_normalizado = cc.numero_radicado_normalizado
        WHERE cc.numero_radicado_normalizado IS NOT NULL
          AND csc.activo = 1
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
        "notificaciones_duplicadas_omitidas": 0,
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
            calificacion_caso_id_by_key = timed_step(
                timings,
                "fetch_calificacion_sistema_caso_id_map",
                lambda: _fetch_calificacion_case_id_map(result),
            )
            fallback_correo_by_key = timed_step(
                timings,
                "fetch_fallback_correo_calificacion",
                lambda: _fetch_fallback_correo_map(
                    _calificacion_case_ids(calificacion_caso_id_by_key)
                ),
            )
            notificacion_rows = timed_step(
                timings,
                "prepare_notificacion_esperada",
                lambda: prepare_notificacion_rows(
                    id_archivo,
                    result,
                    caso_id_by_radicado,
                    calificacion_caso_id_by_key,
                    fallback_correo_by_key,
                ),
            )
            notificacion_rows = [
                row
                for row in notificacion_rows
                if row.get("id_caso") is not None
                or row.get("id_calificacion_sistema_caso") is not None
            ]
            notificacion_rows, skipped_duplicates = timed_step(
                timings,
                "filter_notificacion_esperada_hash_negocio",
                lambda: _filter_new_business_notifications(notificacion_rows),
            )
            summary["notificaciones_duplicadas_omitidas"] = skipped_duplicates
            summary["notificaciones_insertadas"] = timed_step(
                timings,
                "insert_notificacion_esperada",
                lambda: db.insert_many("jnc.notificacion_esperada", notificacion_rows),
            )
            summary["backfill_sala"] = timed_step(
                timings,
                "backfill_sala_desde_calificacion_sistema_caso",
                _backfill_sala_from_calificacion_sistema_caso,
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
