/*
Tabla cacheada para el resumen de validacion por radicado.

La Function refresca esta tabla ejecutando:
EXEC jnc.refrescar_resumen_validacion_radicado;
*/

IF OBJECT_ID('jnc.resumen_validacion_radicado', 'U') IS NULL
BEGIN
    CREATE TABLE jnc.resumen_validacion_radicado (
        id_resumen_validacion BIGINT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_resumen_validacion_radicado PRIMARY KEY,
        numero_radicado NVARCHAR(100) NULL,
        numero_radicado_normalizado NVARCHAR(100) NULL,
        nombre_pestana NVARCHAR(255) NULL,
        sala NVARCHAR(255) NULL,
        fecha_audiencia DATE NULL,
        cedula NVARCHAR(50) NULL,
        nombre_paciente NVARCHAR(500) NULL,
        condicion_pacientes BIT NOT NULL,
        condicion_pacientes_extemporaneo BIT NOT NULL,
        condicion_regional BIT NOT NULL,
        condicion_regional_extemporaneo BIT NOT NULL,
        condicion_empleador BIT NOT NULL,
        condicion_empleador_extemporaneo BIT NOT NULL,
        condicion_remitente BIT NOT NULL,
        condicion_remitente_extemporaneo BIT NOT NULL,
        condicion_eps BIT NOT NULL,
        condicion_eps_extemporaneo BIT NOT NULL,
        condicion_afp BIT NOT NULL,
        condicion_afp_extemporaneo BIT NOT NULL,
        condicion_arl BIT NOT NULL,
        condicion_arl_extemporaneo BIT NOT NULL,
        condicion_aseguradoras BIT NOT NULL,
        condicion_aseguradoras_extemporaneo BIT NOT NULL,
        cumplimiento_total BIT NOT NULL,
        cumplimiento_extemporaneo BIT NOT NULL,
        no_cumplimiento_revision_manual NVARCHAR(500) NULL,
        fecha_actualizacion_resumen DATETIME2(0) NOT NULL
            CONSTRAINT DF_resumen_validacion_fecha_actualizacion DEFAULT (SYSUTCDATETIME())
    );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'UX_resumen_validacion_radicado'
      AND object_id = OBJECT_ID('jnc.resumen_validacion_radicado')
)
BEGIN
    CREATE UNIQUE INDEX UX_resumen_validacion_radicado
    ON jnc.resumen_validacion_radicado (
        numero_radicado_normalizado
    )
    WHERE numero_radicado_normalizado IS NOT NULL;
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_resumen_validacion_estado'
      AND object_id = OBJECT_ID('jnc.resumen_validacion_radicado')
)
BEGIN
    CREATE INDEX IX_resumen_validacion_estado
    ON jnc.resumen_validacion_radicado (
        cumplimiento_total,
        cumplimiento_extemporaneo,
        fecha_audiencia
    );
END;
GO

