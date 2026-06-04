/*
Reset total del pipeline JNC Notificaciones en DEV.

ADVERTENCIA:
- Este script elimina las tablas operativas del esquema jnc y todos sus datos.
- Usar solo si se van a correr nuevamente los flujos desde cero.
- Ejecutar en la base correcta: sqldb-jnc-notif-dev.
*/

SET XACT_ABORT ON;

IF DB_NAME() <> 'sqldb-jnc-notif-dev'
BEGIN
    THROW 50001, 'Ejecute este script en sqldb-jnc-notif-dev.', 1;
END;

BEGIN TRANSACTION;

IF SCHEMA_ID('jnc') IS NULL
BEGIN
    EXEC('CREATE SCHEMA jnc');
END;

DECLARE @drop_fk_sql NVARCHAR(MAX);

SELECT @drop_fk_sql = STRING_AGG(
    N'ALTER TABLE '
    + QUOTENAME(OBJECT_SCHEMA_NAME(fk.parent_object_id))
    + N'.'
    + QUOTENAME(OBJECT_NAME(fk.parent_object_id))
    + N' DROP CONSTRAINT '
    + QUOTENAME(fk.name)
    + N';',
    CHAR(10)
)
FROM sys.foreign_keys AS fk
WHERE fk.referenced_object_id IN (
    OBJECT_ID('jnc.resumen_validacion_radicado'),
    OBJECT_ID('jnc.resultado_cruce_notificacion'),
    OBJECT_ID('jnc.notificacion_esperada'),
    OBJECT_ID('jnc.notificacion_correo_certificado'),
    OBJECT_ID('jnc.audiencia_caso'),
    OBJECT_ID('jnc.etl_estructura_acta'),
    OBJECT_ID('jnc.caso_calificado'),
    OBJECT_ID('jnc.etl_estructura_hoja'),
    OBJECT_ID('jnc.etl_error_procesamiento'),
    OBJECT_ID('jnc.etl_ejecucion_regla'),
    OBJECT_ID('jnc.etl_archivo_cargado')
)
OR fk.parent_object_id IN (
    OBJECT_ID('jnc.resumen_validacion_radicado'),
    OBJECT_ID('jnc.resultado_cruce_notificacion'),
    OBJECT_ID('jnc.notificacion_esperada'),
    OBJECT_ID('jnc.notificacion_correo_certificado'),
    OBJECT_ID('jnc.audiencia_caso'),
    OBJECT_ID('jnc.etl_estructura_acta'),
    OBJECT_ID('jnc.caso_calificado'),
    OBJECT_ID('jnc.etl_estructura_hoja'),
    OBJECT_ID('jnc.etl_error_procesamiento'),
    OBJECT_ID('jnc.etl_ejecucion_regla'),
    OBJECT_ID('jnc.etl_archivo_cargado')
);

IF @drop_fk_sql IS NOT NULL AND @drop_fk_sql <> N''
BEGIN
    EXEC sp_executesql @drop_fk_sql;
END;

DROP TABLE IF EXISTS jnc.resumen_validacion_radicado;
DROP TABLE IF EXISTS jnc.resultado_cruce_notificacion;
DROP TABLE IF EXISTS jnc.notificacion_esperada;
DROP TABLE IF EXISTS jnc.notificacion_correo_certificado;
DROP TABLE IF EXISTS jnc.audiencia_caso;
DROP TABLE IF EXISTS jnc.etl_estructura_acta;
DROP TABLE IF EXISTS jnc.caso_calificado;
DROP TABLE IF EXISTS jnc.etl_estructura_hoja;
DROP TABLE IF EXISTS jnc.etl_error_procesamiento;
DROP TABLE IF EXISTS jnc.etl_ejecucion_regla;
DROP TABLE IF EXISTS jnc.etl_archivo_cargado;

