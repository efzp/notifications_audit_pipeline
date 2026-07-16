from typing import Any

from src.load import db


def refrescar_resumen_validacion_radicado() -> dict[str, Any]:
    db.execute_sql("EXEC jnc.refrescar_resumen_validacion_radicado")
    total = db.fetch_scalar_sql("SELECT COUNT(*) FROM jnc.resumen_validacion_radicado")
    return {
        "tabla": "jnc.resumen_validacion_radicado",
        "registros": int(total or 0),
    }

