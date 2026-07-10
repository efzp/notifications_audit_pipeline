from pathlib import Path
from typing import Any

from src.load import db


def _load_refresh_procedure_sql() -> str:
    sql_path = (
        Path(__file__).resolve().parents[2]
        / "sql"
        / "migrations"
        / "20260710_update_refrescar_resumen_validacion_radicado.sql"
    )
    sql_text = sql_path.read_text(encoding="utf-8")
    return "\n".join(
        line for line in sql_text.splitlines() if line.strip().upper() != "GO"
    )


def refrescar_resumen_validacion_radicado() -> dict[str, Any]:
    db.execute_sql(_load_refresh_procedure_sql())
    db.execute_sql("EXEC jnc.refrescar_resumen_validacion_radicado")
    total = db.fetch_scalar_sql("SELECT COUNT(*) FROM jnc.resumen_validacion_radicado")
    return {
        "tabla": "jnc.resumen_validacion_radicado",
        "registros": int(total or 0),
    }

