/*
Refuerzo de idempotencia para jnc.caso_calificado.

El codigo ahora calcula hash_caso solo con campos de negocio, excluyendo
campos volatiles como id_archivo, fecha_creacion y fecha_actualizacion.
Este indice evita duplicados exactos dentro del mismo archivo procesado.
*/

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'UX_caso_calificado_archivo_hash'
      AND object_id = OBJECT_ID('jnc.caso_calificado')
)
BEGIN
    CREATE UNIQUE INDEX UX_caso_calificado_archivo_hash
    ON jnc.caso_calificado (
        id_archivo,
        hash_caso
    )
    WHERE hash_caso IS NOT NULL
      AND activo = 1;
END;
