import base64
import unittest

from procesador_correo import process_payload_data


HEADERS = (
    "Nombres - Email,Fecha,Asunto,Evento,Razon,Agente/Identidad,Id,"
    "Cantidad Adjuntos,Meta-datas,Peso de Adjuntos,Unidades,Adjuntos\n"
)


def payload_for(csv_text: str) -> dict:
    return {
        "tipo_archivo": "CORREO_CERTIFICADO",
        "nombre_archivo": "correo.csv",
        "ruta_sharepoint": "entrada/correo.csv",
        "identifier": "correo.csv",
        "file_content_base64": base64.b64encode(csv_text.encode("utf-8")).decode("ascii"),
    }


class ProcesadorCorreoTests(unittest.TestCase):
    def test_procesa_fila_bien_alineada(self):
        row = (
            '"Persona (persona@example.com)",'
            '"2026-05-28 07:39:02 / 2026-05-28 07:40:00",'
            '"COMUNICACION DICTAMEN PERSONA CC 44153084",'
            '"Lectura del mensaje",OK,agente@example.com,123,1,,100,KB,'
            '"35 DICTAMEN PERSONA CC 44153084.pdf"\n'
        )

        result = process_payload_data(payload_for(HEADERS + row))

        self.assertEqual(result["filas_corregidas_correo_certificado"], 0)
        self.assertEqual(result["filas_rechazadas_correo_certificado"], 0)
        self.assertEqual(len(result["tabla_correo_certificado"]), 1)
        parsed = result["tabla_correo_certificado"][0]
        self.assertEqual(parsed["fecha"], "2026-05-28")
        self.assertEqual(parsed["fecha_2"], "2026-05-28")
        self.assertEqual(parsed["correo"], "persona@example.com")
        self.assertEqual(parsed["evento"], "Lectura del mensaje")

    def test_repara_coma_no_escapada_en_nombres_email(self):
        row = (
            'ZULEIMA PATRICIA,PADILLA (zuleima@example.com),'
            '"2026-05-28 07:39:02 / 2026-05-28 07:40:00",'
            '"CONSTANCIA DE ASISTENCIA VALORACION VIRTUAL ZULEIMA 44153084",'
            '"Lectura del mensaje",OK,agente@example.com,456,1,,100,KB,'
            '"CONSTANCIA ZULEIMA 44153084.pdf"\n'
        )

        result = process_payload_data(payload_for(HEADERS + row))

        self.assertEqual(result["filas_corregidas_correo_certificado"], 1)
        self.assertEqual(result["filas_rechazadas_correo_certificado"], 0)
        parsed = result["tabla_correo_certificado"][0]
        self.assertEqual(parsed["nombres"], "ZULEIMA PATRICIA, PADILLA")
        self.assertEqual(parsed["correo"], "zuleima@example.com")
        self.assertEqual(parsed["asunto"], "CONSTANCIA DE ASISTENCIA VALORACION VIRTUAL ZULEIMA 44153084")
        self.assertEqual(parsed["evento"], "Lectura del mensaje")
        self.assertEqual(parsed["id"], "456")
        self.assertEqual(parsed["adjuntos"], "CONSTANCIA ZULEIMA 44153084.pdf")

    def test_rechaza_fila_que_sigue_desplazada(self):
        row = (
            '"Persona (persona@example.com)",2026-05-28,'
            '"2026-05-28 07:39:02 / 2026-05-28 07:40:00",'
            '"CONSTANCIA DE ASISTENCIA VALORACION VIRTUAL 44153084",'
            'OK,agente@example.com,789,1,,100,KB,1\n'
        )

        result = process_payload_data(payload_for(HEADERS + row))

        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(result["filas_rechazadas_correo_certificado"], 1)
        self.assertEqual(result["tabla_correo_certificado"], [])
        self.assertEqual(
            result["mensaje_error"][0]["tipo_error"],
            "fila_correo_certificado_invalida",
        )


if __name__ == "__main__":
    unittest.main()
