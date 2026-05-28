IF COL_LENGTH('jnc.notificacion_esperada', 'estado_revision_notificacion') IS NULL
BEGIN
    ALTER TABLE jnc.notificacion_esperada
    ADD estado_revision_notificacion NVARCHAR(100) NULL;
END;

IF COL_LENGTH('jnc.notificacion_esperada', 'pendiente_revision') IS NULL
BEGIN
    ALTER TABLE jnc.notificacion_esperada
    ADD pendiente_revision NVARCHAR(500) NULL;
END;

IF COL_LENGTH('jnc.notificacion_esperada', 'id_notificacion_correo_certificado_match') IS NULL
BEGIN
    ALTER TABLE jnc.notificacion_esperada
    ADD id_notificacion_correo_certificado_match INT NULL;
END;

IF COL_LENGTH('jnc.notificacion_esperada', 'fecha_revision_notificacion') IS NULL
BEGIN
    ALTER TABLE jnc.notificacion_esperada
    ADD fecha_revision_notificacion DATETIME2 NULL;
END;

IF COL_LENGTH('jnc.notificacion_esperada', 'detalle_revision_json') IS NULL
BEGIN
    ALTER TABLE jnc.notificacion_esperada
    ADD detalle_revision_json NVARCHAR(MAX) NULL;
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_notificacion_esperada_revision'
      AND object_id = OBJECT_ID('jnc.notificacion_esperada')
)
BEGIN
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
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_notificacion_correo_certificado_revision'
      AND object_id = OBJECT_ID('jnc.notificacion_correo_certificado')
)
BEGIN
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
END;
