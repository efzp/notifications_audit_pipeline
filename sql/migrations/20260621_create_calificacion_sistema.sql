/*
Tablas tidy para el export de calificaciones del sistema.

No se persiste la fila raw en JSON porque el archivo contiene datos sensibles
fuera del contrato de auditoria. La trazabilidad se conserva con id_archivo,
numero_fila_excel, version de esquema y hashes de los campos cargados.
*/

IF OBJECT_ID('jnc.calificacion_sistema_envio_entidad', 'U') IS NULL
BEGIN
    CREATE TABLE jnc.calificacion_sistema_envio_entidad (
        id_calificacion_sistema_envio BIGINT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_calificacion_sistema_envio_entidad PRIMARY KEY,
        id_calificacion_sistema_caso BIGINT NULL,
        id_archivo INT NOT NULL,
        numero_fila_excel INT NULL,
        numero_radicado_normalizado NVARCHAR(100) NULL,
        cedula_normalizada NVARCHAR(50) NULL,
        tipo_entidad NVARCHAR(100) NOT NULL,
        nombre_entidad NVARCHAR(500) NULL,
        nombre_entidad_normalizado NVARCHAR(500) NULL,
        correo_reportado NVARCHAR(1000) NULL,
        correo_normalizado NVARCHAR(1000) NULL,
        numero_notificacion_reportado NVARCHAR(100) NULL,
        fecha_notificacion_reportada DATE NULL,
        fuente_dato NVARCHAR(100) NOT NULL,
        hash_calificacion_sistema_envio NVARCHAR(64) NULL,
        activo BIT NOT NULL
            CONSTRAINT DF_calificacion_sistema_envio_activo DEFAULT (1),
        fecha_creacion DATETIME2(0) NOT NULL
            CONSTRAINT DF_calificacion_sistema_envio_fecha_creacion DEFAULT (SYSUTCDATETIME()),
        fecha_actualizacion DATETIME2(0) NULL
    );
END;
GO

