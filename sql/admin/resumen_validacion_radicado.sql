/*
Resumen de validacion por radicado.

Una fila por caso/radicado, con banderas por tipo_destinatario:
- <categoria>_cumple = al menos una notificacion de esa categoria quedo CUMPLE.
- <categoria>_extemporaneo = al menos una notificacion de esa categoria quedo FUERA_DE_PLAZO.
*/

WITH caso_base AS (
    SELECT
        cc.*,
        COALESCE(
            cc.hoja_trabajo_fecha_audiencia,
            cc.pestana_fecha,
            CASE
                WHEN PATINDEX(
                    '%[0-3][0-9]-[0-1][0-9]-[1-2][0-9][0-9][0-9]%',
                    cc.pestana_nombre
                ) > 0
                THEN TRY_CONVERT(
                    DATE,
                    SUBSTRING(
                        cc.pestana_nombre,
                        PATINDEX(
                            '%[0-3][0-9]-[0-1][0-9]-[1-2][0-9][0-9][0-9]%',
                            cc.pestana_nombre
                        ),
                        10
                    ),
                    105
                )
            END
        ) AS fecha_audiencia_resumen
    FROM jnc.caso_calificado AS cc
    WHERE cc.activo = 1
),
notificacion_estado AS (
    SELECT
        ne.id_caso,
        ne.id_notificacion_esperada,
        UPPER(COALESCE(ne.tipo_destinatario, 'SIN_TIPO_DESTINATARIO')) AS tipo_destinatario,
        COALESCE(
            rcn.estado_revision_notificacion,
            ne.estado_revision_notificacion,
            'SIN_REVISION'
        ) AS estado_revision_notificacion,
        ne.cedula,
        ne.cedula_normalizada
    FROM jnc.notificacion_esperada AS ne
    LEFT JOIN jnc.resultado_cruce_notificacion AS rcn
        ON rcn.id_notificacion_esperada = ne.id_notificacion_esperada
       AND rcn.activo = 1
    WHERE ne.activo = 1
)
SELECT
    cc.numero_radicado,
    cc.pestana_nombre AS nombre_pestana,
    cc.hoja_trabajo_sala AS sala,
    cc.fecha_audiencia_resumen AS fecha_audiencia,
    MAX(ne.cedula) AS cedula,
    cc.nombre_paciente,

    CAST(CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'PACIENTES' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'PACIENTES' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS BIT) AS condicion_pacientes,
    CAST(MAX(CASE WHEN ne.tipo_destinatario = 'PACIENTES' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) AS BIT) AS condicion_pacientes_extemporaneo,

    CAST(CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'REGIONAL' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'REGIONAL' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS BIT) AS condicion_regional,
    CAST(MAX(CASE WHEN ne.tipo_destinatario = 'REGIONAL' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) AS BIT) AS condicion_regional_extemporaneo,

    CAST(CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'EMPLEADOR' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'EMPLEADOR' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS BIT) AS condicion_empleador,
    CAST(MAX(CASE WHEN ne.tipo_destinatario = 'EMPLEADOR' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) AS BIT) AS condicion_empleador_extemporaneo,

    CAST(CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'REMITENTE' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'REMITENTE' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS BIT) AS condicion_remitente,
    CAST(MAX(CASE WHEN ne.tipo_destinatario = 'REMITENTE' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) AS BIT) AS condicion_remitente_extemporaneo,

    CAST(CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'EPS' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'EPS' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS BIT) AS condicion_eps,
    CAST(MAX(CASE WHEN ne.tipo_destinatario = 'EPS' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) AS BIT) AS condicion_eps_extemporaneo,

    CAST(CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'AFP' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'AFP' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS BIT) AS condicion_afp,
    CAST(MAX(CASE WHEN ne.tipo_destinatario = 'AFP' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) AS BIT) AS condicion_afp_extemporaneo,

    CAST(CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'ARL' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'ARL' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS BIT) AS condicion_arl,
    CAST(MAX(CASE WHEN ne.tipo_destinatario = 'ARL' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) AS BIT) AS condicion_arl_extemporaneo,

    CAST(CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'ASEGURADORAS' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'ASEGURADORAS' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS BIT) AS condicion_aseguradoras,
    CAST(MAX(CASE WHEN ne.tipo_destinatario = 'ASEGURADORAS' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) AS BIT) AS condicion_aseguradoras_extemporaneo
FROM caso_base AS cc
LEFT JOIN notificacion_estado AS ne
    ON ne.id_caso = cc.id_caso
GROUP BY
    cc.id_caso,
    cc.numero_radicado,
    cc.pestana_nombre,
    cc.hoja_trabajo_sala,
    cc.fecha_audiencia_resumen,
    cc.nombre_paciente
ORDER BY
    cc.fecha_audiencia_resumen,
    cc.numero_radicado;
