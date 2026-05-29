/*
Detalle directo de radicados que no cumplen.

Incluye registros que fallan por:
- FUERA_DE_PLAZO: el envio certificado no esta dentro de los 2 dias calendario.
- CAMPO_SIN_ENVIO_VALIDO: el campo original no tiene ningun correo en CUMPLE.
- TEXTO_NO_VALIDO: asunto o evento no coinciden con los textos aceptados.

Para validar todos los casos, cambiar @cedula_a_validar a NULL.
*/

DECLARE @cedula_a_validar NVARCHAR(100) = NULL;

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
campo_estado AS (
    SELECT
        numero_radicado,
        cedula,
        campo_original,
        MAX(CASE WHEN estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END)
            AS campo_tiene_envio_valido
    FROM base
    GROUP BY
        numero_radicado,
        cedula,
        campo_original
),
incumplimientos AS (
    SELECT
        b.*,
        ce.campo_tiene_envio_valido,
        CASE
            WHEN b.estado_revision_notificacion = 'FUERA_DE_PLAZO'
                THEN 'FUERA_DE_PLAZO'
            WHEN b.estado_revision_notificacion IN ('ASUNTO_NO_VALIDO', 'EVENTO_NO_VALIDO')
                THEN 'TEXTO_NO_VALIDO'
            WHEN ce.campo_tiene_envio_valido = 0
                THEN 'CAMPO_SIN_ENVIO_VALIDO'
        END AS tipo_incumplimiento
    FROM base AS b
    INNER JOIN campo_estado AS ce
        ON ce.numero_radicado = b.numero_radicado
        AND ce.cedula = b.cedula
        AND ce.campo_original = b.campo_original
    WHERE
        b.estado_revision_notificacion = 'FUERA_DE_PLAZO'
        OR b.estado_revision_notificacion IN ('ASUNTO_NO_VALIDO', 'EVENTO_NO_VALIDO')
        OR ce.campo_tiene_envio_valido = 0
)
SELECT
    numero_radicado,
    cedula,
    campo_original,
    tipo_incumplimiento,
    estado_revision_notificacion,
    pendiente_revision AS descripcion_error,
    correo_o_guia_reportado,
    correo_esperado_match,
    correo_certificado_match,
    hoja_trabajo_fecha_audiencia,
    fecha_envio_certificado_match,
    dias_despues_audiencia,
    nombre_archivo,
    hoja_excel,
    hoja_trabajo_sala,
    id_notificacion_esperada,
    id_notificacion_correo_certificado_match,
    id_archivo_correo_certificado_match,
    numero_linea_csv_match,
    score_asunto,
    score_evento,
    asunto_tipo_match,
    evento_tipo_match,
    fecha_revision_notificacion
FROM incumplimientos
ORDER BY
    numero_radicado,
    cedula,
    campo_original,
    CASE tipo_incumplimiento
        WHEN 'CAMPO_SIN_ENVIO_VALIDO' THEN 1
        WHEN 'FUERA_DE_PLAZO' THEN 2
        WHEN 'TEXTO_NO_VALIDO' THEN 3
        ELSE 4
    END,
    estado_revision_notificacion,
    correo_o_guia_reportado;
