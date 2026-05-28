CASO_FIELD_MAP: dict[str, str] = {
    "pestana_nombre": "pestana_nombre",
    "pestana_sala_normalizada": "pestana_sala_normalizada",
    "hoja_trabajo_sala_normalizada": "hoja_trabajo_sala_normalizada",
    "numero_radicado": "numero_radicado",
    "nombre_del_paciente": "nombre_paciente",
    "fecha_pago_dictamen": "fecha_pago_dictamen",
    "correo_guia": "correo_guia",
}


NOTIFICACION_FIELD_MAP: dict[str, str] = {
    "numero_radicado": "numero_radicado",
    "cedula": "cedula",
    "entidad": "tipo_destinatario",
    "fecha_envio": "fecha_envio_reportada",
    "fecha_recibido": "fecha_recibido_reportada",
    "correo": "correo_o_guia_reportado",
    "pestana_nombre": "pestana_nombre",
    "pestana_fecha": "pestana_fecha",
    "pestana_sala_normalizada": "pestana_sala_normalizada",
    "hoja_trabajo_sala_normalizada": "hoja_trabajo_sala_normalizada",
    "hoja_trabajo_fecha_audiencia": "hoja_trabajo_fecha_audiencia",
}


ESTRUCTURA_HOJA_FIELD_MAP: dict[str, str] = {
    "pestana_nombre": "pestana_nombre",
    "pestana_nombre_normalizado": "pestana_nombre_normalizado",
    "pestana_fecha": "pestana_fecha",
    "pestana_fecha_original": "pestana_fecha_original",
    "pestana_sala_original": "pestana_sala_original",
    "pestana_sala_normalizada": "pestana_sala_normalizada",
    "hoja_trabajo_sala_original": "hoja_trabajo_sala_original",
    "hoja_trabajo_sala": "hoja_trabajo_sala",
    "hoja_trabajo_sala_normalizada": "hoja_trabajo_sala_normalizada",
    "hoja_trabajo_sala_celda": "hoja_trabajo_sala_celda",
    "hoja_trabajo_fecha_audiencia": "hoja_trabajo_fecha_audiencia",
    "hoja_trabajo_fecha_audiencia_original": "hoja_trabajo_fecha_audiencia_original",
    "hoja_trabajo_fecha_audiencia_celda": "hoja_trabajo_fecha_audiencia_celda",
    "fila_encabezado_wide": "fila_encabezado_wide",
    "fila_encabezado_detalle": "fila_encabezado_detalle",
    "estructura_valida": "estructura_valida",
    "estructura_cumplimiento": "estructura_cumplimiento",
    "estructura_umbral": "estructura_umbral",
    "estructura_campos_esperados": "estructura_campos_esperados",
    "estructura_campos_encontrados": "estructura_campos_encontrados",
    "fila_encabezado_wide_terminos": "fila_encabezado_wide_terminos_json",
    "fila_encabezado_detalle_terminos": "fila_encabezado_detalle_terminos_json",
    "ubicacion_columnas_wide": "ubicacion_columnas_wide_json",
    "ubicacion_columnas_detalle": "ubicacion_columnas_detalle_json",
    "estructura_faltantes": "estructura_faltantes_json",
}


CORREO_CERTIFICADO_FIELD_MAP: dict[str, str] = {
    "numero_linea_csv": "numero_linea_csv",
    "fecha": "fecha",
    "fecha_2": "fecha_2",
    "fecha_3": "fecha_3",
    "nombres": "destinatario_nombre",
    "correo": "destinatario_email",
    "asunto": "asunto",
    "adjuntos": "adjuntos",
    "numeros_asunto": "numeros_asunto_json",
    "numeros_adjuntos": "numeros_adjuntos_json",
}


ESTRUCTURA_HOJA_JSON_FIELDS: set[str] = {
    "fila_encabezado_wide_terminos_json",
    "fila_encabezado_detalle_terminos_json",
    "ubicacion_columnas_wide_json",
    "ubicacion_columnas_detalle_json",
    "estructura_faltantes_json",
}


CORREO_CERTIFICADO_JSON_FIELDS: set[str] = {
    "numeros_asunto_json",
    "numeros_adjuntos_json",
}
