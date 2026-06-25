import json
from typing import Any

from src.load import db
from src.reconcile.notificaciones import (
    CRUCE_VERSION,
    ESTADO_CUMPLE,
    ESTADO_FUERA_DE_PLAZO,
    _refresh_cruce_notificacion_pendiente,
    utc_now_iso,
)
from src.reconcile.resumen_validacion import refrescar_resumen_validacion_radicado
from src.utils.normalization import json_dumps_safe


FINAL_STATUSES = {ESTADO_CUMPLE, ESTADO_FUERA_DE_PLAZO}
MANUAL_VERSION = f"{CRUCE_VERSION}:REVISION_MANUAL_NOTIFICACION"


def _truthy_bit(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    return str(value or "").strip().lower() in {"1", "true", "si", "s", "yes"}


def _manual_status(row: dict[str, Any]) -> tuple[str | None, str | None]:
    cumple = _truthy_bit(row.get("cumplimiento"))
    cumple_extemporaneo = _truthy_bit(row.get("cumplimiento_extemporaneo"))

    if cumple and cumple_extemporaneo:
        return None, "Decision invalida: cumplimiento y cumplimiento_extemporaneo son verdaderos"
    if cumple:
        return ESTADO_CUMPLE, None
    if cumple_extemporaneo:
        return ESTADO_FUERA_DE_PLAZO, None
    return None, "Sin decision aplicable: cumplimiento y cumplimiento_extemporaneo estan vacios o falsos"


def _fetch_pending_manual_rows(
    id_archivo: int | None,
    batch_size: int | None,
) -> list[dict[str, Any]]:
    columns = [
        "id_revision_manual_notificacion",
        "id_archivo",
        "numero_linea_excel",
        "id_notificacion_esperada",
        "numero_radicado_normalizado",
        "cedula_normalizada",
        "tipo_destinatario",
        "cumplimiento",
        "cumplimiento_extemporaneo",
        "observaciones",
        "revisado_por",
        "fecha_revision",
    ]
    where = "[activo] = 1 AND [estado_aplicacion] = ?"
    params: list[Any] = ["PENDIENTE"]
    if id_archivo is not None:
        where += " AND [id_archivo] = ?"
        params.append(id_archivo)
    where += " ORDER BY [id_revision_manual_notificacion]"
    if batch_size is not None:
        where += " OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY"
        params.append(batch_size)

    return db.fetch_rows("jnc.revision_manual_notificacion", columns, where, params)


def _fetch_expected_rows(ids: list[Any]) -> dict[int, dict[str, Any]]:
    if not ids:
        return {}

    table_columns = db.get_table_columns("jnc.notificacion_esperada")
    wanted_columns = [
        "id_notificacion_esperada",
        "id_archivo",
        "id_caso",
        "id_calificacion_sistema_caso",
        "numero_radicado",
        "numero_radicado_normalizado",
        "cedula",
        "cedula_normalizada",
        "tipo_destinatario",
        "correo_o_guia_reportado",
        "correo_normalizado",
        "hoja_trabajo_fecha_audiencia",
        "fecha_envio_reportada",
        "estado_revision_notificacion",
        "pendiente_revision",
        "detalle_revision_json",
        "activo",
    ]
    columns = [column for column in wanted_columns if column in table_columns]
    rows: list[dict[str, Any]] = []

    clean_ids = sorted({int(value) for value in ids if value is not None})
    for chunk in [clean_ids[index : index + 900] for index in range(0, len(clean_ids), 900)]:
        placeholders = ", ".join("?" for _ in chunk)
        rows.extend(
            db.fetch_rows(
                "jnc.notificacion_esperada",
                columns,
                f"[id_notificacion_esperada] IN ({placeholders})",
                chunk,
            )
        )

    return {
        int(row["id_notificacion_esperada"]): row
        for row in rows
        if row.get("id_notificacion_esperada") is not None
    }


def _manual_detail_json(
    manual_row: dict[str, Any],
    expected_row: dict[str, Any],
    status: str,
) -> str | None:
    detail = {
        "fuente_revision": "REVISION_MANUAL_NOTIFICACION",
        "estado_revision_notificacion": status,
        "numero_radicado_normalizado": expected_row.get("numero_radicado_normalizado"),
        "cedula_normalizada": expected_row.get("cedula_normalizada"),
        "tipo_destinatario": expected_row.get("tipo_destinatario"),
        "id_revision_manual_notificacion": manual_row.get("id_revision_manual_notificacion"),
        "id_archivo_revision_manual": manual_row.get("id_archivo"),
        "numero_linea_excel": manual_row.get("numero_linea_excel"),
        "cumplimiento": bool(_truthy_bit(manual_row.get("cumplimiento"))),
        "cumplimiento_extemporaneo": bool(
            _truthy_bit(manual_row.get("cumplimiento_extemporaneo"))
        ),
        "observaciones": manual_row.get("observaciones"),
        "revisado_por": manual_row.get("revisado_por"),
        "fecha_revision_manual": str(manual_row.get("fecha_revision"))
        if manual_row.get("fecha_revision") is not None
        else None,
        "checks": {
            "cumple_documento": True,
            "cumple_asunto": False,
            "cumple_evento": True,
            "cumple_correo": True,
            "cumple_plazo": status == ESTADO_CUMPLE,
        },
    }
    return json_dumps_safe(detail)


def _build_manual_rows(
    manual_row: dict[str, Any],
    expected_row: dict[str, Any],
    status: str,
    revision_date: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    descripcion = (
        manual_row.get("observaciones")
        or f"Aplicado por revision manual de notificaciones: {status}"
    )
    detail_json = _manual_detail_json(manual_row, expected_row, status)
    cumple_plazo = status == ESTADO_CUMPLE

    update_row = {
        "id_notificacion_esperada": expected_row["id_notificacion_esperada"],
        "estado_revision_notificacion": status,
        "pendiente_revision": descripcion,
        "fecha_revision_notificacion": revision_date,
        "detalle_revision_json": detail_json,
        "fecha_actualizacion": revision_date,
    }
    cruce_row = {
        "id_notificacion_esperada": expected_row["id_notificacion_esperada"],
        "id_caso": expected_row.get("id_caso"),
        "id_calificacion_sistema_caso": expected_row.get(
            "id_calificacion_sistema_caso"
        ),
        "id_archivo": expected_row.get("id_archivo"),
        "numero_radicado": expected_row.get("numero_radicado"),
        "numero_radicado_normalizado": expected_row.get(
            "numero_radicado_normalizado"
        ),
        "cedula": expected_row.get("cedula"),
        "cedula_normalizada": expected_row.get("cedula_normalizada"),
        "tipo_destinatario": expected_row.get("tipo_destinatario"),
        "estado_revision_notificacion": status,
        "descripcion_revision": descripcion,
        "cumple_documento": 1,
        "cumple_asunto": 0,
        "cumple_evento": 1,
        "cumple_correo": 1,
        "cumple_plazo": 1 if cumple_plazo else 0,
        "score_total": 4 if cumple_plazo else 3,
        "fuente_documento_match": "REVISION_MANUAL_NOTIFICACION",
        "evento_tipo_match": "REVISION_MANUAL",
        "tipo_match_correo": "REVISION_MANUAL_NOTIFICACION",
        "correo_esperado": expected_row.get("correo_o_guia_reportado"),
        "correo_certificado": None,
        "fecha_audiencia": expected_row.get("hoja_trabajo_fecha_audiencia")
        or expected_row.get("fecha_envio_reportada"),
        "fecha_envio_certificado": None,
        "dias_despues_audiencia": None,
        "fecha_revision": revision_date,
        "version_regla_cruce": MANUAL_VERSION,
        "detalle_revision_json": detail_json,
        "activo": 1,
        "fecha_creacion": revision_date,
        "fecha_actualizacion": revision_date,
    }
    return update_row, cruce_row


def _application_update(
    manual_row: dict[str, Any],
    estado_aplicacion: str,
    detalle: dict[str, Any],
    revision_date: str,
) -> dict[str, Any]:
    return {
        "id_revision_manual_notificacion": manual_row["id_revision_manual_notificacion"],
        "estado_aplicacion": estado_aplicacion,
        "fecha_aplicacion": revision_date,
        "detalle_aplicacion": json.dumps(detalle, ensure_ascii=False, default=str),
        "fecha_actualizacion": revision_date,
    }


def aplicar_revision_manual_notificaciones(
    id_archivo: int | None = None,
    batch_size: int | None = None,
    refrescar_resumen: bool = True,
) -> dict[str, Any]:
    manual_rows = _fetch_pending_manual_rows(id_archivo, batch_size)
    expected_by_id = _fetch_expected_rows(
        [row.get("id_notificacion_esperada") for row in manual_rows]
    )
    revision_date = utc_now_iso()

    notification_updates = []
    cruce_rows = []
    application_updates = []
    applied_expected_ids = []

    summary = {
        "id_archivo": id_archivo,
        "batch_size": batch_size,
        "revisiones_leidas": len(manual_rows),
        "aplicadas": 0,
        "omitidas": 0,
        "errores": 0,
        "notificaciones_actualizadas": 0,
        "cruces_eliminados": 0,
        "cruces_insertados": 0,
        "cruce_notificacion_pendiente": {},
        "resumen_validacion_radicado": {},
    }

    for manual_row in manual_rows:
        status, decision_error = _manual_status(manual_row)
        expected_id = manual_row.get("id_notificacion_esperada")
        expected_row = expected_by_id.get(int(expected_id)) if expected_id is not None else None

        if decision_error:
            summary["errores"] += 1
            application_updates.append(
                _application_update(
                    manual_row,
                    "ERROR_DECISION",
                    {"mensaje": decision_error},
                    revision_date,
                )
            )
            continue

        if not expected_row or not expected_row.get("activo"):
            summary["errores"] += 1
            application_updates.append(
                _application_update(
                    manual_row,
                    "ERROR_NOTIFICACION_NO_ENCONTRADA",
                    {"id_notificacion_esperada": expected_id},
                    revision_date,
                )
            )
            continue

        previous_status = expected_row.get("estado_revision_notificacion")
        if previous_status in FINAL_STATUSES:
            summary["omitidas"] += 1
            application_updates.append(
                _application_update(
                    manual_row,
                    "OMITIDA_ESTADO_FINAL",
                    {
                        "id_notificacion_esperada": expected_id,
                        "estado_revision_notificacion": previous_status,
                    },
                    revision_date,
                )
            )
            continue

        update_row, cruce_row = _build_manual_rows(
            manual_row,
            expected_row,
            status or ESTADO_CUMPLE,
            revision_date,
        )
        notification_updates.append(update_row)
        cruce_rows.append(cruce_row)
        applied_expected_ids.append(expected_id)
        summary["aplicadas"] += 1
        application_updates.append(
            _application_update(
                manual_row,
                "APLICADA",
                {
                    "id_notificacion_esperada": expected_id,
                    "estado_revision_notificacion": status,
                },
                revision_date,
            )
        )

    if cruce_rows:
        summary["cruces_eliminados"] = db.delete_by_column_values(
            "jnc.resultado_cruce_notificacion",
            "id_notificacion_esperada",
            applied_expected_ids,
        )
        summary["cruces_insertados"] = db.insert_many(
            "jnc.resultado_cruce_notificacion",
            cruce_rows,
        )

    summary["notificaciones_actualizadas"] = db.execute_many_updates(
        "jnc.notificacion_esperada",
        "id_notificacion_esperada",
        notification_updates,
    )
    db.execute_many_updates(
        "jnc.revision_manual_notificacion",
        "id_revision_manual_notificacion",
        application_updates,
    )

    if applied_expected_ids:
        summary["cruce_notificacion_pendiente"] = _refresh_cruce_notificacion_pendiente(
            id_notificacion_esperada_values=applied_expected_ids,
        )
    else:
        summary["cruce_notificacion_pendiente"] = {
            "omitido": True,
            "motivo": "No hubo revisiones manuales aplicadas",
        }
    if refrescar_resumen:
        summary["resumen_validacion_radicado"] = refrescar_resumen_validacion_radicado()

    return summary
