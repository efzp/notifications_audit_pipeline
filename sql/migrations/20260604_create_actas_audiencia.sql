/*
Agrega almacenamiento de estructura y detalle extraidos desde PDF de actas de audiencia.
*/

SET XACT_ABORT ON;

IF SCHEMA_ID('jnc') IS NULL
BEGIN
    EXEC('CREATE SCHEMA jnc');
END;

IF COL_LENGTH('jnc.etl_archivo_cargado', 'total_actas_audiencia_pdf') IS NULL
BEGIN
    ALTER TABLE jnc.etl_archivo_cargado
        ADD total_actas_audiencia_pdf INT NULL;
END;

IF OBJECT_ID('jnc.etl_estructura_acta', 'U') IS NULL
   AND OBJECT_ID('jnc.acta_audiencia_pdf', 'U') IS NOT NULL
BEGIN
    EXEC sp_rename 'jnc.acta_audiencia_pdf', 'etl_estructura_acta';
END;

IF OBJECT_ID('jnc.etl_estructura_acta', 'U') IS NULL
BEGIN
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
END;

IF COL_LENGTH('jnc.etl_estructura_acta', 'id_estructura_acta') IS NULL
BEGIN
    EXEC sp_rename 'jnc.etl_estructura_acta.id_acta_audiencia_pdf', 'id_estructura_acta', 'COLUMN';
END;

IF COL_LENGTH('jnc.etl_estructura_acta', 'cantidad_casos') IS NULL
    ALTER TABLE jnc.etl_estructura_acta ADD cantidad_casos INT NULL;
IF COL_LENGTH('jnc.etl_estructura_acta', 'medicos_firmantes_json') IS NULL
    ALTER TABLE jnc.etl_estructura_acta ADD medicos_firmantes_json NVARCHAR(MAX) NULL;
IF COL_LENGTH('jnc.etl_estructura_acta', 'terapeuta_o_psicologo') IS NULL
    ALTER TABLE jnc.etl_estructura_acta ADD terapeuta_o_psicologo NVARCHAR(500) NULL;
IF COL_LENGTH('jnc.etl_estructura_acta', 'proyectado_por') IS NULL
    ALTER TABLE jnc.etl_estructura_acta ADD proyectado_por NVARCHAR(500) NULL;
IF COL_LENGTH('jnc.etl_estructura_acta', 'documento_cuenta_con_firmas') IS NULL
    ALTER TABLE jnc.etl_estructura_acta ADD documento_cuenta_con_firmas BIT NULL;
IF COL_LENGTH('jnc.etl_estructura_acta', 'estado_validacion_firmas') IS NULL
    ALTER TABLE jnc.etl_estructura_acta ADD estado_validacion_firmas NVARCHAR(100) NULL;
IF COL_LENGTH('jnc.etl_estructura_acta', 'firmantes_validados_json') IS NULL
    ALTER TABLE jnc.etl_estructura_acta ADD firmantes_validados_json NVARCHAR(MAX) NULL;
IF COL_LENGTH('jnc.etl_estructura_acta', 'criterio_validacion_firmas') IS NULL
    ALTER TABLE jnc.etl_estructura_acta ADD criterio_validacion_firmas NVARCHAR(MAX) NULL;
IF COL_LENGTH('jnc.etl_estructura_acta', 'asistentes_detectados_json') IS NULL
    ALTER TABLE jnc.etl_estructura_acta ADD asistentes_detectados_json NVARCHAR(MAX) NULL;
IF COL_LENGTH('jnc.etl_estructura_acta', 'hash_estructura_acta') IS NULL
    ALTER TABLE jnc.etl_estructura_acta ADD hash_estructura_acta NVARCHAR(64) NULL;

IF OBJECT_ID('jnc.audiencia_caso', 'U') IS NULL
BEGIN
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
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_etl_estructura_acta_archivo'
      AND object_id = OBJECT_ID('jnc.etl_estructura_acta')
)
BEGIN
    CREATE INDEX IX_etl_estructura_acta_archivo
    ON jnc.etl_estructura_acta (
        id_archivo,
        fecha_audiencia,
        sala_normalizada
    );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'UX_etl_estructura_acta_archivo_hash'
      AND object_id = OBJECT_ID('jnc.etl_estructura_acta')
)
BEGIN
    CREATE UNIQUE INDEX UX_etl_estructura_acta_archivo_hash
    ON jnc.etl_estructura_acta (
        id_archivo,
        hash_estructura_acta
    )
    WHERE hash_estructura_acta IS NOT NULL;
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_audiencia_caso_archivo'
      AND object_id = OBJECT_ID('jnc.audiencia_caso')
)
BEGIN
    CREATE INDEX IX_audiencia_caso_archivo
    ON jnc.audiencia_caso (
        id_archivo,
        numero_radicado_normalizado,
        numero_identificacion_normalizado
    );
END;
