-- Schema `app`: configuración y decisiones de usuarios de ComprasAI.
--
-- Estas tablas NO son snapshot: las escriben los PUT/POST del backend
-- (remates, balanceos, sugeridos). El swap diario stg -> dbo de
-- data/load_sqlserver.py solo reemplaza tablas de `dbo`, así que aquí
-- sobreviven a cada refresco. Se exponen en `dbo` con sinónimos para que el
-- SQL de los routers no cambie.
--
-- Idempotente: lo ejecuta core/sqlserver.ensure_app_schema en cada arranque.
-- Las semillas (escalas, rutas GAM, plazas, meses objetivo) las inserta el
-- propio backend cuando la tabla está vacía, igual que en SQLite.

IF SCHEMA_ID('app') IS NULL EXEC('CREATE SCHEMA [app]')
GO

IF OBJECT_ID('app.remate_escalas') IS NULL
CREATE TABLE app.remate_escalas (
  id INT IDENTITY PRIMARY KEY,
  cajas_min INT NOT NULL,
  cajas_max INT NOT NULL,
  precio_caja FLOAT NOT NULL,
  traslada INT NOT NULL DEFAULT 0)
GO

IF OBJECT_ID('app.remate_rutas_gam') IS NULL
CREATE TABLE app.remate_rutas_gam (
  corredor NVARCHAR(200) PRIMARY KEY,
  cedis NVARCHAR(200) NOT NULL,
  sucursal_remate NVARCHAR(200) NOT NULL)
GO

IF OBJECT_ID('app.remate_plazas_excepcion') IS NULL
CREATE TABLE app.remate_plazas_excepcion (
  nombre NVARCHAR(200) PRIMARY KEY)
GO

IF OBJECT_ID('app.balanceo_costo_corredor') IS NULL
CREATE TABLE app.balanceo_costo_corredor (
  corredor NVARCHAR(200) PRIMARY KEY,
  costo_caja_traslado FLOAT NOT NULL)
GO

IF OBJECT_ID('app.balanceo_umbral_dias_pedido') IS NULL
CREATE TABLE app.balanceo_umbral_dias_pedido (
  categoria NVARCHAR(100) PRIMARY KEY,
  umbral_dias INT NOT NULL)
GO

IF OBJECT_ID('app.balanceo_descarte') IS NULL
CREATE TABLE app.balanceo_descarte (
  material_id NVARCHAR(100) NOT NULL,
  plant NVARCHAR(100) NOT NULL,
  hasta_fecha NVARCHAR(40) NOT NULL,
  motivo NVARCHAR(MAX) NULL,
  creado NVARCHAR(40) NOT NULL,
  PRIMARY KEY (material_id, plant))
GO

IF OBJECT_ID('app.balanceo_prioridad_default') IS NULL
CREATE TABLE app.balanceo_prioridad_default (
  material_id NVARCHAR(100) PRIMARY KEY,
  prioridad FLOAT NOT NULL)
GO

IF OBJECT_ID('app.balanceo_prioridad_excepcion') IS NULL
CREATE TABLE app.balanceo_prioridad_excepcion (
  material_id NVARCHAR(100) NOT NULL,
  plant NVARCHAR(100) NOT NULL,
  prioridad FLOAT NOT NULL,
  PRIMARY KEY (material_id, plant))
GO

IF OBJECT_ID('app.balanceo_pendiente') IS NULL
CREATE TABLE app.balanceo_pendiente (
  id INT IDENTITY PRIMARY KEY,
  material_id NVARCHAR(100) NOT NULL,
  origen_plant NVARCHAR(100) NOT NULL,
  destino_plant NVARCHAR(100) NOT NULL,
  cajas FLOAT NOT NULL,
  estado NVARCHAR(20) NOT NULL DEFAULT 'pendiente',
  traslado_ref NVARCHAR(100) NULL,
  creado NVARCHAR(40) NOT NULL,
  posteado_en NVARCHAR(40) NULL,
  entregado_en NVARCHAR(40) NULL)
GO

IF OBJECT_ID('app.sugeridos_generados') IS NULL
CREATE TABLE app.sugeridos_generados (
  id NVARCHAR(200) PRIMARY KEY,
  material_id NVARCHAR(100) NOT NULL,
  plant NVARCHAR(100) NOT NULL,
  descripcion NVARCHAR(MAX) NULL,
  abc NVARCHAR(10) NULL,
  cobertura_actual FLOAT NULL,
  cobertura_objetivo FLOAT NULL,
  cantidad_sugerida FLOAT NULL,
  cantidad_transferir FLOAT NULL,
  cantidad_comprar FLOAT NULL,
  cantidad_final FLOAT NULL,
  costo_unitario FLOAT NULL,
  costo_estimado FLOAT NULL,
  confianza INT NULL,
  tendencia NVARCHAR(50) NULL,
  capa NVARCHAR(50) NULL,
  explicacion NVARCHAR(MAX) NULL,
  factores_json NVARCHAR(MAX) NULL,
  datos_decision_json NVARCHAR(MAX) NULL,
  estado NVARCHAR(20) NOT NULL DEFAULT 'propuesto',
  justificacion_edicion NVARCHAR(MAX) NULL,
  aprobado_por NVARCHAR(200) NULL,
  creado NVARCHAR(40) NOT NULL,
  actualizado NVARCHAR(40) NOT NULL)
GO

IF OBJECT_ID('app.meses_objetivo_default') IS NULL
CREATE TABLE app.meses_objetivo_default (
  material_id NVARCHAR(100) PRIMARY KEY,
  meses FLOAT NOT NULL)
GO

IF OBJECT_ID('app.meses_objetivo_excepcion') IS NULL
CREATE TABLE app.meses_objetivo_excepcion (
  material_id NVARCHAR(100) NOT NULL,
  plant NVARCHAR(100) NOT NULL,
  meses FLOAT NOT NULL,
  PRIMARY KEY (material_id, plant))
GO

-- Sinónimos dbo.X -> app.X (el SQL de los routers usa nombres sin schema).
DECLARE @t SYSNAME, @s NVARCHAR(400)
DECLARE c CURSOR LOCAL FAST_FORWARD FOR
  SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID('app')
OPEN c
FETCH NEXT FROM c INTO @t
WHILE @@FETCH_STATUS = 0
BEGIN
  IF OBJECT_ID('dbo.' + QUOTENAME(@t)) IS NULL
  BEGIN
    SET @s = N'CREATE SYNONYM dbo.' + QUOTENAME(@t) + N' FOR app.' + QUOTENAME(@t)
    EXEC(@s)
  END
  FETCH NEXT FROM c INTO @t
END
CLOSE c
DEALLOCATE c
GO
