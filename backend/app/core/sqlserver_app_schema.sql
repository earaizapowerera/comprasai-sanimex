-- Schema `app`: configuración y decisiones de usuarios de ComprasAI.
--
-- Estas tablas NO son snapshot: las escriben los PUT/POST del backend
-- (remates, balanceos, sugeridos). El swap diario stg -> dbo de
-- data/load_sqlserver.py solo reemplaza tablas de `dbo`, así que aquí
-- sobreviven a cada refresco. Se exponen en `dbo` con sinónimos para que el
-- SQL de los routers no cambie.
--
-- Todo texto usa COLLATE Latin1_General_100_BIN2, igual que el snapshot de
-- dbo (data/load_sqlserver.py TEXT_COLLATION): semántica de SQLite y sin
-- conflictos de colación en los JOIN app <-> dbo.
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
  corredor NVARCHAR(200) COLLATE Latin1_General_100_BIN2 PRIMARY KEY,
  cedis NVARCHAR(200) COLLATE Latin1_General_100_BIN2 NOT NULL,
  sucursal_remate NVARCHAR(200) COLLATE Latin1_General_100_BIN2 NOT NULL)
GO

IF OBJECT_ID('app.remate_plazas_excepcion') IS NULL
CREATE TABLE app.remate_plazas_excepcion (
  nombre NVARCHAR(200) COLLATE Latin1_General_100_BIN2 PRIMARY KEY)
GO

IF OBJECT_ID('app.balanceo_costo_corredor') IS NULL
CREATE TABLE app.balanceo_costo_corredor (
  corredor NVARCHAR(200) COLLATE Latin1_General_100_BIN2 PRIMARY KEY,
  costo_caja_traslado FLOAT NOT NULL)
GO

IF OBJECT_ID('app.balanceo_umbral_dias_pedido') IS NULL
CREATE TABLE app.balanceo_umbral_dias_pedido (
  categoria NVARCHAR(100) COLLATE Latin1_General_100_BIN2 PRIMARY KEY,
  umbral_dias INT NOT NULL)
GO

IF OBJECT_ID('app.balanceo_descarte') IS NULL
CREATE TABLE app.balanceo_descarte (
  material_id NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
  plant NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
  hasta_fecha NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL,
  motivo NVARCHAR(MAX) COLLATE Latin1_General_100_BIN2 NULL,
  creado NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL,
  PRIMARY KEY (material_id, plant))
GO

IF OBJECT_ID('app.balanceo_prioridad_default') IS NULL
CREATE TABLE app.balanceo_prioridad_default (
  material_id NVARCHAR(100) COLLATE Latin1_General_100_BIN2 PRIMARY KEY,
  prioridad FLOAT NOT NULL)
GO

IF OBJECT_ID('app.balanceo_prioridad_excepcion') IS NULL
CREATE TABLE app.balanceo_prioridad_excepcion (
  material_id NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
  plant NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
  prioridad FLOAT NOT NULL,
  PRIMARY KEY (material_id, plant))
GO

IF OBJECT_ID('app.balanceo_pendiente') IS NULL
CREATE TABLE app.balanceo_pendiente (
  id INT IDENTITY PRIMARY KEY,
  material_id NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
  origen_plant NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
  destino_plant NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
  cajas FLOAT NOT NULL,
  estado NVARCHAR(20) COLLATE Latin1_General_100_BIN2 NOT NULL DEFAULT 'pendiente',
  traslado_ref NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NULL,
  creado NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL,
  posteado_en NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NULL,
  entregado_en NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NULL)
GO

IF OBJECT_ID('app.sugeridos_generados') IS NULL
CREATE TABLE app.sugeridos_generados (
  id NVARCHAR(200) COLLATE Latin1_General_100_BIN2 PRIMARY KEY,
  material_id NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
  plant NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
  descripcion NVARCHAR(MAX) COLLATE Latin1_General_100_BIN2 NULL,
  abc NVARCHAR(10) COLLATE Latin1_General_100_BIN2 NULL,
  cobertura_actual FLOAT NULL,
  cobertura_objetivo FLOAT NULL,
  cantidad_sugerida FLOAT NULL,
  cantidad_transferir FLOAT NULL,
  cantidad_comprar FLOAT NULL,
  cantidad_final FLOAT NULL,
  costo_unitario FLOAT NULL,
  costo_estimado FLOAT NULL,
  confianza INT NULL,
  tendencia NVARCHAR(50) COLLATE Latin1_General_100_BIN2 NULL,
  capa NVARCHAR(50) COLLATE Latin1_General_100_BIN2 NULL,
  explicacion NVARCHAR(MAX) COLLATE Latin1_General_100_BIN2 NULL,
  factores_json NVARCHAR(MAX) COLLATE Latin1_General_100_BIN2 NULL,
  datos_decision_json NVARCHAR(MAX) COLLATE Latin1_General_100_BIN2 NULL,
  estado NVARCHAR(20) COLLATE Latin1_General_100_BIN2 NOT NULL DEFAULT 'propuesto',
  justificacion_edicion NVARCHAR(MAX) COLLATE Latin1_General_100_BIN2 NULL,
  aprobado_por NVARCHAR(200) COLLATE Latin1_General_100_BIN2 NULL,
  creado NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL,
  actualizado NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL)
