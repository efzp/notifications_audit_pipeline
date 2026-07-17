/*
Consulta del resumen cacheado de validacion por radicado.

La tabla se refresca desde la Function al terminar el cruce de notificaciones,
ejecutando el procedimiento:
EXEC jnc.refrescar_resumen_validacion_radicado;
*/

SELECT
    numero_radicado,
    numero_radicado_normalizado,
    nombre_pestana,
    sala,
    sala_acta,
    sala_caso_calificado,
    tiene_acta_audiencia,
    fecha_audiencia,
    cedula,
    nombre_paciente,
    condicion_pacientes,
    condicion_pacientes_extemporaneo,
    condicion_regional,
    condicion_regional_extemporaneo,
    condicion_empleador,
    condicion_empleador_extemporaneo,
    condicion_remitente,
    condicion_remitente_extemporaneo,
    condicion_eps,
    condicion_eps_extemporaneo,
    condicion_afp,
    condicion_afp_extemporaneo,
    condicion_arl,
    condicion_arl_extemporaneo,
    condicion_aseguradoras,
    condicion_aseguradoras_extemporaneo,
    cumplimiento_total,
    cumplimiento_extemporaneo,
    no_cumplimiento_revision_manual,
    fecha_actualizacion_resumen
FROM jnc.resumen_validacion_radicado;

-- Para consultar el resumen ordenado, usa:
-- SELECT *
-- FROM jnc.resumen_validacion_radicado
-- ORDER BY fecha_audiencia, numero_radicado_normalizado;

/*
Validacion puntual de auditoria manual:
cedulas/radicados marcados manualmente con cumplimiento_manual = 1
vs. validacion por guia fisica en resultado_cruce_notificacion.

Reemplace el CTE manual_auditoria con las filas del Excel:
(numero_radicado_normalizado, cedula_normalizada, cumplimiento_manual)
*/

WITH manual_auditoria AS (
    SELECT
        v.numero_radicado_normalizado,
        v.cedula_normalizada,
        v.cumplimiento_manual
    FROM (VALUES
        -- Ejemplo:
        -- (N'RADICADO_NORMALIZADO', N'CEDULA_NORMALIZADA', 1)
        (CAST(NULL AS NVARCHAR(100)), CAST(NULL AS NVARCHAR(50)), CAST(NULL AS INT))
    ) AS v (
        numero_radicado_normalizado,
        cedula_normalizada,
        cumplimiento_manual
    )
    WHERE v.numero_radicado_normalizado IS NOT NULL
),
manual_validado AS (
    SELECT
        UPPER(
            REPLACE(
                REPLACE(
                    REPLACE(
                        REPLACE(LTRIM(RTRIM(numero_radicado_normalizado)), ' ', ''),
                        '-',
                        ''
                    ),
                    '.',
                    ''
                ),
                ',',
                ''
            )
        ) AS numero_radicado_normalizado,
        REPLACE(
            REPLACE(
                REPLACE(LTRIM(RTRIM(cedula_normalizada)), ' ', ''),
                '.',
                ''
            ),
            ',',
            ''
        ) AS cedula_normalizada,
        TRY_CONVERT(INT, cumplimiento_manual) AS cumplimiento_manual
    FROM manual_auditoria
    WHERE TRY_CONVERT(INT, cumplimiento_manual) = 1
),
cruce_por_guia AS (
    SELECT
        rcn.numero_radicado_normalizado,
        rcn.cedula_normalizada,
        MAX(
            CASE
                WHEN JSON_VALUE(rcn.detalle_revision_json, '$.fuente_revision') = 'GUIA_CORREO_FISICO'
                    THEN 1
                ELSE 0
            END
        ) AS tiene_cruce_por_guia,
        MAX(
            CASE
                WHEN JSON_VALUE(rcn.detalle_revision_json, '$.fuente_revision') = 'GUIA_CORREO_FISICO'
                    AND rcn.estado_revision_notificacion = 'CUMPLE'
                    THEN 1
                ELSE 0
            END
        ) AS validado_por_guia_en_plazo,
        MAX(
            CASE
                WHEN JSON_VALUE(rcn.detalle_revision_json, '$.fuente_revision') = 'GUIA_CORREO_FISICO'
                    AND rcn.estado_revision_notificacion = 'FUERA_DE_PLAZO'
                    THEN 1
                ELSE 0
            END
        ) AS validado_por_guia_extemporaneo,
        COUNT(
            CASE
                WHEN JSON_VALUE(rcn.detalle_revision_json, '$.fuente_revision') = 'GUIA_CORREO_FISICO'
                    THEN 1
            END
        ) AS notificaciones_cruzadas_por_guia
    FROM jnc.resultado_cruce_notificacion AS rcn
    WHERE rcn.activo = 1
    GROUP BY
        rcn.numero_radicado_normalizado,
        rcn.cedula_normalizada
)
SELECT
    mv.numero_radicado_normalizado,
    mv.cedula_normalizada,
    mv.cumplimiento_manual,
    COALESCE(cg.tiene_cruce_por_guia, 0) AS tiene_cruce_por_guia,
    COALESCE(cg.validado_por_guia_en_plazo, 0) AS validado_por_guia_en_plazo,
    COALESCE(cg.validado_por_guia_extemporaneo, 0) AS validado_por_guia_extemporaneo,
    COALESCE(cg.notificaciones_cruzadas_por_guia, 0)
        AS notificaciones_cruzadas_por_guia,
    CASE
        WHEN COALESCE(cg.validado_por_guia_en_plazo, 0) = 1
            THEN 'VALIDADO_POR_GUIA'
        WHEN COALESCE(cg.validado_por_guia_extemporaneo, 0) = 1
            THEN 'VALIDADO_POR_GUIA_EXTEMPORANEO'
        WHEN COALESCE(cg.tiene_cruce_por_guia, 0) = 1
            THEN 'CRUCE_GUIA_SIN_CUMPLIMIENTO'
        ELSE 'SIN_CRUCE_POR_GUIA'
    END AS resultado_validacion_guia
