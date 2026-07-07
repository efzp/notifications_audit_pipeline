/*
Convierte jnc.audiencia_caso a modelo documento.

La tabla queda como almacenamiento liviano para backfill desde actas PDF:
- documento_caso_json conserva llaves, datos normalizados y evidencia de extraccion.
- las columnas consultables son computadas desde el documento para no duplicar datos.
*/

SET XACT_ABORT ON;

IF OBJECT_ID('jnc.audiencia_caso', 'U') IS NULL
BEGIN
    THROW 50001, 'No existe jnc.audiencia_caso.', 1;
END;
GO

IF COL_LENGTH('jnc.audiencia_caso', 'documento_caso_json') IS NULL
BEGIN
    ALTER TABLE jnc.audiencia_caso
        ADD documento_caso_json NVARCHAR(MAX) NULL;
END;
GO

IF COL_LENGTH('jnc.audiencia_caso', 'fila_caso_json') IS NOT NULL
BEGIN
    UPDATE ac
    SET documento_caso_json = doc.documento_caso_json,
        fecha_actualizacion = SYSUTCDATETIME()
    FROM jnc.audiencia_caso AS ac
    CROSS APPLY (
        SELECT
            ac.numero_radicado_normalizado
                AS [llaves_busqueda.numero_radicado_normalizado],
            ac.numero_identificacion_normalizado
                AS [llaves_busqueda.numero_identificacion_normalizado],
            ac.numero_acta_normalizado
                AS [llaves_busqueda.numero_acta_normalizado],
            CONVERT(CHAR(10), ac.fecha_audiencia, 23)
                AS [llaves_busqueda.fecha_audiencia],
            ac.sala_normalizada
                AS [llaves_busqueda.sala_normalizada],

            ac.nombre_paciente_normalizado
                AS [datos_normalizados.nombre_paciente_normalizado],
            ac.tipo_identificacion
                AS [datos_normalizados.tipo_identificacion],
            ac.entidad_remitente_normalizado
                AS [datos_normalizados.entidad_remitente_normalizado],
            ac.medico_ponente_normalizado
                AS [datos_normalizados.medico_ponente_normalizado],
            ac.medico_principal_normalizado
                AS [datos_normalizados.medico_principal_normalizado],
            ac.terapeuta_psicologa_normalizado
                AS [datos_normalizados.terapeuta_psicologa_normalizado],

            ac.numero_orden
                AS [origen_extraccion.numero_orden],
            ac.fila_texto
                AS [origen_extraccion.fila_texto],
            JSON_QUERY(ac.fila_caso_json)
                AS [origen_extraccion.fila_caso]
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
    ) AS doc(documento_caso_json)
    WHERE ac.documento_caso_json IS NULL;
END;
GO

IF EXISTS (
    SELECT 1
    FROM jnc.audiencia_caso
    WHERE documento_caso_json IS NULL
       OR ISJSON(documento_caso_json) <> 1
)
BEGIN
    THROW 50002, 'No se puede migrar audiencia_caso: hay documentos nulos o JSON invalido.', 1;
END;
GO

ALTER TABLE jnc.audiencia_caso
    ALTER COLUMN documento_caso_json NVARCHAR(MAX) NOT NULL;
GO

DECLARE @drop_index_sql NVARCHAR(MAX);

SELECT @drop_index_sql = STRING_AGG(
    N'DROP INDEX ' + QUOTENAME(i.name) + N' ON jnc.audiencia_caso;',
    CHAR(10)
)
FROM sys.indexes AS i
WHERE i.object_id = OBJECT_ID('jnc.audiencia_caso')
  AND i.is_primary_key = 0
  AND i.name IS NOT NULL
  AND (
      i.name IN (
          'IX_audiencia_caso_archivo',
          'IX_audiencia_caso_acta',
          'IX_audiencia_caso_identificacion',
          'IX_audiencia_caso_radicado',
          'UX_audiencia_caso_archivo_hash',
          'IX_audiencia_caso_backfill_doc'
      )
      OR EXISTS (
          SELECT 1
          FROM sys.index_columns AS ic
          JOIN sys.columns AS c
            ON c.object_id = ic.object_id
           AND c.column_id = ic.column_id
          WHERE ic.object_id = i.object_id
            AND ic.index_id = i.index_id
            AND c.name IN (
                'id_estructura_acta',
                'numero_acta',
                'numero_acta_normalizado',
                'fecha_audiencia',
                'sala',
                'sala_normalizada',
                'numero_orden',
                'numero_radicado',
                'numero_radicado_normalizado',
                'nombre_paciente',
                'nombre_paciente_normalizado',
                'tipo_identificacion',
                'numero_identificacion',
                'numero_identificacion_normalizado',
                'entidad_remitente',
                'entidad_remitente_normalizado',
                'medico_ponente',
                'medico_ponente_normalizado',
                'medico_principal',
                'medico_principal_normalizado',
                'terapeuta_psicologa',
                'terapeuta_psicologa_normalizado',
                'fila_texto',
                'fila_caso_json'
            )
      )
  );

