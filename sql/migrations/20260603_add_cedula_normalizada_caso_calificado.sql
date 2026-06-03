/*
Agrega cedula normalizada a jnc.caso_calificado.

El ETL ya extrae la cedula desde tabla_casos; estas columnas permiten
persistir el valor original y su version normalizada en el caso calificado.
*/

IF COL_LENGTH('jnc.caso_calificado', 'cedula') IS NULL
BEGIN
    ALTER TABLE jnc.caso_calificado
    ADD cedula NVARCHAR(50) NULL;
END;

IF COL_LENGTH('jnc.caso_calificado', 'cedula_normalizada') IS NULL
BEGIN
    ALTER TABLE jnc.caso_calificado
    ADD cedula_normalizada NVARCHAR(50) NULL;
END;