FROM manual_validado AS mv
LEFT JOIN cruce_por_guia AS cg
    ON cg.numero_radicado_normalizado = mv.numero_radicado_normalizado
    AND cg.cedula_normalizada = mv.cedula_normalizada
ORDER BY
    resultado_validacion_guia,
    mv.numero_radicado_normalizado,
    mv.cedula_normalizada;

-- Detalle de evidencia de guia para las mismas filas manuales.
WITH manual_auditoria AS (
    SELECT
        v.numero_radicado_normalizado,
        v.cedula_normalizada,
        v.cumplimiento_manual
    FROM (VALUES
        -- Ejemplo:
        -- (N'RADICADO_NORMALIZADO', N'CEDULA_NORMALIZADA', 1)
        (CAST(NULL AS NVARCHAR(100)), CAST(NULL AS NVARCHAR(50)), CAST(NULL AS INT))
    ) AS v (
        numero_radicado_normalizado,
        cedula_normalizada,
        cumplimiento_manual
    )
    WHERE v.numero_radicado_normalizado IS NOT NULL
),
manual_validado AS (
    SELECT
        UPPER(
            REPLACE(
                REPLACE(
                    REPLACE(
                        REPLACE(LTRIM(RTRIM(numero_radicado_normalizado)), ' ', ''),
                        '-',
                        ''
                    ),
                    '.',
                    ''
                ),
                ',',
                ''
            )
        ) AS numero_radicado_normalizado,
        REPLACE(
            REPLACE(
                REPLACE(LTRIM(RTRIM(cedula_normalizada)), ' ', ''),
                '.',
                ''
            ),
            ',',
            ''
        ) AS cedula_normalizada,
        TRY_CONVERT(INT, cumplimiento_manual) AS cumplimiento_manual
    FROM manual_auditoria
    WHERE TRY_CONVERT(INT, cumplimiento_manual) = 1
)
SELECT
    mv.numero_radicado_normalizado,
    mv.cedula_normalizada,
    rcn.tipo_destinatario,
    rcn.estado_revision_notificacion,
    rcn.descripcion_revision,
    rcn.cumple_documento,
    rcn.cumple_correo,
    rcn.cumple_evento,
    rcn.cumple_plazo,
    JSON_VALUE(rcn.detalle_revision_json, '$.guia_fisica.metodo_busqueda')
        AS metodo_busqueda_guia,
    JSON_VALUE(rcn.detalle_revision_json, '$.guia_fisica.guia_esperada')
        AS guia_esperada,
    JSON_VALUE(rcn.detalle_revision_json, '$.guia_fisica.guia_fisica')
        AS guia_fisica,
    JSON_VALUE(rcn.detalle_revision_json, '$.guia_fisica.cedula_guia')
        AS cedula_guia,
    JSON_VALUE(rcn.detalle_revision_json, '$.guia_fisica.estado_guia')
        AS estado_guia,
    JSON_VALUE(rcn.detalle_revision_json, '$.guia_fisica.fecha_entrega_guia')
        AS fecha_entrega_guia,
    JSON_VALUE(rcn.detalle_revision_json, '$.guia_fisica.id_guia_correo_fisico')
        AS id_guia_correo_fisico,
    rcn.fecha_revision,
    rcn.id_resultado_cruce,
    rcn.id_notificacion_esperada
FROM manual_validado AS mv
INNER JOIN jnc.resultado_cruce_notificacion AS rcn
    ON rcn.numero_radicado_normalizado = mv.numero_radicado_normalizado
    AND rcn.cedula_normalizada = mv.cedula_normalizada
    AND rcn.activo = 1
    AND JSON_VALUE(rcn.detalle_revision_json, '$.fuente_revision') = 'GUIA_CORREO_FISICO'
ORDER BY
    mv.numero_radicado_normalizado,
    mv.cedula_normalizada,
    rcn.tipo_destinatario,
    rcn.estado_revision_notificacion;
