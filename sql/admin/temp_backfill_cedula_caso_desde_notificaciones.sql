/*
Backfill temporal de cedula en jnc.caso_calificado desde jnc.notificacion_esperada.

Uso:
1. Ejecutar primero la migracion:
   sql/migrations/20260603_add_cedula_normalizada_caso_calificado.sql
2. Ejecutar este script con @solo_previsualizar = 1 para revisar candidatos.
3. Cambiar @solo_previsualizar a 0 para aplicar el mapeo.

El update solo modifica casos con cedula o cedula_normalizada faltante, y solo
cuando las notificaciones esperadas asociadas tienen una unica cedula normalizada.
*/

SET XACT_ABORT ON;

DECLARE @solo_previsualizar BIT = 1;

IF COL_LENGTH('jnc.caso_calificado', 'cedula') IS NULL
   OR COL_LENGTH('jnc.caso_calificado', 'cedula_normalizada') IS NULL
BEGIN
    THROW 50010, 'Faltan columnas cedula/cedula_normalizada en jnc.caso_calificado. Ejecute primero la migracion 20260603.', 1;
END;

;WITH notificaciones_por_caso AS (
    SELECT
        cc.id_caso,
        MAX(NULLIF(LTRIM(RTRIM(ne.cedula)), '')) AS cedula,
        MAX(NULLIF(LTRIM(RTRIM(ne.cedula_normalizada)), '')) AS cedula_normalizada,
        COUNT(DISTINCT NULLIF(LTRIM(RTRIM(ne.cedula_normalizada)), '')) AS cedulas_normalizadas_distintas,
        COUNT(*) AS notificaciones_encontradas
    FROM jnc.caso_calificado AS cc
    INNER JOIN jnc.notificacion_esperada AS ne
        ON ne.id_caso = cc.id_caso
        OR (
            ne.id_caso IS NULL
            AND ne.id_archivo = cc.id_archivo
            AND ne.numero_radicado_normalizado = cc.numero_radicado_normalizado
        )
    WHERE
        cc.activo = 1
        AND ne.activo = 1
        AND (
            cc.cedula IS NULL
            OR cc.cedula_normalizada IS NULL
        )
        AND NULLIF(LTRIM(RTRIM(ne.cedula_normalizada)), '') IS NOT NULL
    GROUP BY
        cc.id_caso
),
candidatos AS (
    SELECT
        cc.id_caso,
        cc.id_archivo,
        cc.numero_radicado,
        cc.numero_radicado_normalizado,
        cc.cedula AS cedula_actual,
        cc.cedula_normalizada AS cedula_normalizada_actual,
        npc.cedula AS cedula_desde_notificacion,
        npc.cedula_normalizada AS cedula_normalizada_desde_notificacion,
        npc.notificaciones_encontradas,
        npc.cedulas_normalizadas_distintas
    FROM jnc.caso_calificado AS cc
    INNER JOIN notificaciones_por_caso AS npc
        ON npc.id_caso = cc.id_caso
)
SELECT
    'CANDIDATO_UPDATE' AS tipo_revision,
    *
FROM candidatos
WHERE cedulas_normalizadas_distintas = 1
ORDER BY
    id_archivo,
    numero_radicado_normalizado;

;WITH notificaciones_por_caso AS (
    SELECT
        cc.id_caso,
        COUNT(DISTINCT NULLIF(LTRIM(RTRIM(ne.cedula_normalizada)), '')) AS cedulas_normalizadas_distintas,
        STRING_AGG(CONVERT(NVARCHAR(MAX), NULLIF(LTRIM(RTRIM(ne.cedula_normalizada)), '')), ', ') AS cedulas_detectadas
    FROM jnc.caso_calificado AS cc
    INNER JOIN jnc.notificacion_esperada AS ne
        ON ne.id_caso = cc.id_caso
        OR (
            ne.id_caso IS NULL
            AND ne.id_archivo = cc.id_archivo
            AND ne.numero_radicado_normalizado = cc.numero_radicado_normalizado
        )
    WHERE
        cc.activo = 1
        AND ne.activo = 1
        AND (
            cc.cedula IS NULL
            OR cc.cedula_normalizada IS NULL
        )
        AND NULLIF(LTRIM(RTRIM(ne.cedula_normalizada)), '') IS NOT NULL
    GROUP BY
        cc.id_caso
)
SELECT
    'OMITIDO_CONFLICTO_CEDULA' AS tipo_revision,
    cc.id_caso,
    cc.id_archivo,
    cc.numero_radicado,
    cc.numero_radicado_normalizado,
    npc.cedulas_detectadas
FROM jnc.caso_calificado AS cc
INNER JOIN notificaciones_por_caso AS npc
    ON npc.id_caso = cc.id_caso
WHERE npc.cedulas_normalizadas_distintas > 1
ORDER BY
    cc.id_archivo,
    cc.numero_radicado_normalizado;

IF @solo_previsualizar = 0
BEGIN
    BEGIN TRANSACTION;

    ;WITH notificaciones_por_caso AS (
        SELECT
            cc.id_caso,
            MAX(NULLIF(LTRIM(RTRIM(ne.cedula)), '')) AS cedula,
            MAX(NULLIF(LTRIM(RTRIM(ne.cedula_normalizada)), '')) AS cedula_normalizada,
            COUNT(DISTINCT NULLIF(LTRIM(RTRIM(ne.cedula_normalizada)), '')) AS cedulas_normalizadas_distintas
        FROM jnc.caso_calificado AS cc
        INNER JOIN jnc.notificacion_esperada AS ne
            ON ne.id_caso = cc.id_caso
            OR (
                ne.id_caso IS NULL
                AND ne.id_archivo = cc.id_archivo
                AND ne.numero_radicado_normalizado = cc.numero_radicado_normalizado
            )
        WHERE
            cc.activo = 1
            AND ne.activo = 1
            AND (
                cc.cedula IS NULL
                OR cc.cedula_normalizada IS NULL
            )
            AND NULLIF(LTRIM(RTRIM(ne.cedula_normalizada)), '') IS NOT NULL
        GROUP BY
            cc.id_caso
    )
    UPDATE cc
    SET
        cc.cedula = COALESCE(cc.cedula, npc.cedula),
        cc.cedula_normalizada = COALESCE(cc.cedula_normalizada, npc.cedula_normalizada),
        cc.fecha_actualizacion = SYSUTCDATETIME()
    FROM jnc.caso_calificado AS cc
    INNER JOIN notificaciones_por_caso AS npc
        ON npc.id_caso = cc.id_caso
    WHERE npc.cedulas_normalizadas_distintas = 1;

    SELECT @@ROWCOUNT AS casos_actualizados;

    COMMIT TRANSACTION;
END;
ELSE
BEGIN
    SELECT 'PREVISUALIZACION_SOLAMENTE: cambie @solo_previsualizar a 0 para aplicar el update.' AS mensaje;
END;
