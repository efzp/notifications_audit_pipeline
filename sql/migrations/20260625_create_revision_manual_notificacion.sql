/*
Tabla de decisiones humanas para revision manual de notificaciones.

Guarda solo la decision y trazabilidad minima de la fila revisada. El contexto
humano se obtiene desde jnc.vw_input_revision_manual_notificaciones_pendientes.
*/

IF OBJECT_ID('jnc.revision_manual_notificacion', 'U') IS NULL
   AND OBJECT_ID('jnc.revision_manual_guia', 'U') IS NOT NULL
BEGIN
    EXEC sp_rename 'jnc.revision_manual_guia', 'revision_manual_notificacion';
END;
GO

IF OBJECT_ID('jnc.revision_manual_notificacion', 'U') IS NOT NULL
   AND COL_LENGTH('jnc.revision_manual_notificacion', 'id_revision_manual_notificacion') IS NULL
   AND COL_LENGTH('jnc.revision_manual_notificacion', 'id_revision_manual_guia') IS NOT NULL
BEGIN
    EXEC sp_rename
        'jnc.revision_manual_notificacion.id_revision_manual_guia',
        'id_revision_manual_notificacion',
        'COLUMN';
END;
GO

IF OBJECT_ID('jnc.revision_manual_notificacion', 'U') IS NULL
BEGIN
    CREATE TABLE jnc.revision_manual_notificacion (
        id_revision_manual_notificacion BIGINT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_revision_manual_notificacion PRIMARY KEY,

        id_archivo INT NOT NULL,
        numero_linea_excel INT NULL,

        id_notificacion_esperada INT NOT NULL,
        numero_radicado_normalizado NVARCHAR(100) NOT NULL,
        cedula_normalizada NVARCHAR(50) NULL,
        tipo_destinatario NVARCHAR(100) NOT NULL,

        cumplimiento BIT NULL,
        cumplimiento_extemporaneo BIT NULL,
        observaciones NVARCHAR(MAX) NULL,
        revisado_por NVARCHAR(255) NULL,

        fecha_revision DATETIME2(0) NOT NULL
            CONSTRAINT DF_revision_manual_notificacion_fecha_revision
            DEFAULT (SYSUTCDATETIME()),

        estado_aplicacion NVARCHAR(50) NOT NULL
            CONSTRAINT DF_revision_manual_notificacion_estado_aplicacion
            DEFAULT ('PENDIENTE'),
        fecha_aplicacion DATETIME2(0) NULL,
        detalle_aplicacion NVARCHAR(MAX) NULL,
        id_resultado_cruce_generado INT NULL,

        hash_revision_manual NVARCHAR(64) NULL,

        activo BIT NOT NULL
            CONSTRAINT DF_revision_manual_notificacion_activo DEFAULT (1),
        fecha_creacion DATETIME2(0) NOT NULL
            CONSTRAINT DF_revision_manual_notificacion_fecha_creacion
            DEFAULT (SYSUTCDATETIME()),
        fecha_actualizacion DATETIME2(0) NULL,

        CONSTRAINT CK_revision_manual_notificacion_decision
            CHECK (
                NOT (
                    ISNULL(cumplimiento, 0) = 1
                    AND ISNULL(cumplimiento_extemporaneo, 0) = 1
                )
            )
    );
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_revision_manual_notificacion_pendientes'
      AND object_id = OBJECT_ID('jnc.revision_manual_notificacion')
)
BEGIN
    CREATE INDEX IX_revision_manual_notificacion_pendientes
    ON jnc.revision_manual_notificacion (
        estado_aplicacion,
        activo,
        id_notificacion_esperada
    )
    INCLUDE (
        id_archivo,
        cumplimiento,
        cumplimiento_extemporaneo,
        numero_radicado_normalizado,
        cedula_normalizada,
        tipo_destinatario
    );
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_revision_manual_notificacion_radicado'
      AND object_id = OBJECT_ID('jnc.revision_manual_notificacion')
)
BEGIN
    CREATE INDEX IX_revision_manual_notificacion_radicado
    ON jnc.revision_manual_notificacion (
        numero_radicado_normalizado,
        cedula_normalizada,
        tipo_destinatario,
        activo
    )
    INCLUDE (
        id_notificacion_esperada,
        estado_aplicacion,
        fecha_revision
    );
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'UX_revision_manual_notificacion_hash'
      AND object_id = OBJECT_ID('jnc.revision_manual_notificacion')
)
BEGIN
    CREATE UNIQUE INDEX UX_revision_manual_notificacion_hash
    ON jnc.revision_manual_notificacion (
        hash_revision_manual
    )
    WHERE hash_revision_manual IS NOT NULL;
END;
GO
