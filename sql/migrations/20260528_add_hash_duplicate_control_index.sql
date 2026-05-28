IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_etl_archivo_cargado_hash_tipo_estado'
      AND object_id = OBJECT_ID('jnc.etl_archivo_cargado')
)
BEGIN
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
END;
