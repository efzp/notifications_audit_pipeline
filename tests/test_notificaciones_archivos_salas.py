import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.load import db
from src.reconcile.notificaciones import (
    _fetch_expected_rows,
    _normalize_id_archivos_salas,
    _refresh_cruce_notificacion_pendiente,
)


class NormalizeArchivosSalasTests(unittest.TestCase):
    def test_conserva_compatibilidad_con_id_singular(self):
        self.assertEqual(_normalize_id_archivos_salas(6494, None), [6494])

    def test_normaliza_lista_y_elimina_duplicados(self):
        self.assertEqual(
            _normalize_id_archivos_salas(None, [7039, "7060", 7039]),
            [7039, 7060],
        )

    def test_rechaza_id_singular_y_lista_simultaneos(self):
        with self.assertRaisesRegex(ValueError, "pero no ambos"):
            _normalize_id_archivos_salas(6494, [7039])

    def test_rechaza_lista_vacia_o_valores_no_positivos(self):
        with self.assertRaisesRegex(ValueError, "no puede estar vacia"):
            _normalize_id_archivos_salas(None, [])
        with self.assertRaisesRegex(ValueError, "enteros positivos"):
            _normalize_id_archivos_salas(None, [0])


class FetchExpectedRowsArchivosSalasTests(unittest.TestCase):
    def test_filtra_notificaciones_con_in_parametrizado(self):
        table_columns = {
            "id_notificacion_esperada",
            "id_archivo",
            "activo",
            "estado_revision_notificacion",
        }

        with (
            patch.object(db, "get_table_columns", return_value=table_columns),
            patch.object(db, "fetch_rows", return_value=[]) as fetch_rows,
        ):
            result = _fetch_expected_rows(
                None,
                solo_pendientes_filter=True,
                id_archivos_salas=[5499, 5500, 5501],
            )

        self.assertEqual(result, [])
        _, columns, where, params = fetch_rows.call_args.args
        self.assertEqual(
            columns,
            ["id_notificacion_esperada", "id_archivo", "activo", "estado_revision_notificacion"],
        )
        self.assertIn("[id_archivo] IN (?, ?, ?)", where)
        self.assertIn(
            "COALESCE([estado_revision_notificacion], 'SIN_REVISION') <> ?",
            where,
        )
        self.assertEqual(params, [5499, 5500, 5501, "CUMPLE"])


class RefreshPendientesScopeTests(unittest.TestCase):
    def test_lista_vacia_no_dispara_refresco_global(self):
        with (
            patch.object(db, "execute_sql") as execute_sql,
            patch.object(db, "delete_all") as delete_all,
        ):
            result = _refresh_cruce_notificacion_pendiente(
                id_archivo=None,
                id_notificacion_esperada_values=[],
            )

        self.assertEqual(
            result,
            {
                "pendientes_eliminados": 0,
                "pendientes_insertados": 0,
            },
        )
        execute_sql.assert_not_called()
        delete_all.assert_not_called()


if __name__ == "__main__":
    unittest.main()
