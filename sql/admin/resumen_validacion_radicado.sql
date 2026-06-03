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