IF @drop_index_sql IS NOT NULL AND @drop_index_sql <> N''
BEGIN
    EXEC sp_executesql @drop_index_sql;
END;
GO

DECLARE @drop_columns_sql NVARCHAR(MAX);

SELECT @drop_columns_sql = STRING_AGG(
    N'ALTER TABLE jnc.audiencia_caso DROP COLUMN ' + QUOTENAME(name) + N';',
    CHAR(10)
) WITHIN GROUP (ORDER BY column_id DESC)
FROM sys.columns
WHERE object_id = OBJECT_ID('jnc.audiencia_caso')
  AND name IN (
      'id_estructura_acta',
      'numero_acta',
      'numero_acta_normalizado',
      'fecha_audiencia',
      'sala',
      'sala_normalizada',
      'numero_orden',
      'numero_radicado',
      'numero_radicado_normalizado',
      'nombre_paciente',
      'nombre_paciente_normalizado',
      'tipo_identificacion',
      'numero_identificacion',
      'numero_identificacion_normalizado',
      'entidad_remitente',
      'entidad_remitente_normalizado',
      'medico_ponente',
      'medico_ponente_normalizado',
      'medico_principal',
      'medico_principal_normalizado',
      'terapeuta_psicologa',
      'terapeuta_psicologa_normalizado',
      'fila_texto',
      'fila_caso_json'
  );

IF @drop_columns_sql IS NOT NULL AND @drop_columns_sql <> N''
BEGIN
    EXEC sp_executesql @drop_columns_sql;
END;
GO

IF COL_LENGTH('jnc.audiencia_caso', 'numero_radicado_normalizado') IS NULL
BEGIN
    ALTER TABLE jnc.audiencia_caso ADD
        numero_radicado_normalizado AS
            CONVERT(
                NVARCHAR(100),
                JSON_VALUE(
                    documento_caso_json,
                    '$.llaves_busqueda.numero_radicado_normalizado'
                )
            ),
        numero_identificacion_normalizado AS
            CONVERT(
                NVARCHAR(50),
                JSON_VALUE(
                    documento_caso_json,
                    '$.llaves_busqueda.numero_identificacion_normalizado'
                )
            ),
        numero_acta_normalizado AS
            CONVERT(
                NVARCHAR(100),
                JSON_VALUE(
                    documento_caso_json,
                    '$.llaves_busqueda.numero_acta_normalizado'
                )
            ),
        fecha_audiencia AS
            CONVERT(
                DATE,
                JSON_VALUE(documento_caso_json, '$.llaves_busqueda.fecha_audiencia'),
                23
            ),
        sala_normalizada AS
            CONVERT(
                NVARCHAR(255),
                JSON_VALUE(documento_caso_json, '$.llaves_busqueda.sala_normalizada')
            ),
        nombre_paciente_normalizado AS
            CONVERT(
                NVARCHAR(500),
                JSON_VALUE(
                    documento_caso_json,
                    '$.datos_normalizados.nombre_paciente_normalizado'
                )
            ),
        tipo_identificacion AS
            CONVERT(
                NVARCHAR(50),
                JSON_VALUE(documento_caso_json, '$.datos_normalizados.tipo_identificacion')
            ),
        entidad_remitente_normalizado AS
            CONVERT(
                NVARCHAR(500),
                JSON_VALUE(
                    documento_caso_json,
                    '$.datos_normalizados.entidad_remitente_normalizado'
                )
            ),
        medico_ponente_normalizado AS
            CONVERT(
                NVARCHAR(500),
                JSON_VALUE(
                    documento_caso_json,
                    '$.datos_normalizados.medico_ponente_normalizado'
                )
            ),
        medico_principal_normalizado AS
            CONVERT(
                NVARCHAR(500),
                JSON_VALUE(
                    documento_caso_json,
                    '$.datos_normalizados.medico_principal_normalizado'
                )
            ),
        terapeuta_psicologa_normalizado AS
            CONVERT(
                NVARCHAR(500),
                JSON_VALUE(
                    documento_caso_json,
                    '$.datos_normalizados.terapeuta_psicologa_normalizado'
                )
            );
END;
GO

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
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_audiencia_caso_backfill'
      AND object_id = OBJECT_ID('jnc.audiencia_caso')
)
BEGIN
    CREATE INDEX IX_audiencia_caso_backfill
    ON jnc.audiencia_caso (
        numero_radicado_normalizado,
        numero_identificacion_normalizado,
        fecha_audiencia
    )
    INCLUDE (
        sala_normalizada,
        numero_acta_normalizado,
        id_archivo,
        hash_audiencia_caso
    )
    WHERE activo = 1;
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'UX_audiencia_caso_archivo_hash'
      AND object_id = OBJECT_ID('jnc.audiencia_caso')
)
BEGIN
    CREATE UNIQUE INDEX UX_audiencia_caso_archivo_hash
    ON jnc.audiencia_caso (
        id_archivo,
        hash_audiencia_caso
    )
    WHERE hash_audiencia_caso IS NOT NULL;
END;
GO