CREATE TABLE jnc.etl_archivo_cargado (
    id_archivo INT IDENTITY(1,1) NOT NULL
        CONSTRAINT PK_etl_archivo_cargado PRIMARY KEY,
    tipo_archivo NVARCHAR(100) NULL,
    nombre_archivo NVARCHAR(500) NULL,
    extension_archivo NVARCHAR(50) NULL,
    ruta_sharepoint NVARCHAR(1000) NULL,
    carpeta_origen NVARCHAR(1000) NULL,
    carpeta_destino NVARCHAR(1000) NULL,
    fecha_llegada DATETIME2(0) NULL,
    fecha_fin_proceso DATETIME2(0) NULL,
    hash_archivo NVARCHAR(64) NULL,
    tamano_bytes BIGINT NULL,
    estado_proceso NVARCHAR(100) NULL,
    contiene_informacion_nueva BIT NULL,
    usuario_carga NVARCHAR(255) NULL,
    mensaje_error NVARCHAR(MAX) NULL,
    fecha_creacion DATETIME2(0) NOT NULL
        CONSTRAINT DF_etl_archivo_cargado_fecha_creacion DEFAULT (SYSUTCDATETIME()),
    fecha_actualizacion DATETIME2(0) NULL,
    estructura_valida BIT NULL,
    hojas_detectadas INT NULL,
    hojas_validas INT NULL,
    casos_detectados INT NULL,
    notificaciones_detectadas INT NULL,
    diccionario_estandar_columnas_json NVARCHAR(MAX) NULL,
    procesador_status NVARCHAR(100) NULL,
    entradas_xlsx INT NULL,
    delimitador_csv NVARCHAR(10) NULL,
    encabezados_originales_json NVARCHAR(MAX) NULL,
    encabezados_normalizados_json NVARCHAR(MAX) NULL,
    total_filas_correo_certificado INT NULL,
    total_actas_audiencia_pdf INT NULL
);

CREATE TABLE jnc.etl_estructura_hoja (
    id_estructura_hoja INT IDENTITY(1,1) NOT NULL
        CONSTRAINT PK_etl_estructura_hoja PRIMARY KEY,
    id_archivo INT NOT NULL,
    pestana_nombre NVARCHAR(255) NULL,
    pestana_nombre_normalizado NVARCHAR(255) NULL,
    pestana_fecha DATE NULL,
    pestana_fecha_original NVARCHAR(100) NULL,
    pestana_sala_original NVARCHAR(255) NULL,
    pestana_sala_normalizada NVARCHAR(255) NULL,
    hoja_trabajo_sala_original NVARCHAR(255) NULL,
    hoja_trabajo_sala NVARCHAR(255) NULL,
    hoja_trabajo_sala_normalizada NVARCHAR(255) NULL,
    hoja_trabajo_sala_celda NVARCHAR(20) NULL,
    hoja_trabajo_fecha_audiencia DATE NULL,
    hoja_trabajo_fecha_audiencia_original NVARCHAR(100) NULL,
    hoja_trabajo_fecha_audiencia_celda NVARCHAR(20) NULL,
    fila_encabezado_wide INT NULL,
    fila_encabezado_detalle INT NULL,
    estructura_valida BIT NULL,
    estructura_cumplimiento DECIMAL(9,4) NULL,
    estructura_umbral DECIMAL(9,4) NULL,
    estructura_campos_esperados INT NULL,
    estructura_campos_encontrados INT NULL,
    estructura_faltantes_json NVARCHAR(MAX) NULL,
    ubicacion_columnas_wide_json NVARCHAR(MAX) NULL,
    ubicacion_columnas_detalle_json NVARCHAR(MAX) NULL,
    fecha_creacion DATETIME2(0) NOT NULL
        CONSTRAINT DF_etl_estructura_hoja_fecha_creacion DEFAULT (SYSUTCDATETIME())
);

CREATE TABLE jnc.caso_calificado (
    id_caso INT IDENTITY(1,1) NOT NULL
        CONSTRAINT PK_caso_calificado PRIMARY KEY,
    id_archivo INT NOT NULL,
    pestana_nombre NVARCHAR(255) NULL,
    pestana_fecha DATE NULL,
    pestana_sala_normalizada NVARCHAR(255) NULL,
    hoja_trabajo_sala NVARCHAR(255) NULL,
    hoja_trabajo_sala_normalizada NVARCHAR(255) NULL,
    hoja_trabajo_fecha_audiencia DATE NULL,
    numero_radicado NVARCHAR(100) NULL,
    numero_radicado_normalizado NVARCHAR(100) NULL,
    cedula NVARCHAR(50) NULL,
    cedula_normalizada NVARCHAR(50) NULL,
    nombre_paciente NVARCHAR(500) NULL,
    nombre_paciente_normalizado NVARCHAR(500) NULL,
    entidad_remitente NVARCHAR(500) NULL,
    regional NVARCHAR(255) NULL,
    medico_ponente NVARCHAR(255) NULL,
    medico_principal NVARCHAR(255) NULL,
    responsable_pago NVARCHAR(255) NULL,
    pago_entidad NVARCHAR(255) NULL,
    rp NVARCHAR(100) NULL,
    terapeuta_psicologa NVARCHAR(255) NULL,
    fecha_pago_dictamen DATE NULL,
    valor_reportado DECIMAL(18,2) NULL,
    correo_guia NVARCHAR(500) NULL,
    eps NVARCHAR(300) NULL,
    afp NVARCHAR(300) NULL,
    arl NVARCHAR(300) NULL,
    asegurado NVARCHAR(300) NULL,
    comentarios_excel NVARCHAR(MAX) NULL,
    hash_caso NVARCHAR(64) NULL,
    origen_tabla NVARCHAR(100) NULL,
    tabla_caso_json NVARCHAR(MAX) NULL,
    activo BIT NOT NULL
        CONSTRAINT DF_caso_calificado_activo DEFAULT (1),
    fecha_creacion DATETIME2(0) NOT NULL
        CONSTRAINT DF_caso_calificado_fecha_creacion DEFAULT (SYSUTCDATETIME()),
    fecha_actualizacion DATETIME2(0) NULL
);

