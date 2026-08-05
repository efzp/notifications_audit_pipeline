import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import procesador_correo_pdf
from src.load.prepare_sql_rows import prepare_correo_certificado_rows
from src.load.write_correo import write_correo_pdf_result_to_sql


PDF_NAME = (
    "36 T COMUNICACI\u00d3N DICTAMEN ADALCY JEANNETH ORTEGA APARICIO "
    "CC 52450952 AFP.pdf"
)
PDF_TEXT = """
Estado/StatusdeEntrega
Direcci\u00f3n Estado/Statusde Entrega
recepcion@example.com EntregadoaCasilleroPostal
Detalles Entregado(UTC*) Entregado(local) Apertura(local)
07/24/2026 07/24/2026
*UTCrepresentaTiempoUniversalCoordinado
Sobre del Mensaje
Asunto: Comunicaci\u00f3n dictamen ADALCY CC 52450952
Para: <recepcion@example.com>
N\u00famero de Seguimiento/Tracking: 59F74C64F5C9F12927C0119B988E3E52BE616C4A
RecibidoporSistemaRMail: 07/24/202611:53:28PM(UTC),07/24/202606:53:28PM(Local)
"""


class ProcesadorCorreoPdfTests(unittest.TestCase):
    def test_pdf_genera_exactamente_una_fila_y_conserva_nombre(self):
        payload = {
            "tipo_archivo": "CORREO_CERTIFICADO_PDF",
            "nombre_archivo": PDF_NAME,
            "ruta_sharepoint": "/entrada/correos",
            "identifier": "sharepoint-item-1",
            "file_content_base64": base64.b64encode(b"%PDF-test").decode("ascii"),
        }

        with patch.object(
            procesador_correo_pdf,
            "_extract_pdf_text",
            return_value=(PDF_TEXT, 2),
        ):
            result = procesador_correo_pdf.process_payload_data(payload)

        self.assertEqual(result["total_filas_correo_certificado"], 1)
        self.assertEqual(len(result["tabla_correo_certificado"]), 1)
        row = result["tabla_correo_certificado"][0]
        self.assertEqual(row["nombre_archivo"], PDF_NAME)
        self.assertEqual(row["cedula_detectada"], "52450952")
        self.assertEqual(row["tipo_destinatario_detectado"], "AFP")
        self.assertEqual(row["evento"], "Acuse de recibo")
        self.assertEqual(row["fecha"], "2026-07-24")
        self.assertEqual(row["fecha_2"], "2026-07-24")
        self.assertIsNone(row["fecha_3"])
        self.assertFalse(result["_recalcular_cruce"])

    def test_mapping_sql_incluye_nombre_sin_duplicar_fila_completa(self):
        result = {
            "tabla_correo_certificado": [
                {
                    "numero_linea_csv": 1,
                    "fecha": "2026-07-24",
                    "fecha_2": "2026-07-24",
                    "fecha_3": None,
                    "correo": "recepcion@example.com",
                    "asunto": "COMUNICACION DICTAMEN CC 52450952",
                    "asunto_normalizado": "comunicacion_dictamen_cc_52450952",
                    "evento": "Acuse de recibo",
                    "id": "TRACKING-1",
                    "nombre_archivo": PDF_NAME,
                    "fila_correo_certificado": {"cedula_detectada": "52450952"},
                }
            ]
        }

        row = prepare_correo_certificado_rows(9001, result)[0]

        self.assertEqual(row["nombre_archivo"], PDF_NAME)
        self.assertNotIn("fila_correo_certificado_json", row)
        self.assertNotIn("asunto_normalizado", row)

    def test_writer_pdf_fuerza_omitir_recalculo(self):
        result = {"_recalcular_cruce": True}
        with patch(
            "src.load.write_correo.write_correo_result_to_sql",
            return_value={"status": "OK"},
        ) as writer:
            response = write_correo_pdf_result_to_sql(9001, result)

        self.assertEqual(response, {"status": "OK"})
        self.assertFalse(writer.call_args.args[1]["_recalcular_cruce"])


if __name__ == "__main__":
    unittest.main()
