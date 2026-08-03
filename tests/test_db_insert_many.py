import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.load import db
from src.load.prepare_sql_rows import prepare_correo_certificado_rows


class FakeCursor:
    def __init__(self):
        self.fast_executemany = False
        self.calls = []

    def executemany(self, sql, params):
        self.calls.append((sql, params))


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()

    def cursor(self):
        return self.cursor_instance


class InsertManyTests(unittest.TestCase):
    def test_insert_many_splits_rows_and_enables_fast_executemany(self):
        connection = FakeConnection()
        rows = [
            {"id_archivo": "7", "correo": f"persona{index}@example.com"}
            for index in range(5)
        ]

        with (
            patch.object(
                db,
                "get_table_columns",
                return_value={"id_archivo", "correo"},
            ),
            patch.object(
                db,
                "get_table_column_types",
                return_value={"id_archivo": "int", "correo": "nvarchar"},
            ),
            patch.object(
                db,
                "_execute_with_optional_own_connection",
                side_effect=lambda operation: operation(connection),
            ),
        ):
            inserted = db.insert_many(
                "jnc.notificacion_correo_certificado",
                rows,
                fast_executemany=True,
                batch_size=2,
            )

        self.assertEqual(inserted, 5)
        self.assertTrue(connection.cursor_instance.fast_executemany)
        self.assertEqual(
            [len(params) for _, params in connection.cursor_instance.calls],
            [2, 2, 1],
        )
        self.assertEqual(
            connection.cursor_instance.calls[0][1][0],
            (7, "persona0@example.com"),
        )

    def test_insert_many_rejects_non_positive_batch_size(self):
        with self.assertRaisesRegex(ValueError, "batch_size debe ser mayor que cero"):
            db.insert_many(
                "jnc.notificacion_correo_certificado",
                [{"id_archivo": 7}],
                batch_size=0,
            )


class PrepareCorreoRowsTests(unittest.TestCase):
    def test_prepare_correo_omits_redundant_and_full_row_columns(self):
        result = {
            "tabla_correo_certificado": [
                {
                    "numero_linea_csv": 12,
                    "fecha": "2026-07-31",
                    "fecha_2": None,
                    "fecha_3": None,
                    "nombres": "Persona Ejemplo",
                    "correo": "PERSONA@EXAMPLE.COM",
                    "asunto": "Comunicacion de dictamen 123456",
                    "evento": "Acuse",
                    "id": "certificado-1",
                    "adjuntos": "123456.pdf",
                    "numeros_asunto": ["123456"],
                    "numeros_adjuntos": ["123456"],
                }
            ]
        }

        row = prepare_correo_certificado_rows(7125, result)[0]

        self.assertNotIn("nombres", row)
        self.assertNotIn("correo", row)
        self.assertNotIn("asunto_normalizado", row)
        self.assertNotIn("fila_correo_certificado_json", row)
        self.assertEqual(row["destinatario_nombre"], "Persona Ejemplo")
        self.assertEqual(row["destinatario_email"], "PERSONA@EXAMPLE.COM")
        self.assertEqual(row["destinatario_email_normalizado"], "persona@example.com")
        self.assertEqual(row["asunto"], "Comunicacion de dictamen 123456")


if __name__ == "__main__":
    unittest.main()