IF OBJECT_ID('jnc.calificacion_sistema_caso', 'U') IS NULL
BEGIN
    CREATE TABLE jnc.calificacion_sistema_caso (
        id_calificacion_sistema_caso BIGINT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_calificacion_sistema_caso PRIMARY KEY,
        id_archivo INT NOT NULL,
        numero_fila_excel INT NULL,
        hoja_origen NVARCHAR(255) NULL,
        schema_version INT NOT NULL
            CONSTRAINT DF_calificacion_sistema_caso_schema_version DEFAULT (1),
        sala NVARCHAR(255) NULL,
        fecha_audiencia DATE NULL,
        numero_dictamen NVARCHAR(100) NULL,
        numero_dictamen_normalizado NVARCHAR(100) NULL,
        numero_radicado NVARCHAR(100) NULL,
        numero_radicado_normalizado NVARCHAR(100) NULL,
        fecha_radicado DATE NULL,
        entidad_remitente NVARCHAR(500) NULL,
        entidad_remitente_normalizado NVARCHAR(500) NULL,
        regional NVARCHAR(500) NULL,
        regional_normalizado NVARCHAR(500) NULL,
        tipo_identificacion NVARCHAR(50) NULL,
        cedula NVARCHAR(50) NULL,
        cedula_normalizada NVARCHAR(50) NULL,
        nombre_paciente NVARCHAR(500) NULL,
        nombre_paciente_normalizado NVARCHAR(500) NULL,
        arl NVARCHAR(300) NULL,
        arl_normalizado NVARCHAR(500) NULL,
        eps NVARCHAR(300) NULL,
        eps_normalizado NVARCHAR(500) NULL,
        afp NVARCHAR(300) NULL,
        afp_normalizado NVARCHAR(500) NULL,
        compania_seguros NVARCHAR(300) NULL,
        compania_seguros_normalizado NVARCHAR(500) NULL,
        empresa_contratante NVARCHAR(500) NULL,
        medico_ponente NVARCHAR(255) NULL,
        medico_ponente_normalizado NVARCHAR(500) NULL,
        terapeuta_psicologa NVARCHAR(255) NULL,
        terapeuta_psicologa_normalizado NVARCHAR(500) NULL,
        medico_principal NVARCHAR(255) NULL,
        medico_principal_normalizado NVARCHAR(500) NULL,
        numero_acta_audiencia NVARCHAR(100) NULL,
        fecha_ejecutoria DATE NULL,
        estado_solicitud NVARCHAR(255) NULL,
        fecha_reactivacion DATE NULL,
        hash_calificacion_sistema_caso NVARCHAR(64) NULL,
        activo BIT NOT NULL
            CONSTRAINT DF_calificacion_sistema_caso_activo DEFAULT (1),
        fecha_creacion DATETIME2(0) NOT NULL
            CONSTRAINT DF_calificacion_sistema_caso_fecha_creacion DEFAULT (SYSUTCDATETIME()),
        fecha_actualizacion DATETIME2(0) NULL
    );
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.foreign_keys
    WHERE name = 'FK_calificacion_sistema_envio_caso'
)
BEGIN
    ALTER TABLE jnc.calificacion_sistema_envio_entidad
    ADD CONSTRAINT FK_calificacion_sistema_envio_caso
        FOREIGN KEY (id_calificacion_sistema_caso)
        REFERENCES jnc.calificacion_sistema_caso (id_calificacion_sistema_caso);
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_calificacion_sistema_caso_radicado'
      AND object_id = OBJECT_ID('jnc.calificacion_sistema_caso')
)
BEGIN
    CREATE INDEX IX_calificacion_sistema_caso_radicado
    ON jnc.calificacion_sistema_caso (
        numero_radicado_normalizado,
        cedula_normalizada,
        activo
    )
    INCLUDE (
        fecha_audiencia,
        numero_dictamen,
        entidad_remitente,
        regional,
        estado_solicitud
    );
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'UX_calificacion_sistema_caso_archivo_hash'
      AND object_id = OBJECT_ID('jnc.calificacion_sistema_caso')
)
BEGIN
    CREATE UNIQUE INDEX UX_calificacion_sistema_caso_archivo_hash
    ON jnc.calificacion_sistema_caso (
        id_archivo,
        hash_calificacion_sistema_caso
    )
    WHERE hash_calificacion_sistema_caso IS NOT NULL;
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_calificacion_sistema_envio_busqueda'
      AND object_id = OBJECT_ID('jnc.calificacion_sistema_envio_entidad')
)
BEGIN
    CREATE INDEX IX_calificacion_sistema_envio_busqueda
    ON jnc.calificacion_sistema_envio_entidad (
        tipo_entidad,
        correo_normalizado,
        numero_radicado_normalizado,
        activo
    )
    INCLUDE (
        id_calificacion_sistema_caso,
        cedula_normalizada,
        fecha_notificacion_reportada
    );
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'UX_calificacion_sistema_envio_archivo_hash'
      AND object_id = OBJECT_ID('jnc.calificacion_sistema_envio_entidad')
)
BEGIN
    CREATE UNIQUE INDEX UX_calificacion_sistema_envio_archivo_hash
    ON jnc.calificacion_sistema_envio_entidad (
        id_archivo,
        hash_calificacion_sistema_envio
    )
    WHERE hash_calificacion_sistema_envio IS NOT NULL;
END;
GO

CREATE OR ALTER VIEW jnc.vw_calificacion_sistema_actual
AS
SELECT
    caso.id_calificacion_sistema_caso,
    caso.id_archivo,
    caso.numero_fila_excel,
    caso.numero_radicado,
    caso.numero_radicado_normalizado,
    caso.numero_dictamen,
    caso.fecha_audiencia,
    caso.entidad_remitente,
    caso.regional,
    caso.tipo_identificacion,
    caso.cedula,
    caso.cedula_normalizada,
    caso.nombre_paciente,
    caso.sala,
    caso.arl,
    caso.eps,
    caso.afp,
    caso.compania_seguros,
    caso.empresa_contratante,
    caso.medico_ponente,
    caso.terapeuta_psicologa,
    caso.medico_principal,
    caso.numero_acta_audiencia,
    caso.fecha_ejecutoria,
    caso.estado_solicitud,
    caso.fecha_reactivacion,
    caso.hash_calificacion_sistema_caso
FROM jnc.calificacion_sistema_caso AS caso
WHERE caso.activo = 1;
GO

CREATE OR ALTER VIEW jnc.vw_calificacion_sistema_envio_entidad_actual
AS
SELECT
    envio.id_calificacion_sistema_envio,
    envio.id_calificacion_sistema_caso,
    envio.id_archivo,
    envio.numero_fila_excel,
    envio.numero_radicado_normalizado,
    envio.cedula_normalizada,
    envio.tipo_entidad,
    envio.nombre_entidad,
    envio.correo_reportado,
    envio.correo_normalizado,
    envio.numero_notificacion_reportado,
    envio.fecha_notificacion_reportada,
    envio.fuente_dato,
    envio.hash_calificacion_sistema_envio
FROM jnc.calificacion_sistema_envio_entidad AS envio
WHERE envio.activo = 1;
GO
