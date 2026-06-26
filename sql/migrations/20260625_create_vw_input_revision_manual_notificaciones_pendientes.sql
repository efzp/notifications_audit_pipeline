/*
Vista base para llenar el template de revision manual de notificaciones.

Granularidad: una fila por notificacion esperada pendiente de cruce.
Los unicos campos que debe llenar el auditor en Excel son:
- cumplimiento
- cumplimiento_extemporaneo
- observaciones
- revisado_por
*/

CREATE OR ALTER VIEW jnc.vw_input_revision_manual_notificaciones_pendientes
AS
WITH base_revision_manual AS (
SELECT
    ne.id_notificacion_esperada,
    archivo_ne.nombre_archivo AS nombre_archivo_notificacion_esperada,
    ne.numero_radicado_normalizado,
    ne.cedula_normalizada,
    csc.sala,
    COALESCE(csc.fecha_audiencia, ne.hoja_trabajo_fecha_audiencia)
        AS fecha_audiencia,
    ne.tipo_destinatario,
    entidad.nombre_entidad,
    COALESCE(envio.correo_reportado, ne.correo_o_guia_reportado)
        AS correo_o_guia_entidad,
    COALESCE(envio.correo_normalizado, ne.correo_normalizado)
        AS correo_normalizado_entidad,
    CAST(NULL AS DATETIME2(0)) AS fecha_revision,
    ne.correo_o_guia_reportado,
    ne.fecha_envio_reportada,
    ne.fecha_recibido_reportada,
    ne.pestana_nombre,
    caso.comentarios_excel,
    CAST(NULL AS BIT) AS cumplimiento,
    CAST(NULL AS BIT) AS cumplimiento_extemporaneo,
    CAST(NULL AS NVARCHAR(MAX)) AS observaciones,
    CAST(NULL AS NVARCHAR(255)) AS revisado_por,
    ROW_NUMBER() OVER (
        PARTITION BY
            ne.numero_radicado_normalizado,
            ne.cedula_normalizada,
            UPPER(COALESCE(ne.tipo_destinatario, '')),
            UPPER(LTRIM(RTRIM(COALESCE(entidad.nombre_entidad, ''))))
        ORDER BY
            ne.fecha_creacion DESC,
            ne.fecha_actualizacion DESC,
            ne.id_notificacion_esperada DESC
    ) AS rn_ultima_entidad
FROM jnc.notificacion_esperada AS ne
INNER JOIN jnc.cruce_notificacion_pendiente AS cnp
    ON cnp.id_notificacion_esperada = ne.id_notificacion_esperada
   AND cnp.activo = 1
INNER JOIN jnc.resumen_validacion_radicado AS rvr
    ON rvr.numero_radicado_normalizado = ne.numero_radicado_normalizado
LEFT JOIN jnc.etl_archivo_cargado AS archivo_ne
    ON archivo_ne.id_archivo = ne.id_archivo
LEFT JOIN jnc.calificacion_sistema_caso AS csc
    ON csc.id_calificacion_sistema_caso = ne.id_calificacion_sistema_caso
   AND csc.activo = 1
OUTER APPLY (
    SELECT TOP (1)
        rcn_inner.estado_revision_notificacion,
        rcn_inner.descripcion_revision,
        rcn_inner.fecha_revision,
        rcn_inner.id_resultado_cruce
    FROM jnc.resultado_cruce_notificacion AS rcn_inner
    WHERE rcn_inner.id_notificacion_esperada = ne.id_notificacion_esperada
      AND rcn_inner.activo = 1
    ORDER BY
        rcn_inner.fecha_revision DESC,
        rcn_inner.id_resultado_cruce DESC
) AS rcn
OUTER APPLY (
    SELECT TOP (1)
        envio_inner.nombre_entidad,
        envio_inner.correo_reportado,
        envio_inner.correo_normalizado
    FROM jnc.calificacion_sistema_envio_entidad AS envio_inner
    WHERE envio_inner.activo = 1
      AND envio_inner.id_calificacion_sistema_caso = ne.id_calificacion_sistema_caso
      AND envio_inner.tipo_entidad = CASE UPPER(COALESCE(ne.tipo_destinatario, ''))
            WHEN 'PACIENTES' THEN 'PACIENTE'
            WHEN 'ASEGURADORAS' THEN 'ASEGURADORAS'
            ELSE UPPER(COALESCE(ne.tipo_destinatario, ''))
          END
    ORDER BY
        envio_inner.fecha_actualizacion DESC,
        envio_inner.fecha_creacion DESC,
        envio_inner.id_calificacion_sistema_envio DESC
) AS envio
CROSS APPLY (
    SELECT
        CASE UPPER(COALESCE(ne.tipo_destinatario, ''))
            WHEN 'PACIENTES' THEN COALESCE(envio.nombre_entidad, csc.nombre_paciente)
            WHEN 'REMITENTE' THEN COALESCE(envio.nombre_entidad, csc.entidad_remitente)
            WHEN 'EPS' THEN COALESCE(envio.nombre_entidad, csc.eps)
            WHEN 'ARL' THEN COALESCE(envio.nombre_entidad, csc.arl)
            WHEN 'AFP' THEN COALESCE(envio.nombre_entidad, csc.afp)
            WHEN 'ASEGURADORAS' THEN COALESCE(envio.nombre_entidad, csc.compania_seguros)
            WHEN 'EMPLEADOR' THEN COALESCE(envio.nombre_entidad, csc.empresa_contratante)
            WHEN 'REGIONAL' THEN COALESCE(envio.nombre_entidad, csc.regional)
            ELSE envio.nombre_entidad
        END AS nombre_entidad
) AS entidad
OUTER APPLY (
    SELECT TOP (1)
        cc.comentarios_excel
    FROM jnc.caso_calificado AS cc
    WHERE cc.activo = 1
      AND (
            cc.id_caso = ne.id_caso
            OR (
                ne.id_caso IS NULL
                AND cc.numero_radicado_normalizado = ne.numero_radicado_normalizado
            )
          )
    ORDER BY
        CASE WHEN cc.id_caso = ne.id_caso THEN 0 ELSE 1 END,
        cc.id_archivo DESC,
        cc.id_caso DESC
) AS caso
WHERE ne.activo = 1
  AND rvr.cumplimiento_total = 0
  AND rvr.cumplimiento_extemporaneo = 0
  AND COALESCE(
        rcn.estado_revision_notificacion,
        ne.estado_revision_notificacion,
        cnp.estado_revision_notificacion,
        'SIN_REVISION'
      ) NOT IN ('CUMPLE', 'FUERA_DE_PLAZO')
)
SELECT
    id_notificacion_esperada,
    nombre_archivo_notificacion_esperada,
    numero_radicado_normalizado,
    cedula_normalizada,
    sala,
    fecha_audiencia,
    tipo_destinatario,
    nombre_entidad,
    correo_o_guia_entidad,
    correo_normalizado_entidad,
    fecha_revision,
    correo_o_guia_reportado,
    fecha_envio_reportada,
    fecha_recibido_reportada,
    pestana_nombre,
    comentarios_excel,
    cumplimiento,
    cumplimiento_extemporaneo,
    observaciones,
    revisado_por
FROM base_revision_manual
WHERE rn_ultima_entidad = 1
ORDER BY
    numero_radicado_normalizado,
    cedula_normalizada,
    tipo_destinatario,
    id_notificacion_esperada
OFFSET 0 ROWS;
GO
