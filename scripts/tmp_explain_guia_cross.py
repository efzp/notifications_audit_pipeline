import os
import sys

sys.path.insert(0, os.getcwd())

from src.load import db

RADICADO = "JN02202605509"
DOCUMENTO = "1299392"


def load_env_local() -> None:
    if not os.path.exists(".env.local"):
        return
    with open(".env.local", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def configure_connection() -> None:
    load_env_local()
    aliases = {
        "SQL_SERVER": "AZURE_SQL_SERVER",
        "SQL_DATABASE": "AZURE_SQL_DATABASE",
        "SQL_USERNAME": "AZURE_SQL_USER",
        "SQL_PASSWORD": "AZURE_SQL_PASSWORD",
    }
    for target_key, source_key in aliases.items():
        if not os.environ.get(target_key) and os.environ.get(source_key):
            os.environ[target_key] = os.environ[source_key]

    os.environ["SQL_CONNECTION_STRING"] = (
        "Driver={SQL Server};"
        f"Server=tcp:{os.environ['SQL_SERVER']},1433;"
        f"Database={os.environ['SQL_DATABASE']};"
        f"Uid={os.environ['SQL_USERNAME']};"
        f"Pwd={os.environ['SQL_PASSWORD']};"
        "Connection Timeout=30;"
    )


def fetch(sql: str, params: list[str]) -> list[dict]:
    connection = db.get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(sql, params)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        connection.close()


configure_connection()

guia_columns = db.get_table_columns("jnc.guia_correo_fisico")
date_selects = []
date_order = []
for column_name in ("fec_entrega", "fecha_entrega"):
    if column_name in guia_columns:
        date_selects.append(f"g.{column_name}")
        date_order.append(f"g.{column_name}")

queries = {
    "expected_summary": (
        """
        SELECT
            ne.numero_radicado_normalizado,
            ne.cedula,
            ne.cedula_normalizada,
            ne.tipo_destinatario,
            COUNT(*) AS notificaciones,
            ne.estado_revision_notificacion,
            ne.pendiente_revision,
            MIN(ne.fecha_envio_reportada) AS min_fecha_envio_reportada,
            MAX(ne.hoja_trabajo_fecha_audiencia) AS fecha_audiencia
        FROM jnc.notificacion_esperada AS ne
        WHERE ne.activo = 1
          AND ne.numero_radicado_normalizado = ?
        GROUP BY
            ne.numero_radicado_normalizado,
            ne.cedula,
            ne.cedula_normalizada,
            ne.tipo_destinatario,
            ne.estado_revision_notificacion,
            ne.pendiente_revision
        ORDER BY
            ne.tipo_destinatario
        """,
        [RADICADO],
    ),
    "cruce_summary": (
        """
        SELECT
            rcn.numero_radicado_normalizado,
            rcn.cedula,
            rcn.cedula_normalizada,
            rcn.tipo_destinatario,
            rcn.estado_revision_notificacion,
            rcn.descripcion_revision,
            JSON_VALUE(rcn.detalle_revision_json, '$.fuente_revision') AS fuente_revision,
            JSON_VALUE(rcn.detalle_revision_json, '$.guia_fisica.aplica') AS guia_aplica,
            JSON_VALUE(rcn.detalle_revision_json, '$.guia_fisica.cedula_esperada') AS cedula_esperada,
            COUNT(*) AS cruces
        FROM jnc.resultado_cruce_notificacion AS rcn
        WHERE rcn.activo = 1
          AND rcn.numero_radicado_normalizado = ?
        GROUP BY
            rcn.numero_radicado_normalizado,
            rcn.cedula,
            rcn.cedula_normalizada,
            rcn.tipo_destinatario,
            rcn.estado_revision_notificacion,
            rcn.descripcion_revision,
            JSON_VALUE(rcn.detalle_revision_json, '$.fuente_revision'),
            JSON_VALUE(rcn.detalle_revision_json, '$.guia_fisica.aplica'),
            JSON_VALUE(rcn.detalle_revision_json, '$.guia_fisica.cedula_esperada')
        ORDER BY
            rcn.tipo_destinatario
        """,
        [RADICADO],
    ),
    "guia_documento": (
        f"""
        SELECT TOP (50)
            g.id_guia_correo_fisico,
            g.id_archivo,
            g.hoja_origen,
            g.guia,
            g.cartaporte,
            g.estado,
            g.des_estadog,
            {", ".join(date_selects) + "," if date_selects else ""}
            g.ced_destinatario,
            g.ced_destinatario_normalizada,
            g.numero_documento
        FROM jnc.guia_correo_fisico AS g
        WHERE REPLACE(REPLACE(REPLACE(CONVERT(NVARCHAR(100), g.numero_documento), '.', ''), ',', ''), ' ', '') = ?
           OR REPLACE(REPLACE(REPLACE(CONVERT(NVARCHAR(100), g.ced_destinatario), '.', ''), ',', ''), ' ', '') = ?
           OR REPLACE(REPLACE(REPLACE(CONVERT(NVARCHAR(100), g.ced_destinatario_normalizada), '.', ''), ',', ''), ' ', '') = ?
        ORDER BY
            {", ".join(date_order) + "," if date_order else ""}
            g.id_guia_correo_fisico
        """,
        [DOCUMENTO, DOCUMENTO, DOCUMENTO],
    ),
}

for name, (sql, params) in queries.items():
    print(f"## {name}")
    rows = fetch(sql, params)
    print(f"rows={len(rows)}")
    for row in rows:
        print(row)
