/*
Limpia las tablas operativas del pipeline JNC Notificaciones.

Uso recomendado:
1. Ejecutar en ambiente DEV o con ventana controlada.
2. Revisar que no haya ejecuciones de Power Automate/Azure Functions activas.
3. Ejecutar todo el script dentro de una transaccion.

ADVERTENCIA: elimina los registros cargados y el control de archivos.
*/

BEGIN TRANSACTION;

IF OBJECT_ID('jnc.resultado_cruce_notificacion', 'U') IS NOT NULL
BEGIN
    DELETE FROM jnc.resultado_cruce_notificacion;
END;

IF OBJECT_ID('jnc.resumen_validacion_radicado', 'U') IS NOT NULL
BEGIN
    DELETE FROM jnc.resumen_validacion_radicado;
END;

DELETE FROM jnc.notificacion_esperada;
DELETE FROM jnc.notificacion_correo_certificado;
DELETE FROM jnc.caso_calificado;
DELETE FROM jnc.etl_estructura_hoja;
DELETE FROM jnc.etl_error_procesamiento;
DELETE FROM jnc.etl_ejecucion_regla;
DELETE FROM jnc.etl_archivo_cargado;

IF OBJECT_ID('jnc.resultado_cruce_notificacion', 'U') IS NOT NULL
BEGIN
    DBCC CHECKIDENT ('jnc.resultado_cruce_notificacion', RESEED, 0);
END;

IF OBJECT_ID('jnc.resumen_validacion_radicado', 'U') IS NOT NULL
BEGIN
    DBCC CHECKIDENT ('jnc.resumen_validacion_radicado', RESEED, 0);
END;

DBCC CHECKIDENT ('jnc.notificacion_esperada', RESEED, 0);
DBCC CHECKIDENT ('jnc.notificacion_correo_certificado', RESEED, 0);
DBCC CHECKIDENT ('jnc.caso_calificado', RESEED, 0);
DBCC CHECKIDENT ('jnc.etl_estructura_hoja', RESEED, 0);
DBCC CHECKIDENT ('jnc.etl_error_procesamiento', RESEED, 0);
DBCC CHECKIDENT ('jnc.etl_ejecucion_regla', RESEED, 0);
DBCC CHECKIDENT ('jnc.etl_archivo_cargado', RESEED, 0);

COMMIT TRANSACTION;
