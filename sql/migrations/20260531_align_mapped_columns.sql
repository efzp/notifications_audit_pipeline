/*
Columnas alineadas contra el codigo actual del pipeline.

Crear:
- jnc.caso_calificado: eps, afp, arl, asegurado, comentarios_excel

Eliminar:
- Columnas historicas que no son preparadas, leidas ni actualizadas por el
  codigo actual de carga/cruce.
- No se eliminan llaves identity, columnas base de archivo ni columnas de
  auditoria generica.
*/

IF COL_LENGTH('jnc.caso_calificado', 'eps') IS NULL
BEGIN
    ALTER TABLE jnc.caso_calificado
    ADD eps NVARCHAR(300) NULL;
END;

IF COL_LENGTH('jnc.caso_calificado', 'afp') IS NULL
BEGIN
    ALTER TABLE jnc.caso_calificado
    ADD afp NVARCHAR(300) NULL;
END;

IF COL_LENGTH('jnc.caso_calificado', 'arl') IS NULL
BEGIN
    ALTER TABLE jnc.caso_calificado
    ADD arl NVARCHAR(300) NULL;
END;

IF COL_LENGTH('jnc.caso_calificado', 'asegurado') IS NULL
BEGIN
    ALTER TABLE jnc.caso_calificado
    ADD asegurado NVARCHAR(300) NULL;
END;

IF COL_LENGTH('jnc.caso_calificado', 'comentarios_excel') IS NULL
BEGIN
    ALTER TABLE jnc.caso_calificado
    ADD comentarios_excel NVARCHAR(MAX) NULL;
END;

DECLARE @columnas_eliminar TABLE (
    schema_name SYSNAME NOT NULL,
    table_name SYSNAME NOT NULL,
    column_name SYSNAME NOT NULL
);

INSERT INTO @columnas_eliminar (schema_name, table_name, column_name)
VALUES
    ('jnc', 'caso_calificado', 'periodo_reporte'),
    ('jnc', 'caso_calificado', 'fecha_corte_archivo'),
    ('jnc', 'caso_calificado', 'hoja_origen'),
    ('jnc', 'caso_calificado', 'fila_origen'),
    ('jnc', 'caso_calificado', 'sala'),
    ('jnc', 'caso_calificado', 'fecha_audiencia'),
    ('jnc', 'caso_calificado', 'cedula'),
    ('jnc', 'caso_calificado', 'cedula_normalizada'),
    ('jnc', 'caso_calificado', 'entidad_remitente_normalizada'),
    ('jnc', 'notificacion_esperada', 'entidad_destinatario'),
    ('jnc', 'notificacion_esperada', 'entidad_destinatario_normalizada'),
    ('jnc', 'notificacion_esperada', 'estado_envio_reportado'),
    ('jnc', 'notificacion_esperada', 'estado_recibido_reportado'),
    ('jnc', 'notificacion_esperada', 'texto_envio_original'),
    ('jnc', 'notificacion_esperada', 'texto_recibido_original'),
    ('jnc', 'notificacion_esperada', 'requiere_notificacion'),
    ('jnc', 'notificacion_esperada', 'motivo_no_requiere'),
    ('jnc', 'notificacion_correo_certificado', 'fecha_envio'),
    ('jnc', 'notificacion_correo_certificado', 'fecha_entrega'),
    ('jnc', 'notificacion_correo_certificado', 'cedula_extraida'),
    ('jnc', 'notificacion_correo_certificado', 'cedula_extraida_score'),
    ('jnc', 'notificacion_correo_certificado', 'metodo_extraccion_cedula'),
    ('jnc', 'notificacion_correo_certificado', 'radicado_extraido'),
    ('jnc', 'notificacion_correo_certificado', 'sala_extraida'),
    ('jnc', 'notificacion_correo_certificado', 'entidad_inferida'),
    ('jnc', 'notificacion_correo_certificado', 'entidad_inferida_score'),
    ('jnc', 'notificacion_correo_certificado', 'tipo_destinatario_inferido'),
    ('jnc', 'notificacion_correo_certificado', 'tipo_destinatario_score'),
    ('jnc', 'etl_error_procesamiento', 'fila_origen'),
    ('jnc', 'etl_error_procesamiento', 'columna_origen');

DECLARE
    @schema_name SYSNAME,
    @table_name SYSNAME,
    @column_name SYSNAME,
    @object_name NVARCHAR(517),
    @sql NVARCHAR(MAX);

DECLARE columnas_cursor CURSOR LOCAL FAST_FORWARD FOR
    SELECT schema_name, table_name, column_name
    FROM @columnas_eliminar;

OPEN columnas_cursor;
FETCH NEXT FROM columnas_cursor INTO @schema_name, @table_name, @column_name;

WHILE @@FETCH_STATUS = 0
BEGIN
    SET @object_name = @schema_name + N'.' + @table_name;

    IF COL_LENGTH(@object_name, @column_name) IS NOT NULL
    BEGIN
        SET @sql = NULL;

        SELECT @sql = STRING_AGG(
            N'DROP INDEX '
            + QUOTENAME(index_name)
            + N' ON '
            + QUOTENAME(@schema_name)
            + N'.'
            + QUOTENAME(@table_name)
            + N';',
            CHAR(10)
        )
        FROM (
            SELECT DISTINCT i.name AS index_name
            FROM sys.indexes AS i
            INNER JOIN sys.index_columns AS ic
                ON ic.object_id = i.object_id
               AND ic.index_id = i.index_id
            INNER JOIN sys.columns AS c
                ON c.object_id = ic.object_id
               AND c.column_id = ic.column_id
            WHERE i.object_id = OBJECT_ID(@object_name)
              AND c.name = @column_name
              AND i.name IS NOT NULL
              AND i.is_primary_key = 0
              AND i.is_unique_constraint = 0
        ) AS dependent_indexes;

        IF @sql IS NOT NULL
        BEGIN
            EXEC sp_executesql @sql;
        END;

        SET @sql = NULL;

        SELECT @sql = STRING_AGG(
            N'ALTER TABLE '
            + QUOTENAME(@schema_name)
            + N'.'
            + QUOTENAME(@table_name)
            + N' DROP CONSTRAINT '
            + QUOTENAME(dc.name)
            + N';',
            CHAR(10)
        )
        FROM sys.default_constraints AS dc
        INNER JOIN sys.columns AS c
            ON c.object_id = dc.parent_object_id
           AND c.column_id = dc.parent_column_id
        WHERE dc.parent_object_id = OBJECT_ID(@object_name)
          AND c.name = @column_name;

        IF @sql IS NOT NULL
        BEGIN
            EXEC sp_executesql @sql;
        END;

        SET @sql =
            N'ALTER TABLE '
            + QUOTENAME(@schema_name)
            + N'.'
            + QUOTENAME(@table_name)
            + N' DROP COLUMN '
            + QUOTENAME(@column_name)
            + N';';

        EXEC sp_executesql @sql;
    END;

    FETCH NEXT FROM columnas_cursor INTO @schema_name, @table_name, @column_name;
END;

CLOSE columnas_cursor;
DEALLOCATE columnas_cursor;