CREATE TABLE jnc.notificacion_correo_certificado (
    id_notificacion_correo INT IDENTITY(1,1) NOT NULL
        CONSTRAINT PK_notificacion_correo_certificado PRIMARY KEY,
    id_archivo INT NOT NULL,
    numero_linea_csv INT NULL,
    fecha DATE NULL,
    fecha_2 DATE NULL,
    fecha_3 DATE NULL,
    destinatario_nombre NVARCHAR(500) NULL,
    destinatario_nombre_normalizado NVARCHAR(500) NULL,
    destinatario_email NVARCHAR(320) NULL,
    destinatario_email_normalizado NVARCHAR(320) NULL,
    nombres NVARCHAR(500) NULL,
    correo NVARCHAR(320) NULL,
    asunto NVARCHAR(MAX) NULL,
    asunto_normalizado NVARCHAR(MAX) NULL,
    estado_correo NVARCHAR(255) NULL,
    codigo_certificado NVARCHAR(255) NULL,
    adjuntos NVARCHAR(MAX) NULL,
    numeros_asunto_json NVARCHAR(MAX) NULL,
    numeros_adjuntos_json NVARCHAR(MAX) NULL,
    fila_correo_certificado_json NVARCHAR(MAX) NULL,
    hash_correo NVARCHAR(64) NULL,
    fecha_creacion DATETIME2(0) NOT NULL
        CONSTRAINT DF_notificacion_correo_fecha_creacion DEFAULT (SYSUTCDATETIME())
);

CREATE TABLE jnc.etl_estructura_acta (
    id_estructura_acta BIGINT IDENTITY(1,1) NOT NULL
        CONSTRAINT PK_etl_estructura_acta PRIMARY KEY,
    id_archivo INT NOT NULL,
    numero_acta NVARCHAR(100) NULL,
    numero_acta_normalizado NVARCHAR(100) NULL,
    fecha_audiencia DATE NULL,
    sala NVARCHAR(255) NULL,
    sala_normalizada NVARCHAR(255) NULL,
    numero_paginas INT NULL,
    cantidad_casos INT NULL,
    medicos_firmantes_json NVARCHAR(MAX) NULL,
    terapeuta_o_psicologo NVARCHAR(500) NULL,
    proyectado_por NVARCHAR(500) NULL,
    documento_cuenta_con_firmas BIT NULL,
    estado_validacion_firmas NVARCHAR(100) NULL,
    firmantes_validados_json NVARCHAR(MAX) NULL,
    criterio_validacion_firmas NVARCHAR(MAX) NULL,
    asistentes_detectados_json NVARCHAR(MAX) NULL,
    casos_detectados_json NVARCHAR(MAX) NULL,
    radicados_detectados_json NVARCHAR(MAX) NULL,
    cedulas_detectadas_json NVARCHAR(MAX) NULL,
    texto_completo NVARCHAR(MAX) NULL,
    texto_paginas_json NVARCHAR(MAX) NULL,
    metadata_pdf_json NVARCHAR(MAX) NULL,
    tabla_acta_json NVARCHAR(MAX) NULL,
    hash_estructura_acta NVARCHAR(64) NULL,
    fecha_creacion DATETIME2(0) NOT NULL
        CONSTRAINT DF_etl_estructura_acta_fecha_creacion DEFAULT (SYSUTCDATETIME())
);

