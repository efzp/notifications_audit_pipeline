/*
Mejoras incrementales al flujo actual de notificaciones:

1. Metadatos de reconocimiento de schema/layout en archivos cargados.
2. Fallback de correo desde calificacion_sistema_envio_entidad.
3. Hash de negocio estable para evitar duplicar notificaciones esperadas.
4. Dependencia operativa menor de audiencia_caso para input salas.
5. Cache de pendientes de cruce para auditoria/Power BI.
*/

IF COL_LENGTH('jnc.etl_archivo_cargado', 'schema_version') IS NULL
BEGIN
    ALTER TABLE jnc.etl_archivo_cargado
        ADD schema_version INT NULL;
END;
GO

IF COL_LENGTH('jnc.etl_archivo_cargado', 'layout_version') IS NULL
BEGIN
    ALTER TABLE jnc.etl_archivo_cargado
        ADD layout_version NVARCHAR(50) NULL;
END;
GO

IF COL_LENGTH('jnc.etl_archivo_cargado', 'tipo_archivo_detectado') IS NULL
BEGIN
    ALTER TABLE jnc.etl_archivo_cargado
        ADD tipo_archivo_detectado NVARCHAR(100) NULL;
END;
GO

IF COL_LENGTH('jnc.etl_archivo_cargado', 'hash_estructura_archivo') IS NULL
BEGIN
    ALTER TABLE jnc.etl_archivo_cargado
        ADD hash_estructura_archivo NVARCHAR(64) NULL;
END;
GO

IF COL_LENGTH('jnc.notificacion_esperada', 'hash_negocio_notificacion') IS NULL
BEGIN
    ALTER TABLE jnc.notificacion_esperada
        ADD hash_negocio_notificacion NVARCHAR(64) NULL;
END;
GO

IF COL_LENGTH('jnc.notificacion_esperada', 'fuente_correo_reportado') IS NULL
BEGIN
    ALTER TABLE jnc.notificacion_esperada
        ADD fuente_correo_reportado NVARCHAR(100) NULL;
END;
GO

IF COL_LENGTH('jnc.notificacion_esperada', 'id_calificacion_sistema_envio_fallback') IS NULL
BEGIN
    ALTER TABLE jnc.notificacion_esperada
        ADD id_calificacion_sistema_envio_fallback BIGINT NULL;
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_notificacion_esperada_hash_negocio'
      AND object_id = OBJECT_ID('jnc.notificacion_esperada')
)
BEGIN
    CREATE INDEX IX_notificacion_esperada_hash_negocio
    ON jnc.notificacion_esperada (
        hash_negocio_notificacion,
        activo
    )
    INCLUDE (
        id_notificacion_esperada,
        id_archivo,
        numero_radicado_normalizado,
        cedula_normalizada,
        tipo_destinatario,
        estado_revision_notificacion
    )
    WHERE hash_negocio_notificacion IS NOT NULL;
END;
GO

IF OBJECT_ID('jnc.cruce_notificacion_pendiente', 'U') IS NULL
BEGIN
    CREATE TABLE jnc.cruce_notificacion_pendiente (
        id_cruce_notificacion_pendiente BIGINT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_cruce_notificacion_pendiente PRIMARY KEY,
        id_notificacion_esperada INT NOT NULL,
        id_calificacion_sistema_caso BIGINT NULL,
        id_caso INT NULL,
        id_archivo INT NULL,
        numero_radicado_normalizado NVARCHAR(100) NULL,
        cedula_normalizada NVARCHAR(50) NULL,
        tipo_destinatario NVARCHAR(100) NULL,
        correo_o_guia_reportado NVARCHAR(500) NULL,
        correo_normalizado NVARCHAR(320) NULL,
        estado_revision_notificacion NVARCHAR(100) NOT NULL,
        motivo_pendiente NVARCHAR(500) NULL,
        prioridad INT NOT NULL
            CONSTRAINT DF_cruce_notificacion_pendiente_prioridad DEFAULT (100),
        requiere_auditoria_manual BIT NOT NULL
            CONSTRAINT DF_cruce_notificacion_pendiente_manual DEFAULT (1),
        fecha_ultima_revision DATETIME2(0) NULL,
        hash_negocio_notificacion NVARCHAR(64) NULL,
        activo BIT NOT NULL
            CONSTRAINT DF_cruce_notificacion_pendiente_activo DEFAULT (1),
        fecha_creacion DATETIME2(0) NOT NULL
            CONSTRAINT DF_cruce_notificacion_pendiente_fecha_creacion DEFAULT (SYSUTCDATETIME()),
        fecha_actualizacion DATETIME2(0) NULL
    );
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_cruce_notificacion_pendiente_busqueda'
      AND object_id = OBJECT_ID('jnc.cruce_notificacion_pendiente')
)
BEGIN
    CREATE INDEX IX_cruce_notificacion_pendiente_busqueda
    ON jnc.cruce_notificacion_pendiente (
        activo,
        estado_revision_notificacion,
        numero_radicado_normalizado,
        tipo_destinatario
    )
    INCLUDE (
        id_notificacion_esperada,
        id_calificacion_sistema_caso,
        cedula_normalizada,
        prioridad
    );
END;
GO
