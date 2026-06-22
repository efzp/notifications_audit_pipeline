/*
Vista para auditoria manual de notificaciones pendientes.

Granularidad: una fila por radicado, cedula y entidad pendiente de cumplimiento.
Pensada para consumo desde Excel/Power BI sin modificar la tabla cacheada de
resumen por radicado.
*/

CREATE OR ALTER VIEW jnc.vw_auditoria_manual_notificaciones_pendientes
AS
WITH casos_candidatos AS (
    SELECT
        cc.id_caso,
        cc.id_archivo,
        cc.numero_radicado,
        cc.numero_radicado_normalizado,
        cc.pestana_nombre,
        cc.cedula,
        cc.cedula_normalizada,
        cc.nombre_paciente,
        cc.eps,
        cc.entidad_remitente,
        cc.arl,
        cc.afp,
        cc.asegurado,
        ac.nombre_archivo,
        ac.ruta_sharepoint,
        ac.carpeta_origen,
        ac.fecha_llegada,
        ac.fecha_fin_proceso,
        ac.fecha_creacion AS fecha_creacion_archivo,
        ac.estructura_valida AS archivo_estructura_valida,
        ac.procesador_status,
        TRY_CONVERT(
            DATE,
            SUBSTRING(
                ac.nombre_archivo,
                NULLIF(
                    PATINDEX(
                        '%[0-3][0-9]-[0-1][0-9]-[1-2][0-9][0-9][0-9]%',
                        ac.nombre_archivo
                    ),
                    0
                ),
                10
            ),
            105
        ) AS fecha_archivo_ddmmyyyy,
        TRY_CONVERT(
            DATE,
            SUBSTRING(
                ac.nombre_archivo,
                NULLIF(
                    PATINDEX(
                        '%[1-2][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]%',
                        ac.nombre_archivo
                    ),
                    0
                ),
                10
            ),
            23
        ) AS fecha_archivo_yyyymmdd,
        ROW_NUMBER() OVER (
            PARTITION BY cc.numero_radicado_normalizado
            ORDER BY
                CASE
                    WHEN ac.estructura_valida = 1
                     AND COALESCE(ac.procesador_status, 'OK') = 'OK'
                        THEN 1
                    ELSE 0
                END DESC,
                COALESCE(
                    TRY_CONVERT(
                        DATE,
                        SUBSTRING(
                            ac.nombre_archivo,
                            NULLIF(
                                PATINDEX(
                                    '%[0-3][0-9]-[0-1][0-9]-[1-2][0-9][0-9][0-9]%',
                                    ac.nombre_archivo
                                ),
                                0
                            ),
                            10
                        ),
                        105
                    ),
                    TRY_CONVERT(
                        DATE,
                        SUBSTRING(
                            ac.nombre_archivo,
                            NULLIF(
                                PATINDEX(
                                    '%[1-2][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]%',
                                    ac.nombre_archivo
                                ),
                                0
                            ),
                            10
                        ),
                        23
                    )
                ) DESC,
                ac.fecha_fin_proceso DESC,
                ac.fecha_llegada DESC,
                cc.id_archivo DESC,
                cc.id_caso DESC
        ) AS rn
    FROM jnc.caso_calificado AS cc
    LEFT JOIN jnc.etl_archivo_cargado AS ac
        ON ac.id_archivo = cc.id_archivo
    WHERE cc.activo = 1
      AND cc.numero_radicado_normalizado IS NOT NULL
),
caso_oficial AS (
    SELECT
        id_caso,
        id_archivo,
        numero_radicado,
        numero_radicado_normalizado,
        pestana_nombre,
        cedula,
        cedula_normalizada,
        nombre_paciente,
        eps,
        entidad_remitente,
        arl,
        afp,
        asegurado,
        nombre_archivo,
        ruta_sharepoint,
        carpeta_origen,
        fecha_llegada,
        fecha_fin_proceso,
        fecha_creacion_archivo,
        archivo_estructura_valida,
        procesador_status,
        COALESCE(fecha_archivo_ddmmyyyy, fecha_archivo_yyyymmdd) AS fecha_parseada_nombre_archivo
    FROM casos_candidatos
    WHERE rn = 1
),
notificacion_estado AS (
    SELECT
        ne.id_notificacion_esperada,
        ne.id_caso,
        ne.id_calificacion_sistema_caso,
        ne.id_archivo,
        ne.numero_radicado,
        ne.numero_radicado_normalizado,
        ne.cedula,
        ne.cedula_normalizada,
        UPPER(COALESCE(ne.tipo_destinatario, 'SIN_TIPO_DESTINATARIO')) AS tipo_destinatario,
        ne.correo_o_guia_reportado,
        ne.correo_normalizado,
        ne.fecha_envio_reportada,
        ne.pendiente_revision,
        ne.fecha_revision_notificacion,
        COALESCE(
            rcn.estado_revision_notificacion,
            ne.estado_revision_notificacion,
            'SIN_REVISION'
        ) AS estado_revision_notificacion
    FROM jnc.notificacion_esperada AS ne
    LEFT JOIN jnc.resultado_cruce_notificacion AS rcn
        ON rcn.id_notificacion_esperada = ne.id_notificacion_esperada
       AND rcn.activo = 1
    WHERE ne.activo = 1
),
notificaciones_pendientes AS (
    SELECT
        ne.*
    FROM notificacion_estado AS ne
    INNER JOIN jnc.cruce_notificacion_pendiente AS cnp
        ON cnp.id_notificacion_esperada = ne.id_notificacion_esperada
       AND cnp.activo = 1
    INNER JOIN jnc.resumen_validacion_radicado AS rvr
        ON rvr.numero_radicado_normalizado = ne.numero_radicado_normalizado
    WHERE rvr.cumplimiento_total = 0
      AND rvr.cumplimiento_extemporaneo = 0
      AND ne.estado_revision_notificacion NOT IN ('CUMPLE', 'FUERA_DE_PLAZO')
      AND NOT EXISTS (
        SELECT 1
        FROM notificacion_estado AS ne_validada
        WHERE ne_validada.numero_radicado_normalizado = ne.numero_radicado_normalizado
          AND COALESCE(ne_validada.cedula_normalizada, '') = COALESCE(ne.cedula_normalizada, '')
          AND ne_validada.tipo_destinatario = ne.tipo_destinatario
          AND ne_validada.estado_revision_notificacion IN ('CUMPLE', 'FUERA_DE_PLAZO')
      )
),
notificaciones_pendientes_priorizadas AS (
    SELECT
        base.id_notificacion_esperada,
        base.id_caso,
        base.id_calificacion_sistema_caso,
        base.id_archivo,
        base.numero_radicado,
        base.numero_radicado_normalizado,
        base.cedula,
        base.cedula_normalizada,
        base.tipo_destinatario,
        base.correo_o_guia_reportado,
        base.correo_normalizado,
        base.fecha_envio_reportada,
        base.pendiente_revision,
        base.fecha_revision_notificacion,
        base.estado_revision_notificacion
    FROM (
        SELECT
            np.*,
            ROW_NUMBER() OVER (
                PARTITION BY
                    np.numero_radicado_normalizado,
                    COALESCE(np.cedula_normalizada, ''),
                    np.tipo_destinatario
                ORDER BY
                    CASE
                        WHEN np.estado_revision_notificacion <> 'SIN_REVISION'
                            THEN 1
                        ELSE 0
                    END DESC,
                    CASE
                        WHEN np.id_caso = co.id_caso
                          OR csc_notificacion.numero_radicado_normalizado = co.numero_radicado_normalizado
                            THEN 1
                        ELSE 0
                    END DESC,
                    fecha_pestana.fecha_pestana_nombre DESC,
                    np.fecha_revision_notificacion DESC,
                    np.id_archivo DESC,
                    np.id_caso DESC,
                    np.id_notificacion_esperada DESC
            ) AS rn
        FROM notificaciones_pendientes AS np
        LEFT JOIN caso_oficial AS co
            ON co.numero_radicado_normalizado = np.numero_radicado_normalizado
        LEFT JOIN jnc.caso_calificado AS cc_notificacion
            ON cc_notificacion.id_caso = np.id_caso
        LEFT JOIN jnc.calificacion_sistema_caso AS csc_notificacion
            ON csc_notificacion.id_calificacion_sistema_caso = np.id_calificacion_sistema_caso
        OUTER APPLY (
            SELECT
                COALESCE(
                    TRY_CONVERT(
                        DATE,
                        SUBSTRING(
                            cc_notificacion.pestana_nombre,
                            NULLIF(
                                PATINDEX(
                                    '%[0-3][0-9]-[0-1][0-9]-[1-2][0-9][0-9][0-9]%',
                                    cc_notificacion.pestana_nombre
                                ),
                                0
                            ),
                            10
                        ),
                        105
                    ),
                    TRY_CONVERT(
                        DATE,
                        SUBSTRING(
                            cc_notificacion.pestana_nombre,
                            NULLIF(
                                PATINDEX(
                                    '%[0-3][0-9]/[0-1][0-9]/[1-2][0-9][0-9][0-9]%',
                                    cc_notificacion.pestana_nombre
                                ),
                                0
                            ),
                            10
                        ),
                        103
                    ),
                    TRY_CONVERT(
                        DATE,
                        SUBSTRING(
                            cc_notificacion.pestana_nombre,
                            NULLIF(
                                PATINDEX(
                                    '%[1-2][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]%',
                                    cc_notificacion.pestana_nombre
                                ),
                                0
                            ),
                            10
                        ),
                        23
                    )
                ) AS fecha_pestana_nombre
        ) AS fecha_pestana
    ) AS base
    WHERE base.rn = 1
),
entidades_pendientes_por_radicado AS (
    SELECT
        base.numero_radicado_normalizado,
        STRING_AGG(base.entidad_no_notificada, ', ')
            WITHIN GROUP (ORDER BY base.entidad_no_notificada) AS entidades_no_notificadas
    FROM (
        SELECT DISTINCT
            np.numero_radicado_normalizado,
            CASE
                WHEN np.tipo_destinatario = 'PACIENTES' THEN 'PACIENTE'
                ELSE np.tipo_destinatario
            END AS entidad_no_notificada
        FROM notificaciones_pendientes_priorizadas AS np
    ) AS base
    GROUP BY
        base.numero_radicado_normalizado
)
SELECT
    np.numero_radicado_normalizado,
    co.nombre_archivo AS nombre_archivo_mas_reciente,
    co.pestana_nombre,
    COALESCE(np.cedula_normalizada, co.cedula_normalizada) AS cedula_normalizada,
    co.nombre_paciente,
    co.eps,
    co.entidad_remitente,
    co.arl,
    co.afp,
    co.asegurado,
    np.fecha_envio_reportada,
    np.correo_normalizado,
    np.correo_o_guia_reportado AS guia_o_correo,
    epr.entidades_no_notificadas,
    CASE
        WHEN np.tipo_destinatario = 'PACIENTES' THEN 'PACIENTE'
        ELSE np.tipo_destinatario
    END AS entidad_no_notificada,
    np.estado_revision_notificacion,
    np.pendiente_revision,
    np.fecha_revision_notificacion,
    rvr.sala_acta,
    rvr.tiene_acta_audiencia,
    rvr.fecha_audiencia,
    np.id_caso AS id_caso_notificacion,
    np.id_calificacion_sistema_caso
FROM notificaciones_pendientes_priorizadas AS np
LEFT JOIN caso_oficial AS co
    ON co.numero_radicado_normalizado = np.numero_radicado_normalizado
LEFT JOIN entidades_pendientes_por_radicado AS epr
    ON epr.numero_radicado_normalizado = np.numero_radicado_normalizado
LEFT JOIN jnc.resumen_validacion_radicado AS rvr
    ON rvr.numero_radicado_normalizado = np.numero_radicado_normalizado;
GO
