import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.load import db


def load_local_env(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def fetch_one(cursor, sql: str) -> dict[str, object]:
    cursor.execute(sql)
    columns = [column[0] for column in cursor.description]
    row = cursor.fetchone()
    return dict(zip(columns, row, strict=True)) if row else {}


def fetch_all(cursor, sql: str) -> list[dict[str, object]]:
    cursor.execute(sql)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def print_section(title: str, rows: list[dict[str, object]]) -> None:
    print(f"\n[{title}]")
    if not rows:
        print("Sin resultados")
        return
    for row in rows:
        print(" | ".join(f"{key}={value}" for key, value in row.items()))


def main() -> None:
    load_local_env(REPO_ROOT / ".env")

    connection = db.get_connection()
    try:
        cursor = connection.cursor()

        identity = fetch_one(
            cursor,
            """
            SELECT
                DB_NAME() AS base_datos,
                ORIGINAL_LOGIN() AS login_original,
                USER_NAME() AS usuario_base_datos
            """,
        )
        print_section("conexion", [identity])

        permissions = fetch_one(
            cursor,
            """
            SELECT
                HAS_PERMS_BY_NAME('jnc', 'SCHEMA', 'SELECT') AS [select],
                HAS_PERMS_BY_NAME('jnc', 'SCHEMA', 'INSERT') AS [insert],
                HAS_PERMS_BY_NAME('jnc', 'SCHEMA', 'UPDATE') AS [update],
                HAS_PERMS_BY_NAME('jnc', 'SCHEMA', 'DELETE') AS [delete],
                HAS_PERMS_BY_NAME('jnc', 'SCHEMA', 'EXECUTE') AS [execute],
                HAS_PERMS_BY_NAME('jnc', 'SCHEMA', 'ALTER') AS [alter],
                HAS_PERMS_BY_NAME(
                    'jnc', 'SCHEMA', 'VIEW DEFINITION'
                ) AS view_definition
            """,
        )
        print_section("permisos_esquema_jnc", [permissions])

        tables = fetch_all(
            cursor,
            """
            SELECT
                t.name AS tabla,
                COUNT(c.column_id) AS columnas
            FROM sys.tables AS t
            INNER JOIN sys.schemas AS s
                ON s.schema_id = t.schema_id
            LEFT JOIN sys.columns AS c
                ON c.object_id = t.object_id
            WHERE s.name = 'jnc'
            GROUP BY t.name
            ORDER BY t.name
            """,
        )
        print_section("tablas_visibles", tables)

        procedure = fetch_one(
            cursor,
            """
            DECLARE @definition NVARCHAR(MAX) = OBJECT_DEFINITION(
                OBJECT_ID('jnc.refrescar_resumen_validacion_radicado')
            );

            SELECT
                CASE WHEN @definition IS NULL THEN 0 ELSE 1 END AS visible,
                CASE WHEN @definition LIKE '%ON ne.id_caso = cc.id_caso%'
                     THEN 1 ELSE 0 END AS relacion_directa_id_caso,
                CASE WHEN @definition LIKE
                    '%csc.cedula_normalizada = cc.cedula_normalizada%'
                     THEN 1 ELSE 0 END AS condicion_incorrecta_cedula,
                CASE WHEN @definition LIKE '%AND EXISTS (%'
                     THEN 1 ELSE 0 END AS exists_correlacionado
            """,
        )
        print_section("procedimiento_refresco", [procedure])
    finally:
        connection.close()


if __name__ == "__main__":
    main()