GO

IF OBJECT_ID('app.meses_objetivo_default') IS NULL
CREATE TABLE app.meses_objetivo_default (
  material_id NVARCHAR(100) COLLATE Latin1_General_100_BIN2 PRIMARY KEY,
  meses FLOAT NOT NULL)
GO

IF OBJECT_ID('app.meses_objetivo_excepcion') IS NULL
CREATE TABLE app.meses_objetivo_excepcion (
  material_id NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
  plant NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
  meses FLOAT NOT NULL,
  PRIMARY KEY (material_id, plant))
GO

IF OBJECT_ID('app.lotes_compra') IS NULL
CREATE TABLE app.lotes_compra (
  id INT IDENTITY PRIMARY KEY,
  nombre NVARCHAR(400) COLLATE Latin1_General_100_BIN2 NOT NULL,
  fecha_inicio NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL,
  fecha_fin NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL,
  activo INT NOT NULL DEFAULT 1,
  creado_por NVARCHAR(200) COLLATE Latin1_General_100_BIN2 NULL,
  creado_en NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL,
  actualizado_en NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL,
  CHECK (fecha_fin >= fecha_inicio))
GO

IF OBJECT_ID('app.lotes_compra_clasificacion') IS NULL
CREATE TABLE app.lotes_compra_clasificacion (
  lote_id INT NOT NULL REFERENCES app.lotes_compra(id) ON DELETE CASCADE,
  clasificacion NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
  PRIMARY KEY (lote_id, clasificacion))
GO

IF OBJECT_ID('app.sucursal_compra_evidencia') IS NULL
CREATE TABLE app.sucursal_compra_evidencia (
  plant NVARCHAR(100) COLLATE Latin1_General_100_BIN2 PRIMARY KEY,
  oc_ext_12m INT NOT NULL DEFAULT 0,
  lineas_12m INT NOT NULL DEFAULT 0,
  proveedores_12m INT NOT NULL DEFAULT 0,
  ult_oc_ext NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NULL,
  oc_ext_24m INT NOT NULL DEFAULT 0,
  traslados_12m INT NOT NULL DEFAULT 0,
  ventana_desde NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NULL,
  ventana_hasta NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NULL,
  extraido NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NULL)
GO

IF OBJECT_ID('app.sucursal_compra_override') IS NULL
CREATE TABLE app.sucursal_compra_override (
  plant NVARCHAR(100) COLLATE Latin1_General_100_BIN2 PRIMARY KEY,
  clase NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL,
  motivo NVARCHAR(MAX) COLLATE Latin1_General_100_BIN2 NULL,
  usuario NVARCHAR(200) COLLATE Latin1_General_100_BIN2 NULL,
  actualizado NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL)
GO

IF OBJECT_ID('app.sucursal_compra_config') IS NULL
CREATE TABLE app.sucursal_compra_config (
  clave NVARCHAR(100) COLLATE Latin1_General_100_BIN2 PRIMARY KEY,
  valor NVARCHAR(400) COLLATE Latin1_General_100_BIN2 NOT NULL)
GO

-- Catálogo derivado: lo reescribe sucursal_compra.recalcular (columnas en el
-- mismo orden que el DDL SQLite: el INSERT es posicional).
IF OBJECT_ID('app.sucursal_compra') IS NULL
CREATE TABLE app.sucursal_compra (
  plant NVARCHAR(100) COLLATE Latin1_General_100_BIN2 PRIMARY KEY,
  clase NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL,
  clase_calculada NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL,
  fuente NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL,
  oc_ext_12m INT NULL,
  traslados_12m INT NULL,
  ult_oc_ext NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NULL,
  skus_con_inventario INT NULL,
  umbral_oc_anual INT NOT NULL,
  generado NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL)
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
