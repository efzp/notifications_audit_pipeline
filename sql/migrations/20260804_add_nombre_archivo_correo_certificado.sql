SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID('jnc.notificacion_correo_certificado', 'U') IS NULL
BEGIN
    THROW 50001, 'No existe la tabla jnc.notificacion_correo_certificado.', 1;
END;

IF COL_LENGTH('jnc.notificacion_correo_certificado', 'nombre_archivo') IS NULL
BEGIN
    ALTER TABLE jnc.notificacion_correo_certificado
        ADD nombre_archivo NVARCHAR(500) NULL;
END;

SELECT
    COL_LENGTH('jnc.notificacion_correo_certificado', 'nombre_archivo')
        AS longitud_nombre_archivo;
