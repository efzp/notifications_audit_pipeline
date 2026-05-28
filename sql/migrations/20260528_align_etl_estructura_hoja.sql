IF COL_LENGTH('jnc.etl_estructura_hoja', 'hoja_trabajo_sala_celda') IS NULL
BEGIN
    ALTER TABLE jnc.etl_estructura_hoja
    ADD hoja_trabajo_sala_celda NVARCHAR(50) NULL;
END;

IF COL_LENGTH('jnc.etl_estructura_hoja', 'hoja_trabajo_fecha_audiencia_celda') IS NULL
BEGIN
    ALTER TABLE jnc.etl_estructura_hoja
    ADD hoja_trabajo_fecha_audiencia_celda NVARCHAR(50) NULL;
END;

IF COL_LENGTH('jnc.etl_estructura_hoja', 'ubicacion_columnas_wide_json') IS NULL
BEGIN
    ALTER TABLE jnc.etl_estructura_hoja
    ADD ubicacion_columnas_wide_json NVARCHAR(MAX) NULL;
END;

IF COL_LENGTH('jnc.etl_estructura_hoja', 'ubicacion_columnas_detalle_json') IS NULL
BEGIN
    ALTER TABLE jnc.etl_estructura_hoja
    ADD ubicacion_columnas_detalle_json NVARCHAR(MAX) NULL;
END;

IF COL_LENGTH('jnc.etl_estructura_hoja', 'estructura_faltantes_json') IS NULL
BEGIN
    ALTER TABLE jnc.etl_estructura_hoja
    ADD estructura_faltantes_json NVARCHAR(MAX) NULL;
END;
