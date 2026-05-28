import os
import re
from contextvars import ContextVar
from typing import Any, Callable


ALLOWED_TABLES = {
    "jnc.etl_archivo_cargado",
    "jnc.etl_estructura_hoja",
    "jnc.caso_calificado",
    "jnc.notificacion_esperada",
    "jnc.notificacion_correo_certificado",
    "jnc.etl_error_procesamiento",
    "jnc.etl_ejecucion_regla",
    "jnc.resultado_cruce_notificacion",
}

_COLUMN_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_active_connection: ContextVar[Any | None] = ContextVar("active_sql_connection", default=None)
_table_columns_cache: dict[str, set[str]] = {}


def get_sql_connection_string() -> str:
    connection_string = os.environ.get("SQL_CONNECTION_STRING")
    if connection_string:
        return connection_string

    server = os.environ.get("SQL_SERVER")
    database = os.environ.get("SQL_DATABASE")
    username = os.environ.get("SQL_USERNAME")
    password = os.environ.get("SQL_PASSWORD")
    driver = os.environ.get("SQL_DRIVER", "ODBC Driver 18 for SQL Server")

    missing = [
        name
        for name, value in {
            "SQL_SERVER": server,
            "SQL_DATABASE": database,
            "SQL_USERNAME": username,
            "SQL_PASSWORD": password,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Falta configuracion SQL. Defina SQL_CONNECTION_STRING o estas variables: "
            + ", ".join(missing)
        )

    return (
        f"Driver={{{driver}}};"
        f"Server=tcp:{server},1433;"
        f"Database={database};"
        f"Uid={username};"
        f"Pwd={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )


def get_connection():
    try:
        import pyodbc
    except ImportError as exc:
        raise RuntimeError(
            "pyodbc no esta instalado. Agregue pyodbc a requirements.txt y redeploye la Function."
        ) from exc

    connection = pyodbc.connect(get_sql_connection_string())
    connection.autocommit = False
    return connection


def validate_table_name(table_name: str) -> str:
    schema = os.environ.get("JNC_SQL_SCHEMA", "jnc")
    if "." not in table_name:
        table_name = f"{schema}.{table_name}"

    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"Tabla no permitida para escritura: {table_name}")

    return table_name


def validate_column_name(column_name: str) -> str:
    if not _COLUMN_PATTERN.match(column_name):
        raise ValueError(f"Nombre de columna invalido: {column_name}")

    return column_name


def quote_table_name(table_name: str) -> str:
    validated = validate_table_name(table_name)
    schema_name, object_name = validated.split(".", 1)
    return f"[{schema_name}].[{object_name}]"


def quote_column_name(column_name: str) -> str:
    return f"[{validate_column_name(column_name)}]"


def _get_connection_for_operation():
    active_connection = _active_connection.get()
    if active_connection is not None:
        return active_connection, False

    return get_connection(), True


def _execute_with_optional_own_connection(operation: Callable[[Any], Any]) -> Any:
    connection, owns_connection = _get_connection_for_operation()
    try:
        result = operation(connection)
        if owns_connection:
            connection.commit()
        return result
    except Exception:
        if owns_connection:
            connection.rollback()
        raise
    finally:
        if owns_connection:
            connection.close()


def get_table_columns(table_name: str) -> set[str]:
    validated = validate_table_name(table_name)
    if validated in _table_columns_cache:
        return _table_columns_cache[validated]

    schema_name, object_name = validated.split(".", 1)

    def operation(connection):
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            """,
            schema_name,
            object_name,
        )
        return {row[0] for row in cursor.fetchall()}

    columns = _execute_with_optional_own_connection(operation)
    if not columns:
        raise ValueError(f"No se encontraron columnas para la tabla: {validated}")

    _table_columns_cache[validated] = columns
    return columns


def filter_values_to_table_columns(table_name: str, values: dict[str, Any]) -> dict[str, Any]:
    table_columns = get_table_columns(table_name)
    return {
        column_name: value
        for column_name, value in values.items()
        if column_name in table_columns
    }


def execute_update(table_name: str, key_column: str, key_value: Any, values: dict[str, Any]) -> int:
    values = filter_values_to_table_columns(table_name, values)
    if not values:
        return 0

    quoted_table = quote_table_name(table_name)
    quoted_key = quote_column_name(key_column)
    assignments = ", ".join(
        f"{quote_column_name(column_name)} = ?" for column_name in values
    )
    sql = f"UPDATE {quoted_table} SET {assignments} WHERE {quoted_key} = ?"
    params = list(values.values()) + [key_value]

    def operation(connection):
        cursor = connection.cursor()
        cursor.execute(sql, params)
        return cursor.rowcount if cursor.rowcount is not None else 0

    return _execute_with_optional_own_connection(operation)


def insert_many(table_name: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    quoted_table = quote_table_name(table_name)
    table_columns = get_table_columns(table_name)
    columns = [column_name for column_name in rows[0].keys() if column_name in table_columns]
    if not columns:
        raise ValueError(f"No hay columnas insertables para la tabla: {table_name}")

    column_set = set(columns)
    for row in rows:
        row_columns = {column_name for column_name in row.keys() if column_name in table_columns}
        if row_columns != column_set:
            raise ValueError(
                "Todas las filas de insert_many deben tener las mismas columnas insertables"
            )

    quoted_columns = ", ".join(quote_column_name(column_name) for column_name in columns)
    placeholders = ", ".join("?" for _ in columns)
    sql = f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})"
    params = [tuple(row.get(column_name) for column_name in columns) for row in rows]

    def operation(connection):
        cursor = connection.cursor()
        cursor.fast_executemany = os.environ.get("SQL_FAST_EXECUTEMANY", "").lower() in {
            "1",
            "true",
            "yes",
        }
        cursor.executemany(sql, params)
        return len(rows)

    return _execute_with_optional_own_connection(operation)


def insert_one(table_name: str, row: dict[str, Any]) -> int | None:
    if not row:
        return None

    insert_many(table_name, [row])
    return None


def delete_by_archivo(table_name: str, id_archivo: int) -> int:
    quoted_table = quote_table_name(table_name)
    sql = f"DELETE FROM {quoted_table} WHERE [id_archivo] = ?"

    def operation(connection):
        cursor = connection.cursor()
        cursor.execute(sql, id_archivo)
        return cursor.rowcount if cursor.rowcount is not None else 0

    return _execute_with_optional_own_connection(operation)


def fetch_rows(
    table_name: str,
    columns: list[str],
    where: str,
    params: list[Any] | tuple[Any, ...],
) -> list[dict[str, Any]]:
    quoted_table = quote_table_name(table_name)
    quoted_columns = ", ".join(quote_column_name(column_name) for column_name in columns)
    sql = f"SELECT {quoted_columns} FROM {quoted_table} WHERE {where}"

    def operation(connection):
        cursor = connection.cursor()
        cursor.execute(sql, params)
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    return _execute_with_optional_own_connection(operation)


def insert_many_returning_ids(
    table_name: str,
    rows: list[dict[str, Any]],
    identity_column: str,
    lookup_columns: list[str],
) -> dict[tuple[Any, ...], int]:
    inserted = insert_many(table_name, rows)
    if inserted == 0:
        return {}

    if not rows:
        return {}

    if "id_archivo" not in rows[0]:
        raise ValueError("insert_many_returning_ids requiere id_archivo en las filas")

    id_archivo = rows[0]["id_archivo"]
    columns = [identity_column, *lookup_columns]
    fetched = fetch_rows(table_name, columns, "[id_archivo] = ?", [id_archivo])
    return {
        tuple(row.get(column_name) for column_name in lookup_columns): row[identity_column]
        for row in fetched
    }


def run_in_transaction(callback: Callable[[], Any]) -> Any:
    connection = get_connection()
    token = _active_connection.set(connection)
    try:
        result = callback()
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        _active_connection.reset(token)
        connection.close()
