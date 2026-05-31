/*
Estatus de validacion de radicados para una cedula.

Replica la regla del flujo:
- RADICADO_VALIDADO: todos los campos originales del radicado tienen
  al menos una notificacion en CUMPLE.
- RADICADO_VALIDADO_EXTEMPORANEO: no todos los campos tienen CUMPLE,
  pero todos tienen al menos CUMPLE o FUERA_DE_PLAZO, y al menos un campo
  tiene FUERA_DE_PLAZO sin CUMPLE.
- RADICADO_PENDIENTE: cualquier otro caso.

Para validar todos los casos, cambiar @cedula_a_validar a NULL.
*/

DECLARE @cedula_a_validar NVARCHAR(100) = '75072067';

IF OBJECT_ID('tempdb..#base') IS NOT NULL DROP TABLE #base;
IF OBJECT_ID('tempdb..#campo_estado') IS NOT NULL DROP TABLE #campo_estado;
IF OBJECT_ID('tempdb..#radicado_validacion') IS NOT NULL DROP TABLE #radicado_validacion;

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
    ne.fecha_revision_notificacion,
    ne.id_notificacion_correo_certificado_match,
    JSON_VALUE(ne.detalle_revision_json, '$.id_archivo_correo_certificado_match')
        AS id_archivo_correo_certificado_match,
    JSON_VALUE(ne.detalle_revision_json, '$.numero_linea_csv_match')
        AS numero_linea_csv_match,
    JSON_VALUE(ne.detalle_revision_json, '$.correo_certificado')
        AS correo_certificado_match,
    JSON_VALUE(ne.detalle_revision_json, '$.correo_esperado')
        AS correo_esperado_match,
    JSON_VALUE(ne.detalle_revision_json, '$.fecha_envio_certificado')
        AS fecha_envio_certificado_match,
    JSON_VALUE(ne.detalle_revision_json, '$.dias_despues_audiencia')
        AS dias_despues_audiencia,
    JSON_VALUE(ne.detalle_revision_json, '$.score_asunto')
        AS score_asunto,
    JSON_VALUE(ne.detalle_revision_json, '$.score_evento')
        AS score_evento,
    JSON_VALUE(ne.detalle_revision_json, '$.asunto_tipo_match')
        AS asunto_tipo_match,
    JSON_VALUE(ne.detalle_revision_json, '$.evento_tipo_match')
        AS evento_tipo_match,
    ac.nombre_archivo,
    ne.pestana_nombre AS hoja_excel,
    ne.hoja_trabajo_sala,
    ne.hoja_trabajo_fecha_audiencia
INTO #base
FROM jnc.notificacion_esperada AS ne
LEFT JOIN jnc.etl_archivo_cargado AS ac
    ON ac.id_archivo = ne.id_archivo
WHERE
    ne.activo = 1
    AND (
        @cedula_a_validar IS NULL
        OR CONVERT(NVARCHAR(100), ne.cedula) = @cedula_a_validar
    );

SELECT
    numero_radicado,
    cedula,
    campo_original,
    MAX(CASE WHEN estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END)
        AS campo_tiene_cumple,
    MAX(
        CASE
            WHEN estado_revision_notificacion IN ('CUMPLE', 'FUERA_DE_PLAZO')
                THEN 1
            ELSE 0
        END
    ) AS campo_tiene_cumple_o_fuera_de_plazo,
    MAX(
        CASE
            WHEN estado_revision_notificacion = 'FUERA_DE_PLAZO'
                THEN 1
            ELSE 0
        END
    ) AS campo_tiene_fuera_de_plazo,
    COUNT(*) AS notificaciones_campo
INTO #campo_estado
FROM #base
GROUP BY
    numero_radicado,
    cedula,
    campo_original;

WITH radicado_estado AS (
    SELECT
        numero_radicado,
        cedula,
        COUNT(*) AS campos_evaluados,
        SUM(campo_tiene_cumple) AS campos_con_cumple,
        SUM(campo_tiene_cumple_o_fuera_de_plazo)
            AS campos_con_cumple_o_fuera_de_plazo,
        SUM(
            CASE
                WHEN campo_tiene_cumple = 0
                    AND campo_tiene_fuera_de_plazo = 1
                    THEN 1
                ELSE 0
            END
        ) AS campos_extemporaneos_sin_cumple,
        SUM(notificaciones_campo) AS notificaciones_evaluadas
    FROM #campo_estado
    GROUP BY
        numero_radicado,
        cedula
)
SELECT
    numero_radicado,
    cedula,
    CASE
        WHEN campos_evaluados > 0
            AND campos_con_cumple = campos_evaluados
            THEN 'RADICADO_VALIDADO'
        WHEN campos_evaluados > 0
            AND campos_con_cumple < campos_evaluados
            AND campos_con_cumple_o_fuera_de_plazo = campos_evaluados
            AND campos_extemporaneos_sin_cumple > 0
            THEN 'RADICADO_VALIDADO_EXTEMPORANEO'
        ELSE 'RADICADO_PENDIENTE'
    END AS estatus_radicado,
    campos_evaluados,
    campos_con_cumple,
    campos_con_cumple_o_fuera_de_plazo,
    campos_extemporaneos_sin_cumple,
    notificaciones_evaluadas
