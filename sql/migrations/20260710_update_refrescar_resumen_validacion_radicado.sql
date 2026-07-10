SET XACT_ABORT ON;
GO

IF OBJECT_ID('jnc.resumen_validacion_radicado', 'U') IS NOT NULL
   AND COL_LENGTH('jnc.resumen_validacion_radicado', 'sala') IS NULL
BEGIN
    ALTER TABLE jnc.resumen_validacion_radicado
        ADD sala NVARCHAR(255) NULL;
END;
GO

IF OBJECT_ID('jnc.calificacion_sistema_caso', 'U') IS NOT NULL
   AND COL_LENGTH('jnc.calificacion_sistema_caso', 'sala') IS NULL
BEGIN
    ALTER TABLE jnc.calificacion_sistema_caso
        ADD sala NVARCHAR(255) NULL;
END;
GO

CREATE OR ALTER PROCEDURE jnc.refrescar_resumen_validacion_radicado
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    BEGIN TRANSACTION;

    TRUNCATE TABLE jnc.resumen_validacion_radicado;

    WITH caso_base AS (
        SELECT
            cc.*,
            COALESCE(
                NULLIF(cc.hoja_trabajo_sala, ''),
                NULLIF(cc.hoja_trabajo_sala_normalizada, ''),
                NULLIF(cc.pestana_sala_normalizada, '')
            ) AS sala_caso_calificado,
            csc_resumen.sala AS sala_calificacion_sistema_caso,
            CASE WHEN ac_resumen.id_audiencia_caso IS NULL THEN 0 ELSE 1 END
                AS tiene_acta_audiencia,
            ac_resumen.sala_normalizada AS sala_audiencia_caso,
            ac_resumen.fecha_audiencia AS fecha_audiencia_resumen,
            ac_resumen.nombre_paciente_normalizado AS nombre_paciente_audiencia_caso
        FROM jnc.caso_calificado AS cc
        OUTER APPLY (
            SELECT TOP (1)
                csc.sala
            FROM jnc.calificacion_sistema_caso AS csc
            WHERE csc.activo = 1
              AND csc.numero_radicado_normalizado = cc.numero_radicado_normalizado
              AND (
                    csc.cedula_normalizada = cc.cedula_normalizada
                    OR csc.cedula_normalizada IS NULL
                    OR cc.cedula_normalizada IS NULL
              )
            ORDER BY
                CASE
                    WHEN csc.cedula_normalizada = cc.cedula_normalizada THEN 0
                    ELSE 1
                END,
                csc.fecha_audiencia DESC,
                csc.id_calificacion_sistema_caso DESC
        ) AS csc_resumen
        OUTER APPLY (
            SELECT TOP (1)
                ac.id_audiencia_caso,
                ac.sala_normalizada,
                ac.fecha_audiencia,
                ac.nombre_paciente_normalizado
            FROM jnc.audiencia_caso AS ac
            WHERE ac.activo = 1
              AND ac.numero_radicado_normalizado = cc.numero_radicado_normalizado
            ORDER BY
                ac.fecha_audiencia DESC,
                ac.id_audiencia_caso DESC
        ) AS ac_resumen
        WHERE cc.activo = 1
    ),
    notificacion_estado AS (
        SELECT
            ne.id_caso,
            ne.id_calificacion_sistema_caso,
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
    ),
    resumen_por_caso AS (
        SELECT
            cc.numero_radicado,
            cc.numero_radicado_normalizado,
            cc.pestana_nombre AS nombre_pestana,
            NULLIF(cc.sala_calificacion_sistema_caso, '') AS sala,
            cc.sala_audiencia_caso AS sala_acta,
            cc.sala_caso_calificado,
            CAST(MAX(cc.tiene_acta_audiencia) AS BIT) AS tiene_acta_audiencia,
            cc.fecha_audiencia_resumen AS fecha_audiencia,
            MAX(ne.cedula) AS cedula,
            cc.nombre_paciente_audiencia_caso AS nombre_paciente,

            CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'PACIENTES' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'PACIENTES' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS condicion_pacientes,
            CASE WHEN MAX(CASE WHEN ne.tipo_destinatario = 'PACIENTES' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) = 0 AND MAX(CASE WHEN ne.tipo_destinatario = 'PACIENTES' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) = 1 THEN 1 ELSE 0 END AS condicion_pacientes_extemporaneo,

            CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'REGIONAL' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'REGIONAL' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS condicion_regional,
            CASE WHEN MAX(CASE WHEN ne.tipo_destinatario = 'REGIONAL' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) = 0 AND MAX(CASE WHEN ne.tipo_destinatario = 'REGIONAL' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) = 1 THEN 1 ELSE 0 END AS condicion_regional_extemporaneo,

            CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'EMPLEADOR' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'EMPLEADOR' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS condicion_empleador,
            CASE WHEN MAX(CASE WHEN ne.tipo_destinatario = 'EMPLEADOR' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) = 0 AND MAX(CASE WHEN ne.tipo_destinatario = 'EMPLEADOR' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) = 1 THEN 1 ELSE 0 END AS condicion_empleador_extemporaneo,

            CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'REMITENTE' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'REMITENTE' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS condicion_remitente,
            CASE WHEN MAX(CASE WHEN ne.tipo_destinatario = 'REMITENTE' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) = 0 AND MAX(CASE WHEN ne.tipo_destinatario = 'REMITENTE' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) = 1 THEN 1 ELSE 0 END AS condicion_remitente_extemporaneo,

            CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'EPS' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'EPS' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS condicion_eps,
            CASE WHEN MAX(CASE WHEN ne.tipo_destinatario = 'EPS' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) = 0 AND MAX(CASE WHEN ne.tipo_destinatario = 'EPS' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) = 1 THEN 1 ELSE 0 END AS condicion_eps_extemporaneo,

            CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'AFP' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'AFP' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS condicion_afp,
            CASE WHEN MAX(CASE WHEN ne.tipo_destinatario = 'AFP' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) = 0 AND MAX(CASE WHEN ne.tipo_destinatario = 'AFP' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) = 1 THEN 1 ELSE 0 END AS condicion_afp_extemporaneo,

            CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'ARL' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'ARL' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS condicion_arl,
            CASE WHEN MAX(CASE WHEN ne.tipo_destinatario = 'ARL' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) = 0 AND MAX(CASE WHEN ne.tipo_destinatario = 'ARL' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) = 1 THEN 1 ELSE 0 END AS condicion_arl_extemporaneo,

            CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'ASEGURADORAS' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'ASEGURADORAS' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS condicion_aseguradoras,
            CASE WHEN MAX(CASE WHEN ne.tipo_destinatario = 'ASEGURADORAS' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) = 0 AND MAX(CASE WHEN ne.tipo_destinatario = 'ASEGURADORAS' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) = 1 THEN 1 ELSE 0 END AS condicion_aseguradoras_extemporaneo
        FROM caso_base AS cc
        LEFT JOIN notificacion_estado AS ne
            ON (
                ne.id_caso = cc.id_caso
                OR (
                    ne.id_caso IS NULL
                    AND
                    ne.id_calificacion_sistema_caso IS NOT NULL
                    AND EXISTS (
                        SELECT 1
                        FROM jnc.calificacion_sistema_caso AS csc
                        WHERE csc.id_calificacion_sistema_caso = ne.id_calificacion_sistema_caso
                          AND csc.numero_radicado_normalizado = cc.numero_radicado_normalizado
                    )
                )
            )
        GROUP BY
            cc.id_caso,
            cc.numero_radicado,
            cc.numero_radicado_normalizado,
            cc.pestana_nombre,
            cc.sala_calificacion_sistema_caso,
            cc.sala_audiencia_caso,
            cc.sala_caso_calificado,
            cc.fecha_audiencia_resumen,
            cc.nombre_paciente_audiencia_caso
    ),
    resumen_por_radicado AS (
        SELECT
            MAX(numero_radicado) AS numero_radicado,
            numero_radicado_normalizado,
            MAX(nombre_pestana) AS nombre_pestana,
            MAX(sala) AS sala,
            MAX(sala_acta) AS sala_acta,
            MAX(sala_caso_calificado) AS sala_caso_calificado,
            CAST(MAX(CAST(tiene_acta_audiencia AS INT)) AS BIT) AS tiene_acta_audiencia,
            MAX(fecha_audiencia) AS fecha_audiencia,
            MAX(cedula) AS cedula,
            MAX(nombre_paciente) AS nombre_paciente,
            CAST(MAX(condicion_pacientes) AS BIT) AS condicion_pacientes,
            CAST(CASE WHEN MAX(condicion_pacientes) = 1 THEN 0 ELSE MAX(condicion_pacientes_extemporaneo) END AS BIT) AS condicion_pacientes_extemporaneo,
            CAST(MAX(condicion_regional) AS BIT) AS condicion_regional,
            CAST(CASE WHEN MAX(condicion_regional) = 1 THEN 0 ELSE MAX(condicion_regional_extemporaneo) END AS BIT) AS condicion_regional_extemporaneo,
            CAST(MAX(condicion_empleador) AS BIT) AS condicion_empleador,
            CAST(CASE WHEN MAX(condicion_empleador) = 1 THEN 0 ELSE MAX(condicion_empleador_extemporaneo) END AS BIT) AS condicion_empleador_extemporaneo,
            CAST(MAX(condicion_remitente) AS BIT) AS condicion_remitente,
            CAST(CASE WHEN MAX(condicion_remitente) = 1 THEN 0 ELSE MAX(condicion_remitente_extemporaneo) END AS BIT) AS condicion_remitente_extemporaneo,
            CAST(MAX(condicion_eps) AS BIT) AS condicion_eps,
            CAST(CASE WHEN MAX(condicion_eps) = 1 THEN 0 ELSE MAX(condicion_eps_extemporaneo) END AS BIT) AS condicion_eps_extemporaneo,
            CAST(MAX(condicion_afp) AS BIT) AS condicion_afp,
            CAST(CASE WHEN MAX(condicion_afp) = 1 THEN 0 ELSE MAX(condicion_afp_extemporaneo) END AS BIT) AS condicion_afp_extemporaneo,
            CAST(MAX(condicion_arl) AS BIT) AS condicion_arl,
            CAST(CASE WHEN MAX(condicion_arl) = 1 THEN 0 ELSE MAX(condicion_arl_extemporaneo) END AS BIT) AS condicion_arl_extemporaneo,
            CAST(MAX(condicion_aseguradoras) AS BIT) AS condicion_aseguradoras,
            CAST(CASE WHEN MAX(condicion_aseguradoras) = 1 THEN 0 ELSE MAX(condicion_aseguradoras_extemporaneo) END AS BIT) AS condicion_aseguradoras_extemporaneo
        FROM resumen_por_caso
        GROUP BY
            numero_radicado_normalizado
    ),
    cruces_por_radicado AS (
        SELECT
            rcn_base.numero_radicado_normalizado,
            (
                SELECT
                    rcn.id_resultado_cruce,
                    rcn.id_notificacion_esperada,
                    rcn.id_caso,
                    rcn.id_calificacion_sistema_caso,
                    rcn.id_archivo,
                    rcn.numero_radicado,
                    rcn.numero_radicado_normalizado,
                    rcn.cedula,
                    rcn.cedula_normalizada,
                    rcn.tipo_destinatario,
                    rcn.id_notificacion_correo_certificado_match,
                    rcn.id_archivo_correo_certificado_match,
                    rcn.numero_linea_csv_match,
                    rcn.estado_revision_notificacion,
                    rcn.descripcion_revision,
                    rcn.cumple_documento,
                    rcn.cumple_asunto,
                    rcn.cumple_evento,
                    rcn.cumple_correo,
                    rcn.cumple_plazo,
                    rcn.score_total,
                    rcn.score_asunto,
                    rcn.score_evento,
                    rcn.fuente_documento_match,
                    rcn.asunto_tipo_match,
                    rcn.evento_tipo_match,
                    rcn.tipo_match_correo,
                    rcn.distancia_correo,
                    rcn.correo_esperado,
                    rcn.correo_certificado,
                    rcn.fecha_audiencia,
                    rcn.fecha_envio_certificado,
                    rcn.dias_despues_audiencia,
                    rcn.fecha_revision,
                    rcn.version_regla_cruce,
                    JSON_QUERY(rcn.detalle_revision_json) AS detalle_revision_json
                FROM jnc.resultado_cruce_notificacion AS rcn
                WHERE rcn.activo = 1
                  AND rcn.numero_radicado_normalizado = rcn_base.numero_radicado_normalizado
                ORDER BY
                    rcn.tipo_destinatario,
                    rcn.id_resultado_cruce
                FOR JSON PATH
            ) AS cruces_json
        FROM (
            SELECT DISTINCT
                numero_radicado_normalizado
            FROM jnc.resultado_cruce_notificacion
            WHERE activo = 1
              AND numero_radicado_normalizado IS NOT NULL
        ) AS rcn_base
    )
    INSERT INTO jnc.resumen_validacion_radicado (
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
        cruces_json,
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
    )
    SELECT
        rpr.numero_radicado,
        rpr.numero_radicado_normalizado,
        rpr.nombre_pestana,
        rpr.sala,
        rpr.sala_acta,
        rpr.sala_caso_calificado,
        rpr.tiene_acta_audiencia,
        rpr.fecha_audiencia,
        rpr.cedula,
        rpr.nombre_paciente,
        COALESCE(cg.cruces_json, N'[]') AS cruces_json,
        rpr.condicion_pacientes,
        rpr.condicion_pacientes_extemporaneo,
        rpr.condicion_regional,
        rpr.condicion_regional_extemporaneo,
        rpr.condicion_empleador,
        rpr.condicion_empleador_extemporaneo,
        rpr.condicion_remitente,
        rpr.condicion_remitente_extemporaneo,
        rpr.condicion_eps,
        rpr.condicion_eps_extemporaneo,
        rpr.condicion_afp,
        rpr.condicion_afp_extemporaneo,
        rpr.condicion_arl,
        rpr.condicion_arl_extemporaneo,
        rpr.condicion_aseguradoras,
        rpr.condicion_aseguradoras_extemporaneo,
        CAST(
            CASE
                WHEN rpr.condicion_pacientes = 1
                 AND rpr.condicion_regional = 1
                 AND rpr.condicion_empleador = 1
                 AND rpr.condicion_remitente = 1
                 AND rpr.condicion_eps = 1
                 AND rpr.condicion_afp = 1
                 AND rpr.condicion_arl = 1
                 AND rpr.condicion_aseguradoras = 1
                THEN 1
                ELSE 0
            END AS BIT
        ) AS cumplimiento_total,
        CAST(
            CASE
                WHEN rpr.condicion_pacientes = 1
                 AND rpr.condicion_regional = 1
                 AND rpr.condicion_empleador = 1
                 AND rpr.condicion_remitente = 1
                 AND rpr.condicion_eps = 1
                 AND rpr.condicion_afp = 1
                 AND rpr.condicion_arl = 1
                 AND rpr.condicion_aseguradoras = 1
                THEN 0
                WHEN (rpr.condicion_pacientes = 1 OR rpr.condicion_pacientes_extemporaneo = 1)
                 AND (rpr.condicion_regional = 1 OR rpr.condicion_regional_extemporaneo = 1)
                 AND (rpr.condicion_empleador = 1 OR rpr.condicion_empleador_extemporaneo = 1)
                 AND (rpr.condicion_remitente = 1 OR rpr.condicion_remitente_extemporaneo = 1)
                 AND (rpr.condicion_eps = 1 OR rpr.condicion_eps_extemporaneo = 1)
                 AND (rpr.condicion_afp = 1 OR rpr.condicion_afp_extemporaneo = 1)
                 AND (rpr.condicion_arl = 1 OR rpr.condicion_arl_extemporaneo = 1)
                 AND (rpr.condicion_aseguradoras = 1 OR rpr.condicion_aseguradoras_extemporaneo = 1)
                 AND (
                    rpr.condicion_pacientes_extemporaneo = 1
                    OR rpr.condicion_regional_extemporaneo = 1
                    OR rpr.condicion_empleador_extemporaneo = 1
                    OR rpr.condicion_remitente_extemporaneo = 1
                    OR rpr.condicion_eps_extemporaneo = 1
                    OR rpr.condicion_afp_extemporaneo = 1
                    OR rpr.condicion_arl_extemporaneo = 1
                    OR rpr.condicion_aseguradoras_extemporaneo = 1
                 )
                THEN 1
                ELSE 0
            END AS BIT
        ) AS cumplimiento_extemporaneo,
        NULLIF(
            CONCAT_WS(
                ', ',
                CASE WHEN rpr.condicion_pacientes = 0 AND rpr.condicion_pacientes_extemporaneo = 0 THEN 'PACIENTES' END,
                CASE WHEN rpr.condicion_regional = 0 AND rpr.condicion_regional_extemporaneo = 0 THEN 'REGIONAL' END,
                CASE WHEN rpr.condicion_empleador = 0 AND rpr.condicion_empleador_extemporaneo = 0 THEN 'EMPLEADOR' END,
                CASE WHEN rpr.condicion_remitente = 0 AND rpr.condicion_remitente_extemporaneo = 0 THEN 'REMITENTE' END,
                CASE WHEN rpr.condicion_eps = 0 AND rpr.condicion_eps_extemporaneo = 0 THEN 'EPS' END,
                CASE WHEN rpr.condicion_afp = 0 AND rpr.condicion_afp_extemporaneo = 0 THEN 'AFP' END,
                CASE WHEN rpr.condicion_arl = 0 AND rpr.condicion_arl_extemporaneo = 0 THEN 'ARL' END,
                CASE WHEN rpr.condicion_aseguradoras = 0 AND rpr.condicion_aseguradoras_extemporaneo = 0 THEN 'ASEGURADORAS' END
            ),
            ''
        ) AS no_cumplimiento_revision_manual,
        SYSUTCDATETIME() AS fecha_actualizacion_resumen
    FROM resumen_por_radicado AS rpr
    LEFT JOIN cruces_por_radicado AS cg
        ON cg.numero_radicado_normalizado = rpr.numero_radicado_normalizado;

    COMMIT TRANSACTION;
END;
GO