CREATE TABLE jnc.audiencia_caso (
    id_audiencia_caso BIGINT IDENTITY(1,1) NOT NULL
        CONSTRAINT PK_audiencia_caso PRIMARY KEY,
    id_estructura_acta BIGINT NULL,
    id_archivo INT NOT NULL,
    numero_acta NVARCHAR(100) NULL,
    numero_acta_normalizado NVARCHAR(100) NULL,
    fecha_audiencia DATE NULL,
    sala NVARCHAR(255) NULL,
    sala_normalizada NVARCHAR(255) NULL,
    numero_orden INT NULL,
    numero_radicado NVARCHAR(100) NULL,
    numero_radicado_normalizado NVARCHAR(100) NULL,
    nombre_paciente NVARCHAR(500) NULL,
    nombre_paciente_normalizado NVARCHAR(500) NULL,
    tipo_identificacion NVARCHAR(50) NULL,
    numero_identificacion NVARCHAR(50) NULL,
    numero_identificacion_normalizado NVARCHAR(50) NULL,
    entidad_remitente NVARCHAR(500) NULL,
    entidad_remitente_normalizado NVARCHAR(500) NULL,
    medico_ponente NVARCHAR(500) NULL,
    medico_ponente_normalizado NVARCHAR(500) NULL,
    medico_principal NVARCHAR(500) NULL,
    medico_principal_normalizado NVARCHAR(500) NULL,
    terapeuta_psicologa NVARCHAR(500) NULL,
    terapeuta_psicologa_normalizado NVARCHAR(500) NULL,
    fila_texto NVARCHAR(MAX) NULL,
    fila_caso_json NVARCHAR(MAX) NULL,
    hash_audiencia_caso NVARCHAR(64) NULL,
    activo BIT NOT NULL
        CONSTRAINT DF_audiencia_caso_activo DEFAULT (1),
    fecha_creacion DATETIME2(0) NOT NULL
        CONSTRAINT DF_audiencia_caso_fecha_creacion DEFAULT (SYSUTCDATETIME()),
    fecha_actualizacion DATETIME2(0) NULL
);

CREATE TABLE jnc.notificacion_esperada (
    id_notificacion_esperada INT IDENTITY(1,1) NOT NULL
        CONSTRAINT PK_notificacion_esperada PRIMARY KEY,
    id_caso INT NULL,
    id_archivo INT NOT NULL,
    numero_radicado NVARCHAR(100) NULL,
    numero_radicado_normalizado NVARCHAR(100) NULL,
    cedula NVARCHAR(50) NULL,
    cedula_normalizada NVARCHAR(50) NULL,
    tipo_destinatario NVARCHAR(100) NULL,
    correo_o_guia_reportado NVARCHAR(500) NULL,
    correo_normalizado NVARCHAR(320) NULL,
    fecha_envio_reportada DATE NULL,
    fecha_recibido_reportada DATE NULL,
    pestana_nombre NVARCHAR(255) NULL,
    pestana_fecha DATE NULL,
    pestana_sala_normalizada NVARCHAR(255) NULL,
    hoja_trabajo_sala NVARCHAR(255) NULL,
    hoja_trabajo_sala_normalizada NVARCHAR(255) NULL,
    hoja_trabajo_fecha_audiencia DATE NULL,
    origen_tabla NVARCHAR(100) NULL,
    tabla_notificacion_json NVARCHAR(MAX) NULL,
    hash_notificacion_esperada NVARCHAR(64) NULL,
    activo BIT NOT NULL
        CONSTRAINT DF_notificacion_esperada_activo DEFAULT (1),
    fecha_creacion DATETIME2(0) NOT NULL
        CONSTRAINT DF_notificacion_esperada_fecha_creacion DEFAULT (SYSUTCDATETIME()),
    fecha_actualizacion DATETIME2(0) NULL,
    estado_revision_notificacion NVARCHAR(100) NULL,
    pendiente_revision NVARCHAR(500) NULL,
    id_notificacion_correo_certificado_match INT NULL,
    fecha_revision_notificacion DATETIME2(0) NULL,
    detalle_revision_json NVARCHAR(MAX) NULL
);

CREATE TABLE jnc.etl_error_procesamiento (
    id_error INT IDENTITY(1,1) NOT NULL
        CONSTRAINT PK_etl_error_procesamiento PRIMARY KEY,
    id_archivo INT NOT NULL,
    etapa NVARCHAR(100) NULL,
    tipo_error NVARCHAR(100) NULL,
    detalle_error NVARCHAR(MAX) NULL,
    hoja_origen NVARCHAR(255) NULL,
    severidad NVARCHAR(50) NULL,
    requiere_revision BIT NULL,
    fecha_error DATETIME2(0) NULL,
    detalle_error_json NVARCHAR(MAX) NULL
);