INTO #radicado_validacion
FROM radicado_estado;

-- Output equivalente al resumen cruce_notificaciones del flujo, filtrado por cedula.
SELECT
    @cedula_a_validar AS cedula_consultada,
    COUNT(*) AS radicados_evaluados,
    SUM(CASE WHEN estatus_radicado = 'RADICADO_VALIDADO' THEN 1 ELSE 0 END)
        AS radicados_validados,
    SUM(CASE WHEN estatus_radicado = 'RADICADO_VALIDADO_EXTEMPORANEO' THEN 1 ELSE 0 END)
        AS radicados_validados_extemporaneos,
    SUM(CASE WHEN estatus_radicado = 'RADICADO_PENDIENTE' THEN 1 ELSE 0 END)
        AS radicados_pendientes,
    CAST(
        CASE
            WHEN COUNT(*) = 0 THEN 0.0
            ELSE
                SUM(CASE WHEN estatus_radicado = 'RADICADO_VALIDADO' THEN 1 ELSE 0 END)
                * 100.0 / COUNT(*)
        END
        AS DECIMAL(10, 2)
    ) AS porcentaje_radicados_validados,
    CAST(
        CASE
            WHEN COUNT(*) = 0 THEN 0.0
            ELSE
                SUM(CASE WHEN estatus_radicado = 'RADICADO_VALIDADO_EXTEMPORANEO' THEN 1 ELSE 0 END)
                * 100.0 / COUNT(*)
        END
        AS DECIMAL(10, 2)
    ) AS porcentaje_radicados_validados_extemporaneos
FROM #radicado_validacion;

-- Resumen: una fila por radicado de la cedula.
SELECT
    numero_radicado,
    cedula,
    estatus_radicado,
    campos_evaluados,
    campos_con_cumple,
    campos_con_cumple_o_fuera_de_plazo,
    campos_extemporaneos_sin_cumple,
    notificaciones_evaluadas
FROM #radicado_validacion
ORDER BY
    numero_radicado,
    cedula;

-- Detalle: evidencia por campo original y notificacion evaluada.
SELECT
    rv.numero_radicado,
    rv.cedula,
    rv.estatus_radicado,
    b.campo_original,
    CASE
        WHEN ce.campo_tiene_cumple = 1
            THEN 'CAMPO_VALIDADO'
        WHEN ce.campo_tiene_fuera_de_plazo = 1
            THEN 'CAMPO_EXTEMPORANEO'
        ELSE 'CAMPO_PENDIENTE'
    END AS estatus_campo,
    b.estado_revision_notificacion,
    b.pendiente_revision AS descripcion_revision,
    b.correo_o_guia_reportado,
    b.correo_esperado_match,
    b.correo_certificado_match,
    b.hoja_trabajo_fecha_audiencia,
    b.fecha_envio_certificado_match,
    b.dias_despues_audiencia,
    b.nombre_archivo,
    b.hoja_excel,
    b.hoja_trabajo_sala,
    b.id_notificacion_esperada,
    b.id_notificacion_correo_certificado_match,
    b.id_archivo_correo_certificado_match,
    b.numero_linea_csv_match,
    b.score_asunto,
    b.score_evento,
    b.asunto_tipo_match,
    b.evento_tipo_match,
    b.fecha_revision_notificacion
FROM #base AS b
INNER JOIN #campo_estado AS ce
    ON ce.numero_radicado = b.numero_radicado
    AND ce.cedula = b.cedula
    AND ce.campo_original = b.campo_original
INNER JOIN #radicado_validacion AS rv
    ON rv.numero_radicado = b.numero_radicado
    AND rv.cedula = b.cedula
ORDER BY
    rv.numero_radicado,
    rv.cedula,
    b.campo_original,
    CASE
        WHEN b.estado_revision_notificacion = 'CUMPLE' THEN 1
        WHEN b.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 2
        ELSE 3
    END,
    b.estado_revision_notificacion,
    b.correo_o_guia_reportado;
