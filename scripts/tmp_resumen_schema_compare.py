import re
from pathlib import Path

import pyodbc


def load_local_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path(".env.local").read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#") or "=" not in clean:
            continue
        key, value = clean.split("=", 1)
        values[key] = value
    return values


def insert_columns_from_migration() -> list[str]:
    text = Path("sql/migrations/20260531_create_resumen_validacion_radicado.sql").read_text(
        encoding="utf-8"
    )
    match = re.search(
        r"INSERT\s+INTO\s+jnc\.resumen_validacion_radicado\s*\((.*?)\)\s*SELECT",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise RuntimeError("No se encontro el INSERT del resumen.")
    return [
        col.strip().strip("[]")
        for col in match.group(1).split(",")
        if col.strip()
    ]


def main() -> None:
    env = load_local_env()
    driver = env.get("AZURE_SQL_DRIVER", "ODBC Driver 18 for SQL Server")
    connection_string = (
        f"Driver={{{driver}}};"
        f"Server=tcp:{env['AZURE_SQL_SERVER']},1433;"
        f"Database={env['AZURE_SQL_DATABASE']};"
        f"Uid={env['AZURE_SQL_USER']};"
        f"Pwd={env['AZURE_SQL_PASSWORD']};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    calculated = insert_columns_from_migration()
    calculated_set = set(calculated)
    technical_keep = {"id_resumen_validacion"}

    with pyodbc.connect(connection_string) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                c.COLUMN_NAME,
                c.ORDINAL_POSITION,
                c.DATA_TYPE,
                c.IS_NULLABLE,
                c.COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS AS c
            WHERE c.TABLE_SCHEMA = 'jnc'
              AND c.TABLE_NAME = 'resumen_validacion_radicado'
            ORDER BY c.ORDINAL_POSITION
            """
        )
        schema_rows = cursor.fetchall()

    schema_columns = [row.COLUMN_NAME for row in schema_rows]
    not_calculated = [
        column for column in schema_columns if column not in calculated_set | technical_keep
    ]

    print("CALCULATED_COLUMNS")
    for column in calculated:
        print(column)

    print("SCHEMA_COLUMNS")
    for row in schema_rows:
        print(
            "|".join(
                [
                    str(row.COLUMN_NAME),
                    str(row.ORDINAL_POSITION),
                    str(row.DATA_TYPE),
                    str(row.IS_NULLABLE),
                    "" if row.COLUMN_DEFAULT is None else str(row.COLUMN_DEFAULT),
                ]
            )
        )

    print("NOT_CALCULATED_COLUMNS")
    for column in not_calculated:
        print(column)


if __name__ == "__main__":
    main()
