/*
Evidencia de radicacion/respuesta de ARL recibida como PDF.

Esta fuente no trae numero de radicado confiable para el cruce operativo;
la conciliacion se hace contra notificacion_esperada de tipo ARL por:
    cedula_normalizada + entidad ARL detectada + ventana de fecha.
*/

IF OBJECT_ID('jnc.notificacion_arl_radicado', 'U') IS NULL
BEGIN
    CREATE TABLE jnc.notificacion_arl_radicado (
        id_notificacion_arl_radicado BIGINT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_notificacion_arl_radicado PRIMARY KEY,
        id_archivo INT NOT NULL,
        arl_detectada NVARCHAR(100) NULL,
        arl_normalizada NVARCHAR(100) NULL,
        remitente_detectado NVARCHAR(500) NULL,
        cedula_detectada NVARCHAR(50) NULL,
        cedula_normalizada NVARCHAR(50) NULL,
        fecha_recibo_comunicacion DATE NULL,
        hora_recibo_comunicacion TIME(0) NULL,
        fecha_correo DATE NULL,
        hora_correo TIME(0) NULL,
        metodo_deteccion_arl NVARCHAR(100) NULL,
        metodo_deteccion_cedula NVARCHAR(100) NULL,
        metodo_deteccion_fecha NVARCHAR(100) NULL,
        confianza_arl DECIMAL(9,4) NULL,
        confianza_cedula DECIMAL(9,4) NULL,
        confianza_fecha DECIMAL(9,4) NULL,
        nombre_archivo NVARCHAR(500) NULL,
        ruta_sharepoint NVARCHAR(1000) NULL,
        identifier NVARCHAR(1000) NULL,
        numero_paginas INT NULL,
        texto_patrones_json NVARCHAR(MAX) NULL,
        metadata_pdf_json NVARCHAR(MAX) NULL,
        fila_arl_radicado_json NVARCHAR(MAX) NULL,
        hash_arl_radicado NVARCHAR(64) NULL,
        activo BIT NOT NULL
            CONSTRAINT DF_notificacion_arl_radicado_activo DEFAULT (1),
        fecha_creacion DATETIME2(0) NOT NULL
            CONSTRAINT DF_notificacion_arl_radicado_fecha_creacion DEFAULT (SYSUTCDATETIME()),
        fecha_actualizacion DATETIME2(0) NULL
    );
END;

IF COL_LENGTH('jnc.resultado_cruce_notificacion', 'id_notificacion_arl_radicado_match') IS NULL
BEGIN
    ALTER TABLE jnc.resultado_cruce_notificacion
        ADD id_notificacion_arl_radicado_match BIGINT NULL;
END;

IF COL_LENGTH('jnc.resultado_cruce_notificacion', 'id_archivo_arl_radicado_match') IS NULL
BEGIN
    ALTER TABLE jnc.resultado_cruce_notificacion
        ADD id_archivo_arl_radicado_match INT NULL;
END;

IF COL_LENGTH('jnc.resultado_cruce_notificacion', 'arl_esperada') IS NULL
BEGIN
    ALTER TABLE jnc.resultado_cruce_notificacion
        ADD arl_esperada NVARCHAR(300) NULL;
END;

IF COL_LENGTH('jnc.resultado_cruce_notificacion', 'arl_detectada') IS NULL
BEGIN
    ALTER TABLE jnc.resultado_cruce_notificacion
        ADD arl_detectada NVARCHAR(100) NULL;
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_notificacion_arl_radicado_cedula_fecha'
      AND object_id = OBJECT_ID('jnc.notificacion_arl_radicado')
)
BEGIN
    CREATE INDEX IX_notificacion_arl_radicado_cedula_fecha
    ON jnc.notificacion_arl_radicado (
        cedula_normalizada,
        arl_normalizada,
        fecha_recibo_comunicacion,
        activo
    )
    INCLUDE (
        id_notificacion_arl_radicado,
        id_archivo,
        arl_detectada,
        fecha_correo,
        metodo_deteccion_arl,
        metodo_deteccion_fecha
    );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_notificacion_arl_radicado_hash'
      AND object_id = OBJECT_ID('jnc.notificacion_arl_radicado')
)
BEGIN
    CREATE INDEX IX_notificacion_arl_radicado_hash
    ON jnc.notificacion_arl_radicado (
        hash_arl_radicado,
        activo
    )
    INCLUDE (
        id_notificacion_arl_radicado,
        id_archivo,
        cedula_normalizada,
        arl_normalizada,
        fecha_recibo_comunicacion
    );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_resultado_cruce_notificacion_match_arl'
      AND object_id = OBJECT_ID('jnc.resultado_cruce_notificacion')
)
BEGIN
    CREATE INDEX IX_resultado_cruce_notificacion_match_arl
    ON jnc.resultado_cruce_notificacion (
        id_notificacion_arl_radicado_match
    )
    INCLUDE (
        id_notificacion_esperada,
        cedula_normalizada,
        tipo_destinatario,
        estado_revision_notificacion
    );
END;
