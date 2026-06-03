CASO_FIELD_MAP: dict[str, str] = {
    "pestana_nombre": "pestana_nombre",
    "pestana_fecha": "pestana_fecha",
    "pestana_sala_normalizada": "pestana_sala_normalizada",
    "hoja_trabajo_sala": "hoja_trabajo_sala",
    "hoja_trabajo_sala_normalizada": "hoja_trabajo_sala_normalizada",
    "hoja_trabajo_fecha_audiencia": "hoja_trabajo_fecha_audiencia",
    "numero_radicado": "numero_radicado",
    "cedula": "cedula",
    "nombre_del_paciente": "nombre_paciente",
    "entidad_remitente": "entidad_remitente",
    "regional": "regional",
    "medico_ponente": "medico_ponente",
    "medico_principal": "medico_principal",
    "responsable_del_pago": "responsable_pago",
    "pago_entidad": "pago_entidad",
    "rp": "rp",
    "terapeuta_o_psicologa": "terapeuta_psicologa",
    "fecha_pago_dictamen": "fecha_pago_dictamen",
    "valor": "valor_reportado",
    "correo_guia": "correo_guia",
    "eps": "eps",
    "afp": "afp",
    "arl": "arl",
    "aseguradoras": "asegurado",
    "comentarios_excel": "comentarios_excel",
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
    "hoja_trabajo_sala": "hoja_trabajo_sala",
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
    "evento": "estado_correo",
    "id": "codigo_certificado",
    "adjuntos": "adjuntos",
    "numeros_asunto": "numeros_asunto_json",
    "numeros_adjuntos": "numeros_adjuntos_json",
}


ESTRUCTURA_HOJA_JSON_FIELDS: set[str] = {
    "ubicacion_columnas_wide_json",
    "ubicacion_columnas_detalle_json",
    "estructura_faltantes_json",
}


CORREO_CERTIFICADO_JSON_FIELDS: set[str] = {
    "numeros_asunto_json",
    "numeros_adjuntos_json",
}
