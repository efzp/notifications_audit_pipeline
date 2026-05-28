IF COL_LENGTH('jnc.caso_calificado', 'pago_entidad') IS NULL
BEGIN
    ALTER TABLE jnc.caso_calificado
    ADD pago_entidad NVARCHAR(255) NULL;
END;

IF COL_LENGTH('jnc.caso_calificado', 'rp') IS NULL
BEGIN
    ALTER TABLE jnc.caso_calificado
    ADD rp NVARCHAR(100) NULL;
END;