-- Carga inicial del cache si ya existen datos procesados.
EXEC jnc.refrescar_resumen_validacion_radicado;
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
    ),
    resumen_por_caso AS (
        SELECT
            cc.numero_radicado,
            cc.numero_radicado_normalizado,
            cc.pestana_nombre AS nombre_pestana,
            cc.hoja_trabajo_sala AS sala,
            cc.fecha_audiencia_resumen AS fecha_audiencia,
            MAX(ne.cedula) AS cedula,
            cc.nombre_paciente,

            CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'PACIENTES' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'PACIENTES' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS condicion_pacientes,
            MAX(CASE WHEN ne.tipo_destinatario = 'PACIENTES' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) AS condicion_pacientes_extemporaneo,

            CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'REGIONAL' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'REGIONAL' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS condicion_regional,
            MAX(CASE WHEN ne.tipo_destinatario = 'REGIONAL' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) AS condicion_regional_extemporaneo,

            CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'EMPLEADOR' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'EMPLEADOR' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS condicion_empleador,
            MAX(CASE WHEN ne.tipo_destinatario = 'EMPLEADOR' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) AS condicion_empleador_extemporaneo,

            CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'REMITENTE' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'REMITENTE' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS condicion_remitente,
            MAX(CASE WHEN ne.tipo_destinatario = 'REMITENTE' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) AS condicion_remitente_extemporaneo,

            CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'EPS' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'EPS' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS condicion_eps,
            MAX(CASE WHEN ne.tipo_destinatario = 'EPS' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) AS condicion_eps_extemporaneo,

            CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'AFP' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'AFP' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS condicion_afp,
            MAX(CASE WHEN ne.tipo_destinatario = 'AFP' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) AS condicion_afp_extemporaneo,

            CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'ARL' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'ARL' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS condicion_arl,
            MAX(CASE WHEN ne.tipo_destinatario = 'ARL' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) AS condicion_arl_extemporaneo,

            CASE WHEN COUNT(CASE WHEN ne.tipo_destinatario = 'ASEGURADORAS' THEN 1 END) = 0 THEN 1 ELSE MAX(CASE WHEN ne.tipo_destinatario = 'ASEGURADORAS' AND ne.estado_revision_notificacion = 'CUMPLE' THEN 1 ELSE 0 END) END AS condicion_aseguradoras,
            MAX(CASE WHEN ne.tipo_destinatario = 'ASEGURADORAS' AND ne.estado_revision_notificacion = 'FUERA_DE_PLAZO' THEN 1 ELSE 0 END) AS condicion_aseguradoras_extemporaneo
        FROM caso_base AS cc
        LEFT JOIN notificacion_estado AS ne
            ON ne.id_caso = cc.id_caso
        GROUP BY
            cc.id_caso,
            cc.numero_radicado,
            cc.numero_radicado_normalizado,
            cc.pestana_nombre,
            cc.hoja_trabajo_sala,
            cc.fecha_audiencia_resumen,
            cc.nombre_paciente
    ),
    resumen_por_radicado AS (
        SELECT
            MAX(numero_radicado) AS numero_radicado,
            numero_radicado_normalizado,
            MAX(nombre_pestana) AS nombre_pestana,
            MAX(sala) AS sala,
            MAX(fecha_audiencia) AS fecha_audiencia,
            MAX(cedula) AS cedula,
            MAX(nombre_paciente) AS nombre_paciente,
            CAST(MAX(condicion_pacientes) AS BIT) AS condicion_pacientes,
            CAST(MAX(condicion_pacientes_extemporaneo) AS BIT) AS condicion_pacientes_extemporaneo,
            CAST(MAX(condicion_regional) AS BIT) AS condicion_regional,
            CAST(MAX(condicion_regional_extemporaneo) AS BIT) AS condicion_regional_extemporaneo,
            CAST(MAX(condicion_empleador) AS BIT) AS condicion_empleador,
            CAST(MAX(condicion_empleador_extemporaneo) AS BIT) AS condicion_empleador_extemporaneo,
            CAST(MAX(condicion_remitente) AS BIT) AS condicion_remitente,
            CAST(MAX(condicion_remitente_extemporaneo) AS BIT) AS condicion_remitente_extemporaneo,
            CAST(MAX(condicion_eps) AS BIT) AS condicion_eps,
            CAST(MAX(condicion_eps_extemporaneo) AS BIT) AS condicion_eps_extemporaneo,
            CAST(MAX(condicion_afp) AS BIT) AS condicion_afp,
            CAST(MAX(condicion_afp_extemporaneo) AS BIT) AS condicion_afp_extemporaneo,
            CAST(MAX(condicion_arl) AS BIT) AS condicion_arl,
            CAST(MAX(condicion_arl_extemporaneo) AS BIT) AS condicion_arl_extemporaneo,
            CAST(MAX(condicion_aseguradoras) AS BIT) AS condicion_aseguradoras,
            CAST(MAX(condicion_aseguradoras_extemporaneo) AS BIT) AS condicion_aseguradoras_extemporaneo
        FROM resumen_por_caso
        GROUP BY
            numero_radicado_normalizado
    )
    INSERT INTO jnc.resumen_validacion_radicado (
        numero_radicado,
        numero_radicado_normalizado,
        nombre_pestana,
        sala,
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
    )
    SELECT
        numero_radicado,
        numero_radicado_normalizado,
        nombre_pestana,
        sala,
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
        CAST(
            CASE
                WHEN condicion_pacientes = 1
                 AND condicion_regional = 1
                 AND condicion_empleador = 1
                 AND condicion_remitente = 1
                 AND condicion_eps = 1
                 AND condicion_afp = 1
                 AND condicion_arl = 1
                 AND condicion_aseguradoras = 1
                THEN 1
                ELSE 0
            END AS BIT
        ) AS cumplimiento_total,
        CAST(
            CASE
                WHEN condicion_pacientes = 1
                 AND condicion_regional = 1
                 AND condicion_empleador = 1
                 AND condicion_remitente = 1
                 AND condicion_eps = 1
                 AND condicion_afp = 1
                 AND condicion_arl = 1
                 AND condicion_aseguradoras = 1
                THEN 0
                WHEN (condicion_pacientes = 0 AND condicion_pacientes_extemporaneo = 1)
                  OR (condicion_regional = 0 AND condicion_regional_extemporaneo = 1)
                  OR (condicion_empleador = 0 AND condicion_empleador_extemporaneo = 1)
                  OR (condicion_remitente = 0 AND condicion_remitente_extemporaneo = 1)
                  OR (condicion_eps = 0 AND condicion_eps_extemporaneo = 1)
                  OR (condicion_afp = 0 AND condicion_afp_extemporaneo = 1)
                  OR (condicion_arl = 0 AND condicion_arl_extemporaneo = 1)
                  OR (condicion_aseguradoras = 0 AND condicion_aseguradoras_extemporaneo = 1)
                THEN 1
                ELSE 0
            END AS BIT
        ) AS cumplimiento_extemporaneo,
        NULLIF(
            CONCAT_WS(
                ', ',
                CASE WHEN condicion_pacientes = 0 AND condicion_pacientes_extemporaneo = 0 THEN 'PACIENTES' END,
                CASE WHEN condicion_regional = 0 AND condicion_regional_extemporaneo = 0 THEN 'REGIONAL' END,
                CASE WHEN condicion_empleador = 0 AND condicion_empleador_extemporaneo = 0 THEN 'EMPLEADOR' END,
                CASE WHEN condicion_remitente = 0 AND condicion_remitente_extemporaneo = 0 THEN 'REMITENTE' END,
                CASE WHEN condicion_eps = 0 AND condicion_eps_extemporaneo = 0 THEN 'EPS' END,
                CASE WHEN condicion_afp = 0 AND condicion_afp_extemporaneo = 0 THEN 'AFP' END,
                CASE WHEN condicion_arl = 0 AND condicion_arl_extemporaneo = 0 THEN 'ARL' END,
                CASE WHEN condicion_aseguradoras = 0 AND condicion_aseguradoras_extemporaneo = 0 THEN 'ASEGURADORAS' END
            ),
            ''
        ) AS no_cumplimiento_revision_manual,
        SYSUTCDATETIME() AS fecha_actualizacion_resumen
    FROM resumen_por_radicado;

    COMMIT TRANSACTION;
END;
GO
