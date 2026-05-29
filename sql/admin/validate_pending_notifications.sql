/*
Resumen de validacion por radicado, cedula y campo original.

Regla aplicada:
- Cada fila de notificacion_esperada representa un correo extraido.
- Varios correos pueden venir del mismo campo original de Excel.
- El campo original se considera cumplido si al menos uno de sus correos
  quedo en estado CUMPLE.
- El radicado/cedula se considera CUMPLE si todos sus campos originales
  cumplen.

Para validar todos los casos, cambiar @cedula_a_validar a NULL.
*/

DECLARE @cedula_a_validar NVARCHAR(100) = '35410378';

WITH base AS (
    SELECT
        ne.id_notificacion_esperada,
        COALESCE(CONVERT(NVARCHAR(100), ne.numero_radicado), 'SIN_RADICADO')
            AS numero_radicado,
        COALESCE(CONVERT(NVARCHAR(100), ne.cedula), 'SIN_CEDULA')
            AS cedula,
        COALESCE(CONVERT(NVARCHAR(100), ne.tipo_destinatario), 'SIN_TIPO')
            AS campo_original,
        ne.correo_o_guia_reportado,
        COALESCE(ne.estado_revision_notificacion, 'SIN_REVISION')
            AS estado_revision_notificacion,
        ne.pendiente_revision,
        ac.nombre_archivo,
        ne.pestana_nombre AS hoja_excel,
        ne.hoja_trabajo_sala,
        ne.hoja_trabajo_fecha_audiencia,
        CONCAT(
            COALESCE(ac.nombre_archivo, 'SIN_ARCHIVO'),
            ' | hoja: ',
            COALESCE(ne.pestana_nombre, 'SIN_HOJA'),
            ' | sala: ',
            COALESCE(ne.hoja_trabajo_sala, 'SIN_SALA'),
            ' | fecha audiencia: ',
            COALESCE(CONVERT(VARCHAR(10), ne.hoja_trabajo_fecha_audiencia, 120), 'SIN_FECHA')
        ) AS ubicacion
    FROM jnc.notificacion_esperada AS ne
    LEFT JOIN jnc.etl_archivo_cargado AS ac
        ON ac.id_archivo = ne.id_archivo
    WHERE
        ne.activo = 1
        AND (
            @cedula_a_validar IS NULL
            OR CONVERT(NVARCHAR(100), ne.cedula) = @cedula_a_validar
        )
),
campo_resumen AS (
    SELECT
        numero_radicado,
        cedula,
        campo_original,
        ubicacion,
        COUNT(*) AS correos_evaluados,
        SUM(CASE WHEN estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END)
            AS correos_cumplen,
        SUM(CASE WHEN estado_revision_notificacion <> 'CUMPLE' THEN 1 ELSE 0 END)
            AS correos_no_cumplen,
        MAX(CASE WHEN estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END)
            AS campo_cumple
    FROM base
    GROUP BY
        numero_radicado,
        cedula,
        campo_original,
        ubicacion
),
resumen AS (
    SELECT
        numero_radicado,
        cedula,
        COUNT(*) AS campos_originales,
        SUM(correos_evaluados) AS total_correos_evaluados,
        SUM(correos_cumplen) AS total_correos_cumplen,
        SUM(correos_no_cumplen) AS total_correos_no_cumplen,
        SUM(campo_cumple) AS campos_cumplen,
        SUM(CASE WHEN campo_cumple = 0 THEN 1 ELSE 0 END) AS campos_no_cumplen
    FROM campo_resumen
    GROUP BY
        numero_radicado,
        cedula
),
ubicaciones AS (
    SELECT DISTINCT
        numero_radicado,
        cedula,
        ubicacion
    FROM campo_resumen
),
ubicaciones_agg AS (
    SELECT
        numero_radicado,
        cedula,
        STRING_AGG(ubicacion, ' || ') AS archivos_y_hojas
    FROM ubicaciones
    GROUP BY
        numero_radicado,
        cedula
),
campos AS (
    SELECT
        numero_radicado,
        cedula,
        CONCAT(
            campo_original,
            ': ',
            CASE WHEN campo_cumple = 1 THEN 'CUMPLE' ELSE 'NO_CUMPLE' END,
            ' (correos cumplen ',
            correos_cumplen,
            '/',
            correos_evaluados,
            ')'
        ) AS descripcion_campo
    FROM campo_resumen
),
campos_agg AS (
    SELECT
        numero_radicado,
        cedula,
        STRING_AGG(descripcion_campo, ' || ') AS resumen_campos_originales
    FROM campos
    GROUP BY
        numero_radicado,
        cedula
),
errores AS (
    SELECT DISTINCT
        b.numero_radicado,
        b.cedula,
        CONCAT(
            b.campo_original,
            ' - ',
            b.estado_revision_notificacion,
            ': ',
            COALESCE(b.pendiente_revision, 'Sin descripcion')
        ) AS descripcion_error
    FROM base AS b
    INNER JOIN campo_resumen AS cr
        ON cr.numero_radicado = b.numero_radicado
        AND cr.cedula = b.cedula
        AND cr.campo_original = b.campo_original
        AND cr.ubicacion = b.ubicacion
    WHERE
        cr.campo_cumple = 0
        AND b.estado_revision_notificacion <> 'CUMPLE'
),
errores_agg AS (
    SELECT
        numero_radicado,
        cedula,
        STRING_AGG(descripcion_error, ' || ') AS descripcion_error
    FROM errores
    GROUP BY
        numero_radicado,
        cedula
)
SELECT
    r.numero_radicado,
    r.cedula,
    r.campos_originales,
    r.campos_cumplen,
    r.campos_no_cumplen,
    r.total_correos_evaluados,
    r.total_correos_cumplen,
    r.total_correos_no_cumplen,
    CASE
        WHEN r.campos_no_cumplen = 0 THEN 'CUMPLE'
        WHEN r.campos_cumplen > 0 THEN 'CUMPLE_PARCIAL'
        ELSE 'NO_CUMPLE'
    END AS estado_resumen,
    u.archivos_y_hojas,
    c.resumen_campos_originales,
    e.descripcion_error
FROM resumen AS r
LEFT JOIN ubicaciones_agg AS u
    ON u.numero_radicado = r.numero_radicado
    AND u.cedula = r.cedula
LEFT JOIN campos_agg AS c
    ON c.numero_radicado = r.numero_radicado
    AND c.cedula = r.cedula
LEFT JOIN errores_agg AS e
    ON e.numero_radicado = r.numero_radicado
    AND e.cedula = r.cedula
ORDER BY
    r.campos_no_cumplen DESC,
    r.numero_radicado,
    r.cedula;