CREATE TABLE jnc.etl_ejecucion_regla (
    id_ejecucion INT IDENTITY(1,1) NOT NULL
        CONSTRAINT PK_etl_ejecucion_regla PRIMARY KEY,
    id_archivo INT NOT NULL,
    nombre_regla NVARCHAR(255) NULL,
    tipo_regla NVARCHAR(100) NULL,
    version_script NVARCHAR(50) NULL,
    registros_evaluados INT NULL,
    registros_afectados INT NULL,
    resultado NVARCHAR(100) NULL,
    observacion NVARCHAR(500) NULL,
    fecha_ejecucion DATETIME2(0) NULL
);

CREATE TABLE jnc.resultado_cruce_notificacion (
    id_resultado_cruce INT IDENTITY(1,1) NOT NULL
        CONSTRAINT PK_resultado_cruce_notificacion PRIMARY KEY,
    id_notificacion_esperada INT NOT NULL,
    id_caso INT NULL,
    id_archivo INT NULL,
    numero_radicado NVARCHAR(100) NULL,
    numero_radicado_normalizado NVARCHAR(100) NULL,
    cedula NVARCHAR(50) NULL,
    cedula_normalizada NVARCHAR(50) NULL,
    tipo_destinatario NVARCHAR(100) NULL,
    id_notificacion_correo_certificado_match INT NULL,
    id_archivo_correo_certificado_match INT NULL,
    numero_linea_csv_match INT NULL,
    estado_revision_notificacion NVARCHAR(100) NOT NULL,
    descripcion_revision NVARCHAR(500) NULL,
    cumple_documento BIT NOT NULL
        CONSTRAINT DF_resultado_cruce_cumple_documento DEFAULT (0),
    cumple_asunto BIT NOT NULL
        CONSTRAINT DF_resultado_cruce_cumple_asunto DEFAULT (0),
    cumple_evento BIT NOT NULL
        CONSTRAINT DF_resultado_cruce_cumple_evento DEFAULT (0),
    cumple_correo BIT NOT NULL
        CONSTRAINT DF_resultado_cruce_cumple_correo DEFAULT (0),
    cumple_plazo BIT NOT NULL
        CONSTRAINT DF_resultado_cruce_cumple_plazo DEFAULT (0),
    score_total INT NULL,
    score_asunto DECIMAL(9,4) NULL,
    score_evento DECIMAL(9,4) NULL,
    fuente_documento_match NVARCHAR(100) NULL,
    asunto_tipo_match NVARCHAR(100) NULL,
    evento_tipo_match NVARCHAR(100) NULL,
    tipo_match_correo NVARCHAR(100) NULL,
    distancia_correo INT NULL,
    correo_esperado NVARCHAR(320) NULL,
    correo_certificado NVARCHAR(320) NULL,
    fecha_audiencia DATE NULL,
    fecha_envio_certificado DATE NULL,
    dias_despues_audiencia INT NULL,
    fecha_revision DATETIME2(0) NOT NULL
        CONSTRAINT DF_resultado_cruce_fecha_revision DEFAULT (SYSUTCDATETIME()),
    version_regla_cruce NVARCHAR(50) NULL,
    detalle_revision_json NVARCHAR(MAX) NULL,
    activo BIT NOT NULL
        CONSTRAINT DF_resultado_cruce_activo DEFAULT (1),
    fecha_creacion DATETIME2(0) NOT NULL
        CONSTRAINT DF_resultado_cruce_fecha_creacion DEFAULT (SYSUTCDATETIME()),
    fecha_actualizacion DATETIME2(0) NULL
);

