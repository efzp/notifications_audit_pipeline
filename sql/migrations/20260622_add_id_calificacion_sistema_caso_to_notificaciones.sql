/*
Agrega linaje hacia jnc.calificacion_sistema_caso.

id_caso se conserva por compatibilidad, pero el identificador canonico del caso
para nuevas cargas debe ser id_calificacion_sistema_caso.
*/

IF COL_LENGTH('jnc.notificacion_esperada', 'id_calificacion_sistema_caso') IS NULL
BEGIN
    ALTER TABLE jnc.notificacion_esperada
        ADD id_calificacion_sistema_caso BIGINT NULL;
END;
GO

IF COL_LENGTH('jnc.resultado_cruce_notificacion', 'id_calificacion_sistema_caso') IS NULL
BEGIN
    ALTER TABLE jnc.resultado_cruce_notificacion
        ADD id_calificacion_sistema_caso BIGINT NULL;
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_notificacion_esperada_calificacion_caso'
      AND object_id = OBJECT_ID('jnc.notificacion_esperada')
)
BEGIN
    CREATE INDEX IX_notificacion_esperada_calificacion_caso
    ON jnc.notificacion_esperada (
        id_calificacion_sistema_caso,
        activo
    )
    INCLUDE (
        id_notificacion_esperada,
        id_caso,
        numero_radicado_normalizado,
        cedula_normalizada,
        tipo_destinatario,
        estado_revision_notificacion
    );
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_resultado_cruce_calificacion_caso'
      AND object_id = OBJECT_ID('jnc.resultado_cruce_notificacion')
)
BEGIN
    CREATE INDEX IX_resultado_cruce_calificacion_caso
    ON jnc.resultado_cruce_notificacion (
        id_calificacion_sistema_caso,
        activo
    )
    INCLUDE (
        id_notificacion_esperada,
        id_caso,
        estado_revision_notificacion
    );
END;
GO
