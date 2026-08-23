-- ComprasAI Sanimex - Esquema SQLite del contrato de datos
-- Este esquema es el CONTRATO oficial entre el generador sintético (T3) y los
-- datos reales de SAP (T1). Cuando T1 entregue el .db real, se sustituye el
-- archivo sin tocar código de la API ni de los motores.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS materiales (
    material_id     TEXT PRIMARY KEY,
    descripcion     TEXT NOT NULL,
    familia         TEXT NOT NULL,
    formato         TEXT,
    m2_por_caja     REAL,
    abc             TEXT CHECK (abc IN ('A', 'B', 'C')),
    precio_venta    REAL NOT NULL DEFAULT 0,
    costo           REAL NOT NULL DEFAULT 0,
    economico       INTEGER NOT NULL DEFAULT 0 CHECK (economico IN (0, 1))
);

CREATE TABLE IF NOT EXISTS sucursales (
    plant           TEXT PRIMARY KEY,
    nombre          TEXT NOT NULL,
    organizacion    TEXT NOT NULL CHECK (organizacion IN ('GAM', 'GSA', 'SA', 'GAMN')),
    canal           TEXT NOT NULL CHECK (canal IN ('Menudeo', 'Mayoreo', 'eCommerce', 'Outlet', 'Remates')),
    corredor        TEXT,
    es_cedis        INTEGER NOT NULL DEFAULT 0 CHECK (es_cedis IN (0, 1))
);

CREATE TABLE IF NOT EXISTS ventas_mensuales (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id     TEXT NOT NULL REFERENCES materiales(material_id),
    plant           TEXT NOT NULL REFERENCES sucursales(plant),
    canal           TEXT NOT NULL,
    anio_mes        TEXT NOT NULL,  -- 'YYYY-MM'
    cantidad_m2     REAL NOT NULL DEFAULT 0,
    importe         REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ventas_material ON ventas_mensuales(material_id);
CREATE INDEX IF NOT EXISTS idx_ventas_plant ON ventas_mensuales(plant);
CREATE INDEX IF NOT EXISTS idx_ventas_aniomes ON ventas_mensuales(anio_mes);
CREATE INDEX IF NOT EXISTS idx_ventas_mat_plant ON ventas_mensuales(material_id, plant);

CREATE TABLE IF NOT EXISTS inventarios (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id         TEXT NOT NULL REFERENCES materiales(material_id),
    plant               TEXT NOT NULL REFERENCES sucursales(plant),
    disponible          REAL NOT NULL DEFAULT 0,
    transito            REAL NOT NULL DEFAULT 0,
    comprometido        REAL NOT NULL DEFAULT 0,
    pedidos_abiertos    REAL NOT NULL DEFAULT 0,
    cajas_remanentes    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(material_id, plant)
);

CREATE INDEX IF NOT EXISTS idx_inv_material ON inventarios(material_id);
CREATE INDEX IF NOT EXISTS idx_inv_plant ON inventarios(plant);

CREATE TABLE IF NOT EXISTS coberturas_objetivo (
    material_id     TEXT PRIMARY KEY REFERENCES materiales(material_id),
    meses_objetivo  REAL NOT NULL DEFAULT 2.0
);

CREATE TABLE IF NOT EXISTS proveedores (
    material_id     TEXT PRIMARY KEY REFERENCES materiales(material_id),
    proveedor       TEXT NOT NULL,
    lead_time_dias  INTEGER NOT NULL DEFAULT 15,
    moq_cajas       INTEGER NOT NULL DEFAULT 20,
    cajas_por_pallet INTEGER NOT NULL DEFAULT 40
);
