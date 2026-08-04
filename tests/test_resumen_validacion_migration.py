import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    REPO_ROOT
    / "sql"
    / "migrations"
    / "20260803_optimize_refrescar_resumen_validacion_radicado.sql"
)


class ResumenValidacionMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION_PATH.read_text(encoding="utf-8")

    def test_resuelve_sala_por_radicado_sin_cedula_del_caso(self):
        self.assertIn(
            "csc.numero_radicado_normalizado = cc.numero_radicado_normalizado",
            self.sql,
        )
        self.assertNotIn(
            "csc.cedula_normalizada = cc.cedula_normalizada",
            self.sql,
        )

    def test_relaciona_notificaciones_directamente_por_id_caso(self):
        self.assertIn("ON ne.id_caso = cc.id_caso", self.sql)
        self.assertNotIn("AND EXISTS (", self.sql)

    def test_crea_indices_de_soporte(self):
        self.assertIn(
            "IX_calificacion_sistema_caso_resumen_radicado",
            self.sql,
        )
        self.assertIn("IX_notificacion_esperada_resumen_id_caso", self.sql)
        self.assertIn("IX_audiencia_caso_resumen_radicado", self.sql)

    def test_indice_audiencia_no_usa_fecha_calculada_no_determinista(self):
        index_start = self.sql.index(
            "CREATE INDEX IX_audiencia_caso_resumen_radicado"
        )
        index_end = self.sql.index("END;", index_start)
        index_sql = self.sql[index_start:index_end]

        self.assertIn("numero_radicado_normalizado", index_sql)
        self.assertIn("id_audiencia_caso DESC", index_sql)
        self.assertNotIn("fecha_audiencia", index_sql)


if __name__ == "__main__":
    unittest.main()