CREATE TABLE jnc.resumen_validacion_radicado (
    id_resumen_validacion BIGINT IDENTITY(1,1) NOT NULL
        CONSTRAINT PK_resumen_validacion_radicado PRIMARY KEY,
    numero_radicado NVARCHAR(100) NULL,
    numero_radicado_normalizado NVARCHAR(100) NULL,
    nombre_pestana NVARCHAR(255) NULL,
    sala NVARCHAR(255) NULL,
    fecha_audiencia DATE NULL,
    cedula NVARCHAR(50) NULL,
    nombre_paciente NVARCHAR(500) NULL,
    condicion_pacientes BIT NOT NULL,
    condicion_pacientes_extemporaneo BIT NOT NULL,
    condicion_regional BIT NOT NULL,
    condicion_regional_extemporaneo BIT NOT NULL,
    condicion_empleador BIT NOT NULL,
    condicion_empleador_extemporaneo BIT NOT NULL,
    condicion_remitente BIT NOT NULL,
    condicion_remitente_extemporaneo BIT NOT NULL,
    condicion_eps BIT NOT NULL,
    condicion_eps_extemporaneo BIT NOT NULL,
    condicion_afp BIT NOT NULL,
    condicion_afp_extemporaneo BIT NOT NULL,
    condicion_arl BIT NOT NULL,
    condicion_arl_extemporaneo BIT NOT NULL,
    condicion_aseguradoras BIT NOT NULL,
    condicion_aseguradoras_extemporaneo BIT NOT NULL,
    cumplimiento_total BIT NOT NULL,
    cumplimiento_extemporaneo BIT NOT NULL,
    no_cumplimiento_revision_manual NVARCHAR(500) NULL,
    fecha_actualizacion_resumen DATETIME2(0) NOT NULL
        CONSTRAINT DF_resumen_validacion_fecha_actualizacion DEFAULT (SYSUTCDATETIME())
);

CREATE INDEX IX_etl_archivo_cargado_hash_tipo_estado
ON jnc.etl_archivo_cargado (
    hash_archivo,
    tipo_archivo,
    estado_proceso
)
INCLUDE (
    nombre_archivo,
    fecha_fin_proceso
)
WHERE hash_archivo IS NOT NULL;

CREATE INDEX IX_caso_calificado_archivo_radicado_hash
ON jnc.caso_calificado (
    id_archivo,
    numero_radicado_normalizado,
    hash_caso
);

CREATE UNIQUE INDEX UX_caso_calificado_archivo_hash
ON jnc.caso_calificado (
    id_archivo,
    hash_caso
)
WHERE hash_caso IS NOT NULL
  AND activo = 1;

CREATE INDEX IX_notificacion_esperada_revision
ON jnc.notificacion_esperada (
    activo,
    estado_revision_notificacion,
    numero_radicado_normalizado,
    cedula_normalizada
)
INCLUDE (
    correo_normalizado,
    hoja_trabajo_fecha_audiencia,
    id_caso,
    id_archivo
);

CREATE INDEX IX_notificacion_correo_certificado_revision
ON jnc.notificacion_correo_certificado (
    destinatario_email_normalizado,
    fecha,
    id_archivo
)
INCLUDE (
    id_notificacion_correo,
    numero_linea_csv,
    estado_correo
);

CREATE INDEX IX_etl_estructura_acta_archivo
ON jnc.etl_estructura_acta (
    id_archivo,
    fecha_audiencia,
    sala_normalizada
);

CREATE UNIQUE INDEX UX_etl_estructura_acta_archivo_hash
ON jnc.etl_estructura_acta (
    id_archivo,
    hash_estructura_acta
)
WHERE hash_estructura_acta IS NOT NULL;

CREATE INDEX IX_audiencia_caso_archivo
ON jnc.audiencia_caso (
    id_archivo,
    numero_radicado_normalizado,
    numero_identificacion_normalizado
);

CREATE INDEX IX_resultado_cruce_notificacion_radicado
ON jnc.resultado_cruce_notificacion (
    numero_radicado_normalizado,
    tipo_destinatario,
    estado_revision_notificacion
);

CREATE INDEX IX_resultado_cruce_notificacion_cedula
ON jnc.resultado_cruce_notificacion (
    cedula_normalizada,
    estado_revision_notificacion
);

CREATE INDEX IX_resultado_cruce_notificacion_estado
ON jnc.resultado_cruce_notificacion (
    estado_revision_notificacion,
    activo,
    fecha_revision
);

CREATE INDEX IX_resultado_cruce_notificacion_match_correo
ON jnc.resultado_cruce_notificacion (
    id_notificacion_correo_certificado_match
);

CREATE UNIQUE INDEX UX_resultado_cruce_notificacion_activo
ON jnc.resultado_cruce_notificacion (
    id_notificacion_esperada
)
WHERE activo = 1;

CREATE UNIQUE INDEX UX_resumen_validacion_radicado
ON jnc.resumen_validacion_radicado (
    numero_radicado_normalizado
)
WHERE numero_radicado_normalizado IS NOT NULL;

CREATE INDEX IX_resumen_validacion_estado
ON jnc.resumen_validacion_radicado (
    cumplimiento_total,
    cumplimiento_extemporaneo,
    fecha_audiencia
);

COMMIT TRANSACTION;
