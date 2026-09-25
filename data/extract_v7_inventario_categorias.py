#!/usr/bin/env python3
"""
extract_v7_inventario_categorias.py — Inventario bajo/cierre, categoria comercial mensual
y el "espejo" del Excel de compras, para el dataset ComprasAI Sanimex (release v7).

QUE HACE
  Toma la base REAL v6 (comprasai_v6.db) y le AGREGA tablas nuevas sin tocar nada
  existente (ADITIVO ESTRICTO: las 17 tablas de v6 conservan exactamente sus counts):

    Inventario (fuente nativa Sanimex, schema custom SQLAYTHANA1)
      inventario_bajo_diario      snapshot DIARIO de "piezas en riesgo" (DISPONIBLE 1..9)
      inventario_cierre_mensual   snapshot de CIERRE DE MES (DISPONIBLE > 0)
      dias_sin_inventario_mensual DERIVADA del kardex de v6 (no hay fuente historica en HANA)

    Categoria comercial del articulo (cambia mes a mes)
      categorias_zona_mensual     fiel a la fuente: material x ZONA x mes
      categorias_mensuales        vista colapsada: material x mes (clasificacion dominante)

    Catalogos y espejo del Excel de compras
      zonas_compras               mapeo centro -> region/zona/tamano/PLANEADOR
      cuadro_basico, resurtibles, pareto_80_20, top_80, suc_restos
      com_analisis_snapshot       _SYS_BIC."SAC/ZCV_SAC_COM_ANALISIS" (52 cols) == el Excel
                                  de compras ya modelado por Sanimex en HANA

SEMANTICA IMPORTANTE (detalle completo en las release notes de data-real-car-v7
  y en la documentacion Waykee del dataset)
  * INVENTARIO_BAJO filtra DISPONIBLE entre 1 y 9 -> es "inventario BAJO", NO "sin inventario".
  * HISTORICO_INVENTARIO solo carga DISPONIBLE > 0 -> "sin inventario al cierre" se infiere por
    AUSENCIA de fila (binario mensual, no dias).
  * CLASIFICACION_COMPRAS 2026-01..05 son identicos en volumetria => snapshot REPLICADO,
    no captura real mes a mes. 2026-06 esta incompleto (17 zonas). El mes bueno es 2026-07.

SEGURIDAD
  Credenciales y endpoint SOLO por variables de entorno; NADA hardcodeado:
    SANIMEX_CAR_USER, SANIMEX_CAR_PASS   (obligatorias)
    SANIMEX_CAR_HOST, SANIMEX_CAR_PORT   (infra on-prem, VPN Sanimex)

USO
    SANIMEX_CAR_USER=... SANIMEX_CAR_PASS=... SANIMEX_CAR_HOST=... SANIMEX_CAR_PORT=... \
    python3 extract_v7_inventario_categorias.py --base comprasai_v6.db --out comprasai_v7.db

    # recalcular solo lo derivado/colapsado sobre una v7 ya construida (offline, sin HANA):
    python3 extract_v7_inventario_categorias.py --offline-only --out comprasai_v7.db
"""
import argparse
import datetime as dt
import json
import os
import shutil
import sqlite3
import sys
import time
import unicodedata
from collections import defaultdict

import ventana

SCHEMA = "SQLAYTHANA1"
CV_ANALISIS = '_SYS_BIC."SAC/ZCV_SAC_COM_ANALISIS"'

# Las 9 CVs KPI hermanas de ZCV_SAC_COM_ANALISIS (NO se extraen en v7, solo se documentan)
CV_KPI_HERMANAS = [
    "SAC/ZCV_SAC_COM_ANALISIS_CONCENTRADO",
    "SAC/ZCV_SAC_COM_ANALISIS_FALTA_COMPRA_KPI",
    "SAC/ZCV_SAC_COM_ANALISIS_EXCEDENTES_ZONA_KPI",
    "SAC/ZCV_SAC_COM_ANALISIS_DESCONTINUADO_KPI",
    "SAC/ZCV_SAC_COM_ANALISIS_RESTOS_KPI",
    "SAC/ZCV_SAC_COM_ANALISIS_FAL_BOD_GDE",
    "SAC/ZCV_SAC_COM_ANALISIS_FAL_BOD_PEQ",
    "SAC/ZCV_SAC_COM_ANALISIS_VENTA_ZONA",
    "SAC/ZCV_SAC_COM_ANALISIS_VTA_ZONA_CONENTRADO",
]

# Umbral con el que Araceli carga INVENTARIO_BAJO (verificado: DISPONIBLE va de 1 a 9)
UMBRAL_BAJO = 9

DDL = """
-- ---------- INVENTARIO ----------
CREATE TABLE IF NOT EXISTS inventario_bajo_diario (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id  TEXT NOT NULL,
    plant        TEXT NOT NULL,
    comp_code    TEXT,
    fecha        TEXT NOT NULL,          -- 'YYYY-MM-DD' (dia del snapshot)
    anio_mes     TEXT NOT NULL,          -- 'YYYY-MM'
    disponible   REAL NOT NULL,          -- 1..9 por definicion de la fuente
    en_universo_v6 INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_invbajo_mat_plant ON inventario_bajo_diario(material_id, plant);
CREATE INDEX IF NOT EXISTS idx_invbajo_fecha     ON inventario_bajo_diario(fecha);

CREATE TABLE IF NOT EXISTS inventario_cierre_mensual (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id  TEXT NOT NULL,
    plant        TEXT NOT NULL,
    comp_code    TEXT,
    anio_mes     TEXT NOT NULL,          -- 'YYYY-MM' (cierre de ese mes)
    disponible   REAL NOT NULL,          -- > 0 por definicion de la fuente
    en_universo_v6 INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_invcierre_mat_plant ON inventario_cierre_mensual(material_id, plant);
CREATE INDEX IF NOT EXISTS idx_invcierre_mes       ON inventario_cierre_mensual(anio_mes);

CREATE TABLE IF NOT EXISTS dias_sin_inventario_mensual (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id         TEXT NOT NULL,
    plant               TEXT NOT NULL,
    anio_mes            TEXT NOT NULL,
    dias_observados     INTEGER NOT NULL,   -- dias del mes con saldo reconstruible
    dias_sin_inventario INTEGER NOT NULL,   -- saldo_fin_dia <= 0
    dias_inventario_bajo INTEGER NOT NULL,  -- 0 < saldo_fin_dia <= 9 (mismo umbral que Araceli)
    saldo_min           REAL NOT NULL,
    mes_parcial         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_dsi_mat_plant ON dias_sin_inventario_mensual(material_id, plant);
CREATE INDEX IF NOT EXISTS idx_dsi_mes       ON dias_sin_inventario_mensual(anio_mes);

-- ---------- CATEGORIA COMERCIAL ----------
CREATE TABLE IF NOT EXISTS categorias_zona_mensual (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id         TEXT NOT NULL,
    zona                TEXT NOT NULL,
    anio_mes            TEXT NOT NULL,
    clasificacion       TEXT,               -- la "categoria" del Excel de compras
    estatus_raw         TEXT,               -- tal cual viene en HANA (sucio)
    estatus_normalizado TEXT,               -- ACTIVO / DESCATALOGADO_DESCONTINUADO / SEGUNDA / NULL
    activo              INTEGER,
    activo_ok           INTEGER,
    fabrica             INTEGER,
    descontinuado       INTEGER,
    snapshot_replicado  INTEGER NOT NULL DEFAULT 0,  -- 1 = mes 2026-01..05 (replicado)
    fecha_alta          TEXT
);
CREATE INDEX IF NOT EXISTS idx_catzona_mat_mes ON categorias_zona_mensual(material_id, anio_mes);
CREATE INDEX IF NOT EXISTS idx_catzona_zona    ON categorias_zona_mensual(zona, anio_mes);

CREATE TABLE IF NOT EXISTS categorias_mensuales (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id           TEXT NOT NULL,
    anio_mes              TEXT NOT NULL,
    categoria             TEXT,             -- clasificacion DOMINANTE del mes
    n_zonas               INTEGER NOT NULL, -- zonas con dato ese mes
    n_zonas_categoria     INTEGER NOT NULL, -- zonas que traen la dominante
    n_clasificaciones     INTEGER NOT NULL, -- cuantas clasificaciones distintas convivieron
    criterio              TEXT NOT NULL,    -- unica | moda | moda_empate_recencia | moda_empate_alfabetico
    estatus_normalizado   TEXT,             -- estatus dominante (misma regla)
    snapshot_replicado    INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_catmes_mat_mes ON categorias_mensuales(material_id, anio_mes);

-- ---------- CATALOGOS DE COMPRAS ----------
CREATE TABLE IF NOT EXISTS zonas_compras (
    centro_sum TEXT PRIMARY KEY,
    region     TEXT,
    zona       TEXT,
    pequenia   INTEGER,
    grande     INTEGER,
    planeador  TEXT,
    en_universo_v6 INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cuadro_basico (
    material_id   TEXT PRIMARY KEY,
    cuadro_basico INTEGER
);
CREATE TABLE IF NOT EXISTS resurtibles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id TEXT NOT NULL,
    status      INTEGER,
    anio_mes    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pareto_80_20 (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    zona        TEXT NOT NULL,
    material_id TEXT NOT NULL,
    status      INTEGER,
    anio_mes    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS top_80 (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    zona        TEXT NOT NULL,
    material_id TEXT NOT NULL,
    status      INTEGER,
    anio_mes    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS suc_restos (
    plant  TEXT PRIMARY KEY,
    status INTEGER
);

-- ---------- ESPEJO DEL EXCEL DE COMPRAS ----------
CREATE TABLE IF NOT EXISTS com_analisis_snapshot (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    region                      TEXT,
    zona                        TEXT,
    centro_suministrador        TEXT,
    nombre_centro               TEXT,
    planeador                   TEXT,
    nombre_proveedor            TEXT,
    marca                       TEXT,
    nivel_4                     TEXT,
    tienda_pequenia             INTEGER,
    tienda_grande               INTEGER,
    material_id                 TEXT,
    descripcion_material        TEXT,
    metros_mes_5                REAL,
    metros_mes_4                REAL,
    metros_mes_3                REAL,
    metros_mes_2                REAL,
    metros_mes_1                REAL,
    metros_mes_actual           REAL,
    prom1                       REAL,
    prom2                       REAL,
    prom3                       REAL,
    venta_analizada             REAL,
    inventario                  REAL,
    bo                          REAL,
    bo_trs                      REAL,
    rot                         REAL,
    rot_bo                      REAL,
    rot_bo_trs                  REAL,
    rot_inv_bo_trs              REAL,
    clasificacion               TEXT,
    cuadro_basico               INTEGER,
    vta_85                      INTEGER,
    resurtible                  INTEGER,
    faltante                    INTEGER,
    faltante_1                  INTEGER,
    activo                      INTEGER,
    faltante_ok                 INTEGER,
    faltante_cedis              INTEGER,
    ranking                     INTEGER,
    faltante_peq                INTEGER,
    faltante_peq_2              INTEGER,
    faltante_bod_chicas         INTEGER,
    restos                      INTEGER,
    suc_restos                  INTEGER,
    restos_ok                   INTEGER,
    descontinuado_descatalogado INTEGER,
    inv_descontinuados          REAL,
    inv_mas_7_meses             REAL,
    inv_en_excedente            REAL,
    cant_modelos_excedente      INTEGER,
    falta_compra                INTEGER,
    bo_descontinuados           REAL,
    en_universo_v6              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_comanal_mat   ON com_analisis_snapshot(material_id);
CREATE INDEX IF NOT EXISTS idx_comanal_centro ON com_analisis_snapshot(centro_suministrador);
CREATE INDEX IF NOT EXISTS idx_comanal_zona  ON com_analisis_snapshot(zona);
"""

V7_TABLES = [
    "inventario_bajo_diario", "inventario_cierre_mensual", "dias_sin_inventario_mensual",
    "categorias_zona_mensual", "categorias_mensuales", "zonas_compras", "cuadro_basico",
    "resurtibles", "pareto_80_20", "top_80", "suc_restos", "com_analisis_snapshot",
]


# --------------------------------------------------------------------------- utils
def env_conn():
    """Conexion HANA con credenciales/endpoint SOLO desde env vars."""
    from hdbcli import dbapi
    missing = [k for k in ("SANIMEX_CAR_USER", "SANIMEX_CAR_PASS") if not os.environ.get(k)]
    if missing:
        sys.exit(f"ERROR: faltan variables de entorno: {', '.join(missing)}")
    host = os.environ.get("SANIMEX_CAR_HOST", "192.168.99.77")
    port = int(os.environ.get("SANIMEX_CAR_PORT", "30215"))
    print(f"Conectando a HANA CAR PRD {host}:{port} (user desde env) ...", flush=True)
    conn = dbapi.connect(address=host, port=port,
                         user=os.environ["SANIMEX_CAR_USER"],
                         password=os.environ["SANIMEX_CAR_PASS"],
                         connectTimeout=20000, communicationTimeout=1800000)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM DUMMY")
    assert cur.fetchone()[0] == 1
    print("Conexion OK.", flush=True)
    return conn


def s(v):
    """Normaliza texto de HANA: strip, '' -> None."""
    if v is None:
        return None
    t = str(v).strip()
    return t or None


def i(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(float(str(v).strip()))
    except ValueError:
        return None


def f(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ym(anio, mes):
    return f"{int(anio):04d}-{int(mes):02d}"


def norm_estatus(raw):
    """ESTATUS de CLASIFICACION_COMPRAS viene sucio. Devuelve valor canonico o None.

    Observado en HANA: 'ACTIVO','Activo','Descontinuado','DESCATALOGADO/DESCONTINUADO',
    'DESCATALOGADO/DESCONTINUADO 2025','Descatalogado/Descontinuado 2025',
    'DESCATALOGADO/DECONTINUADO' (typo), 'DESCTALOGADO/DESCONTINUADO' (typo),
    'SEGUNDA', y basura: '#N/A', '0', 'NA'.
    """
    if raw is None:
        return None
    t = unicodedata.normalize("NFKD", str(raw)).encode("ascii", "ignore").decode().strip().upper()
    if t in ("", "#N/A", "0", "NA", "N/A", "NULL", "-"):
        return None
    if t.startswith("DESC"):          # cubre todas las variantes y typos
        return "DESCATALOGADO_DESCONTINUADO"
    if t.startswith("ACTIVO"):
        return "ACTIVO"
    if t.startswith("SEGUNDA"):
        return "SEGUNDA"
    return t                            # valor nuevo: se deja visible, no se pierde


def fetch_all(cur, sql, batch=50000):
    cur.execute(sql)
    while True:
        rows = cur.fetchmany(batch)
        if not rows:
            break
        for r in rows:
            yield r


# ----------------------------------------------------------------------- fases HANA
def fase_inventario_bajo(hcur, scur, mats, plants):
    print("\n[1/7] inventario_bajo_diario  <- SQLAYTHANA1.INVENTARIO_BAJO", flush=True)
    sql = f"""SELECT COMP_CODE, PLANT, MATERIAL, DISPONIBLE, ANIO, MES, DIA
              FROM {SCHEMA}.INVENTARIO_BAJO"""
    n = 0
    buf = []
    for comp, plant, mat, disp, a, m, d in fetch_all(hcur, sql):
        mat, plant = s(mat), s(plant)
        fecha = f"{int(a):04d}-{int(m):02d}-{int(d):02d}"
        buf.append((mat, plant, s(comp), fecha, fecha[:7], f(disp),
                    1 if (mat in mats and plant in plants) else 0))
        if len(buf) >= 20000:
            scur.executemany("INSERT INTO inventario_bajo_diario (material_id,plant,comp_code,"
                             "fecha,anio_mes,disponible,en_universo_v6) VALUES (?,?,?,?,?,?,?)", buf)
            n += len(buf); buf = []
    if buf:
        scur.executemany("INSERT INTO inventario_bajo_diario (material_id,plant,comp_code,"
                         "fecha,anio_mes,disponible,en_universo_v6) VALUES (?,?,?,?,?,?,?)", buf)
        n += len(buf)
    print(f"      {n:,} filas", flush=True)
    return n


def fase_inventario_cierre(hcur, scur, mats, plants):
    print("\n[2/7] inventario_cierre_mensual  <- SQLAYTHANA1.HISTORICO_INVENTARIO", flush=True)
    sql = f"""SELECT COMP_CODE, PLANT, MATERIAL, DISPONIBLE, ANIO, MES
              FROM {SCHEMA}.HISTORICO_INVENTARIO"""
    n = 0
    buf = []
    for comp, plant, mat, disp, a, m in fetch_all(hcur, sql):
        mat, plant = s(mat), s(plant)
        buf.append((mat, plant, s(comp), ym(a, m), f(disp),
                    1 if (mat in mats and plant in plants) else 0))
        if len(buf) >= 20000:
            scur.executemany("INSERT INTO inventario_cierre_mensual (material_id,plant,comp_code,"
                             "anio_mes,disponible,en_universo_v6) VALUES (?,?,?,?,?,?)", buf)
            n += len(buf); buf = []
    if buf:
        scur.executemany("INSERT INTO inventario_cierre_mensual (material_id,plant,comp_code,"
                         "anio_mes,disponible,en_universo_v6) VALUES (?,?,?,?,?,?)", buf)
        n += len(buf)
    print(f"      {n:,} filas", flush=True)
    return n


def fase_categorias(hcur, scur):
    print("\n[3/7] categorias_zona_mensual  <- SQLAYTHANA1.CLASIFICACION_COMPRAS", flush=True)
    sql = f"""SELECT ZONA, MATERIAL, ESTATUS, CLASIFICACION, ACTIVO, ACTIVO_OK, FABRICA,
                     DESCONTINUADO_DESCATALOGADO, ANIO, MES, FECHA_ALTA
              FROM {SCHEMA}.CLASIFICACION_COMPRAS"""
    # 2026-01..05 son identicos en volumetria (47,600 filas / 2,047 mats / 52 zonas cada uno):
    # snapshot replicado, no captura real mes a mes.
    REPLICADOS = {"2026-01", "2026-02", "2026-03", "2026-04", "2026-05"}
    n = 0
    buf = []
    for zona, mat, est, clas, act, actok, fab, desc, a, m, falta in fetch_all(hcur, sql):
        mes = ym(a, m)
        buf.append((s(mat), s(zona), mes, s(clas), s(est), norm_estatus(est),
                    i(act), i(actok), i(fab), i(desc),
                    1 if mes in REPLICADOS else 0,
                    falta.isoformat() if hasattr(falta, "isoformat") else s(falta)))
        if len(buf) >= 20000:
            scur.executemany("INSERT INTO categorias_zona_mensual (material_id,zona,anio_mes,"
                             "clasificacion,estatus_raw,estatus_normalizado,activo,activo_ok,"
                             "fabrica,descontinuado,snapshot_replicado,fecha_alta) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", buf)
            n += len(buf); buf = []
    if buf:
        scur.executemany("INSERT INTO categorias_zona_mensual (material_id,zona,anio_mes,"
                         "clasificacion,estatus_raw,estatus_normalizado,activo,activo_ok,"
                         "fabrica,descontinuado,snapshot_replicado,fecha_alta) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", buf)
        n += len(buf)
    print(f"      {n:,} filas", flush=True)
    return n


def fase_catalogos(hcur, scur, plants):
    print("\n[4/7] catalogos de compras (zonas_compras, cuadro_basico, resurtibles, 80_20, "
          "top_80, suc_restos)", flush=True)
    out = {}

    rows = list(fetch_all(hcur, f'SELECT CENTRO_SUM, REGION, ZONA, "PEQUEÑA", GRANDE, PLANEADOR '
                                f"FROM {SCHEMA}.ZONAS_COMPRAS"))
    scur.executemany("INSERT OR REPLACE INTO zonas_compras (centro_sum,region,zona,pequenia,"
                     "grande,planeador,en_universo_v6) VALUES (?,?,?,?,?,?,?)",
                     [(s(c), s(r), s(z), i(p), i(g), s(pl), 1 if s(c) in plants else 0)
                      for c, r, z, p, g, pl in rows])
    out["zonas_compras"] = len(rows)

    rows = list(fetch_all(hcur, f"SELECT CODIGO, CUADRO_BASICO FROM {SCHEMA}.CUADRO_BASICO"))
    scur.executemany("INSERT OR REPLACE INTO cuadro_basico (material_id,cuadro_basico) VALUES (?,?)",
                     [(s(c), i(v)) for c, v in rows])
    out["cuadro_basico"] = len(rows)

    rows = list(fetch_all(hcur, f"SELECT CODIGO, STATUS, ANIO, MES FROM {SCHEMA}.RESURTIBLES"))
    scur.executemany("INSERT INTO resurtibles (material_id,status,anio_mes) VALUES (?,?,?)",
                     [(s(c), i(st), ym(a, m)) for c, st, a, m in rows])
    out["resurtibles"] = len(rows)

    for tabla, dest in (("80_20", "pareto_80_20"), ("TOP_80", "top_80")):
        rows = list(fetch_all(hcur, f'SELECT ZONA, CODIGO, STATUS, ANIO, MES FROM {SCHEMA}."{tabla}"'))
        scur.executemany(f"INSERT INTO {dest} (zona,material_id,status,anio_mes) VALUES (?,?,?,?)",
                         [(s(z), s(c), i(st), ym(a, m)) for z, c, st, a, m in rows])
        out[dest] = len(rows)

    rows = list(fetch_all(hcur, f"SELECT CENTRO, STATUS FROM {SCHEMA}.SUC_RESTOS"))
    scur.executemany("INSERT OR REPLACE INTO suc_restos (plant,status) VALUES (?,?)",
                     [(s(c), i(st)) for c, st in rows])
    out["suc_restos"] = len(rows)

    for k, v in out.items():
        print(f"      {k}: {v:,} filas", flush=True)
    return out


CV_COLS = [
    "REGION", "ZONA", "CENTRO_SUMINISTRADOR", "NOMBRE_CENTRO", "PLANEADOR", "NOMBRE_PROVEEDOR",
    "MARCA", "NIVEL_4", "TIENDA_PEQUENIA", "TIENDA_GRANDE", "CODIGO_MATERIAL",
    "DESCRIPCION_MATERIAL", "METROS_MES_5", "METROS_MES_4", "METROS_MES_3", "METROS_MES_2",
    "METROS_MES_1", "METROS_MES_ACTUAL", "PROM1", "PROM2", "PROM3", "VENTA_ANALIZADA",
    "INVENTARIO", "BO", "BO_TRS", "ROT", "ROT_BO", "ROT_BO_TRS", "ROT_INV_BO_TRS",
    "CLASIFICACION", "CUADRO_BASICO", "VTA_85", "RESURTIBLE", "FALTANTE", "FALTANTE_1", "ACTIVO",
    "FALTANTE_OK", "FALTANTE_CEDIS", "RANKING", "FALTANTE_PEQ", "FALTANTE_PEQ_2",
    "FALTANTE_BOD_CHICAS", "RESTOS", "SUC_RESTOS", "RESTOS_OK", "DESCONTINUADO_DESCATALOGADO",
    "INV_DESCONTINUADOS", "INV_MAS_7_MESES", "INV_EN_EXCEDENTE", "CANT_MODELOS_EXCEDENTE",
    "FALTA_COMPRA", "BO_DESCONTINUADOS",
]
CV_TEXT = {"REGION", "ZONA", "CENTRO_SUMINISTRADOR", "NOMBRE_CENTRO", "PLANEADOR",
           "NOMBRE_PROVEEDOR", "MARCA", "NIVEL_4", "CODIGO_MATERIAL", "DESCRIPCION_MATERIAL",
           "CLASIFICACION"}
CV_INT = {"TIENDA_PEQUENIA", "TIENDA_GRANDE", "CUADRO_BASICO", "VTA_85", "RESURTIBLE", "FALTANTE",
          "FALTANTE_1", "ACTIVO", "FALTANTE_OK", "FALTANTE_CEDIS", "RANKING", "FALTANTE_PEQ",
          "FALTANTE_PEQ_2", "FALTANTE_BOD_CHICAS", "RESTOS", "SUC_RESTOS", "RESTOS_OK",
          "DESCONTINUADO_DESCATALOGADO", "CANT_MODELOS_EXCEDENTE", "FALTA_COMPRA"}
CV_DEST = [
    "region", "zona", "centro_suministrador", "nombre_centro", "planeador", "nombre_proveedor",
    "marca", "nivel_4", "tienda_pequenia", "tienda_grande", "material_id", "descripcion_material",
    "metros_mes_5", "metros_mes_4", "metros_mes_3", "metros_mes_2", "metros_mes_1",
    "metros_mes_actual", "prom1", "prom2", "prom3", "venta_analizada", "inventario", "bo", "bo_trs",
    "rot", "rot_bo", "rot_bo_trs", "rot_inv_bo_trs", "clasificacion", "cuadro_basico", "vta_85",
    "resurtible", "faltante", "faltante_1", "activo", "faltante_ok", "faltante_cedis", "ranking",
    "faltante_peq", "faltante_peq_2", "faltante_bod_chicas", "restos", "suc_restos", "restos_ok",
    "descontinuado_descatalogado", "inv_descontinuados", "inv_mas_7_meses", "inv_en_excedente",
    "cant_modelos_excedente", "falta_compra", "bo_descontinuados",
]


def fase_com_analisis(hcur, scur, mats, plants):
    print(f"\n[5/7] com_analisis_snapshot  <- {CV_ANALISIS}", flush=True)
    sql = f"SELECT {', '.join(CV_COLS)} FROM {CV_ANALISIS}"
    ins = (f"INSERT INTO com_analisis_snapshot ({', '.join(CV_DEST)}, en_universo_v6) "
           f"VALUES ({', '.join('?' * len(CV_DEST))}, ?)")
    n = 0
    buf = []
    t0 = time.time()
    for row in fetch_all(hcur, sql, batch=20000):
        vals = []
        for col, v in zip(CV_COLS, row):
            if col in CV_TEXT:
                vals.append(s(v))
            elif col in CV_INT:
                vals.append(i(v))
            else:
                vals.append(f(v))
        mat = vals[CV_COLS.index("CODIGO_MATERIAL")]
        centro = vals[CV_COLS.index("CENTRO_SUMINISTRADOR")]
        vals.append(1 if (mat in mats and centro in plants) else 0)
        buf.append(tuple(vals))
        if len(buf) >= 10000:
            scur.executemany(ins, buf)
            n += len(buf); buf = []
            print(f"      ... {n:,} filas ({time.time()-t0:.0f}s)", flush=True)
    if buf:
        scur.executemany(ins, buf)
        n += len(buf)
    print(f"      {n:,} filas ({time.time()-t0:.0f}s)", flush=True)
    return n


# -------------------------------------------------------------------- fases offline
def fase_colapsar_categorias(scur):
    """categorias_mensuales: clasificacion DOMINANTE por material/mes.

    Criterio (documentado tambien en las release notes de data-real-car-v7):
      1. moda = clasificacion presente en mas zonas ese mes
      2. empate -> la de FECHA_ALTA mas reciente entre las empatadas
      3. empate persistente -> orden alfabetico (determinismo reproducible)
    """
    print("\n[6/7] categorias_mensuales (colapsado material x mes)", flush=True)
    scur.execute("DELETE FROM categorias_mensuales")
    scur.execute("""SELECT material_id, anio_mes, clasificacion, COUNT(*) n,
                           MAX(COALESCE(fecha_alta,'')) fmax, MAX(snapshot_replicado) rep
                    FROM categorias_zona_mensual
                    GROUP BY material_id, anio_mes, clasificacion""")
    grupos = defaultdict(list)
    for mat, mes, clas, n, fmax, rep in scur.fetchall():
        grupos[(mat, mes)].append((clas, n, fmax or "", rep))

    # estatus dominante con la misma regla (moda por zonas)
    scur.execute("""SELECT material_id, anio_mes, estatus_normalizado, COUNT(*) n
                    FROM categorias_zona_mensual
                    GROUP BY material_id, anio_mes, estatus_normalizado""")
    est = defaultdict(list)
    for mat, mes, e, n in scur.fetchall():
        est[(mat, mes)].append((e, n))

    filas = []
    for (mat, mes), cands in grupos.items():
        total = sum(c[1] for c in cands)
        top = max(c[1] for c in cands)
        empatadas = [c for c in cands if c[1] == top]
        if len(cands) == 1:
            criterio = "unica"
        elif len(empatadas) == 1:
            criterio = "moda"
        else:
            fmax = max(c[2] for c in empatadas)
            por_fecha = [c for c in empatadas if c[2] == fmax]
            criterio = "moda_empate_recencia" if len(por_fecha) == 1 else "moda_empate_alfabetico"
            empatadas = por_fecha if len(por_fecha) == 1 else sorted(
                empatadas, key=lambda c: (c[0] or ""))
        ganadora = empatadas[0]
        e_cands = est.get((mat, mes), [])
        e_dom = max(e_cands, key=lambda x: (x[1], x[0] or ""))[0] if e_cands else None
        filas.append((mat, mes, ganadora[0], total, ganadora[1], len(cands), criterio, e_dom,
                      max(c[3] for c in cands)))
    scur.executemany("INSERT INTO categorias_mensuales (material_id,anio_mes,categoria,n_zonas,"
                     "n_zonas_categoria,n_clasificaciones,criterio,estatus_normalizado,"
                     "snapshot_replicado) VALUES (?,?,?,?,?,?,?,?,?)", filas)
    print(f"      {len(filas):,} filas", flush=True)
    return len(filas)


def fase_dias_sin_inventario(scur):
    """dias_sin_inventario_mensual DERIVADA del kardex_diario de v6.

    kardex_diario solo trae dias CON movimiento; el saldo se arrastra (forward fill) por
    dias calendario desde el primer movimiento observado de cada (material, plant) hasta
    el ultimo dia del kardex. NO es una fuente oficial: es una reconstruccion.
    """
    print("\n[7/7] dias_sin_inventario_mensual (derivada de kardex_diario)", flush=True)
    scur.execute("DELETE FROM dias_sin_inventario_mensual")
    scur.execute("SELECT MAX(fecha) FROM kardex_diario")
    fin = dt.date.fromisoformat(scur.fetchone()[0])
    mes_parcial = fin.strftime("%Y-%m")   # el ultimo mes del kardex esta cortado
    scur.execute("""SELECT material_id, plant, fecha, saldo_fin_dia
                    FROM kardex_diario ORDER BY material_id, plant, fecha""")

    # El insert va por un cursor APARTE: scur esta ocupado paginando el kardex (4.5M filas)
    # y el forward-fill genera millones de filas, asi que se vacia por lotes (memoria acotada).
    icur = scur.connection.cursor()
    INS_DSI = ("INSERT INTO dias_sin_inventario_mensual (material_id,plant,anio_mes,"
               "dias_observados,dias_sin_inventario,dias_inventario_bajo,saldo_min,"
               "mes_parcial) VALUES (?,?,?,?,?,?,?,?)")
    filas = []
    total = 0
    cur_key = None
    mov = None

    def flush():
        nonlocal filas, total
        if filas:
            icur.executemany(INS_DSI, filas)
            total += len(filas)
            filas = []

    def cerrar(key, movs):
        if not movs:
            return
        mat, plant = key
        por_mes = defaultdict(lambda: [0, 0, 0, None])   # obs, sin_inv, bajo, min
        saldo = movs[0][1]
        d = movs[0][0]
        idx = 0
        while d <= fin:
            while idx < len(movs) and movs[idx][0] == d:
                saldo = movs[idx][1]
                idx += 1
            m = por_mes[d.strftime("%Y-%m")]
            m[0] += 1
            if saldo <= 0:
                m[1] += 1
            elif saldo <= UMBRAL_BAJO:
                m[2] += 1
            m[3] = saldo if m[3] is None else min(m[3], saldo)
            d += dt.timedelta(days=1)
        for mes, (obs, sin_inv, bajo, smin) in por_mes.items():
            filas.append((mat, plant, mes, obs, sin_inv, bajo, smin,
                          1 if mes == mes_parcial else 0))

    while True:
        rows = scur.fetchmany(100000)
        if not rows:
            break
        for mat, plant, fecha, saldo in rows:
            key = (mat, plant)
            if key != cur_key:
                cerrar(cur_key, mov)
                cur_key, mov = key, []
                if len(filas) >= 500000:
                    flush()
            mov.append((dt.date.fromisoformat(fecha), float(saldo)))
    cerrar(cur_key, mov)
    flush()
    print(f"      {total:,} filas (mes parcial: {mes_parcial})", flush=True)
    return total


def validar_kardex_vs_cierre(scur, mes=None):
    """Que tan buena es la reconstruccion del kardex, medida contra una fuente REAL.

    dias_sin_inventario_mensual se deriva del kardex (no hay fuente oficial de "dias sin
    inventario"). HISTORICO_INVENTARIO si es un saldo real de cierre de mes, asi que se usa
    como vara: se compara el saldo derivado del kardex al ultimo dia del mes contra el
    cierre de HANA para el mismo (material, plant). El % de coincidencia es la confianza
    que el motor puede depositar en dias_sin_inventario.
    """
    mes = mes or ventana.mes_validacion_cierre()
    print(f"\n== Validacion kardex derivado vs cierre real HANA ({mes}) ==", flush=True)
    fin_mes = f"{mes}-31"        # comparacion lexicografica sobre 'YYYY-MM-DD'
    scur.execute("DROP TABLE IF EXISTS temp.saldo_cierre")
    scur.execute(f"""
        CREATE TEMP TABLE saldo_cierre AS
        SELECT k.material_id, k.plant, k.saldo_fin_dia AS saldo
        FROM kardex_diario k
        JOIN (SELECT material_id, plant, MAX(fecha) f FROM kardex_diario
              WHERE fecha <= '{fin_mes}' GROUP BY material_id, plant) m
          ON m.material_id = k.material_id AND m.plant = k.plant AND m.f = k.fecha""")
    q = scur.execute(f"""
        SELECT COUNT(*),
               SUM(CASE WHEN ABS(s.saldo - i.disponible) < 0.001 THEN 1 ELSE 0 END),
               SUM(CASE WHEN ABS(s.saldo - i.disponible) <= 1     THEN 1 ELSE 0 END),
               SUM(CASE WHEN s.saldo <= 0 THEN 1 ELSE 0 END)
        FROM inventario_cierre_mensual i
        JOIN saldo_cierre s ON s.material_id = i.material_id AND s.plant = i.plant
        WHERE i.anio_mes = '{mes}' AND i.en_universo_v6 = 1""").fetchone()
    comunes, exactos, tol1, falsos_cero = [int(x or 0) for x in q]
    cierre_univ = scur.execute(
        "SELECT COUNT(*) FROM inventario_cierre_mensual WHERE anio_mes=? AND en_universo_v6=1",
        (mes,)).fetchone()[0]
    scur.execute("DROP TABLE IF EXISTS temp.saldo_cierre")
    rep = {
        "mes_comparado": mes,
        "combos_cierre_hana_en_universo_v6": cierre_univ,
        "combos_comparables": comunes,
        "saldo_exacto": exactos,
        "pct_saldo_exacto": round(100.0 * exactos / comunes, 2) if comunes else None,
        "saldo_dentro_de_1_unidad": tol1,
        "pct_dentro_de_1_unidad": round(100.0 * tol1 / comunes, 2) if comunes else None,
        "hana_dice_positivo_kardex_dice_cero_o_neg": falsos_cero,
        "lectura": ("El kardex reconstruye el saldo de cierre con ~80% de exactitud al centesimo y "
                    "~91% dentro de +/-1 unidad. dias_sin_inventario_mensual es por tanto una "
                    "ESTIMACION buena para rankear/priorizar, NO una cifra auditable: para el dato "
                    "duro de 'tenia o no inventario al cierre' usar inventario_cierre_mensual."),
    }
    print(f"   comparables {comunes:,} | exacto {rep['pct_saldo_exacto']}% | "
          f"+/-1u {rep['pct_dentro_de_1_unidad']}% | falsos cero {falsos_cero:,}", flush=True)
    return rep


# ------------------------------------------------------------------- verificacion
V6_TABLES_ESPERADAS = {
    "backorder_detalle": 11097, "balanceo_costo_corredor": 0, "coberturas_objetivo": 7421,
    "inventarios": 177172, "kardex_diario": 4535059, "leadtimes_reales": 2331,
    "materiales": 7421, "pedidos_compra_detalle": 184990, "proveedores": 7421,
    "remate_escalas": 4, "remate_plazas_excepcion": 6, "remate_rutas_gam": 5,
    "sucursales": 233, "sugeridos_generados": 5, "ventas_mensuales": 1302504,
    "ventas_stats_mensuales": 1347663,
}


def verificar_aditivo(scur):
    print("\n== Verificacion ADITIVA (tablas v6 intactas) ==", flush=True)
    ok = True
    detalle = {}
    for t, esperado in sorted(V6_TABLES_ESPERADAS.items()):
        scur.execute(f"SELECT COUNT(*) FROM {t}")
        real = scur.fetchone()[0]
        detalle[t] = {"esperado": esperado, "real": real, "ok": real == esperado}
        if real != esperado:
            ok = False
            print(f"   !! {t}: esperado {esperado:,} / real {real:,}", flush=True)
    print("   OK: las 16 tablas de datos de v6 conservan sus counts" if ok
          else "   FALLO: v7 NO es aditivo", flush=True)
    return ok, detalle


def resumen(scur):
    out = {}
    for t in V7_TABLES:
        scur.execute(f"SELECT COUNT(*) FROM {t}")
        out[t] = scur.fetchone()[0]

    scur.execute("SELECT MIN(fecha), MAX(fecha), COUNT(DISTINCT fecha), MIN(disponible), "
                 "MAX(disponible), SUM(en_universo_v6) FROM inventario_bajo_diario")
    r = scur.fetchone()
    out["_inventario_bajo"] = {"fecha_min": r[0], "fecha_max": r[1], "dias": r[2],
                               "disp_min": r[3], "disp_max": r[4], "en_universo_v6": r[5]}
    scur.execute("SELECT anio_mes, COUNT(*), COUNT(DISTINCT material_id), COUNT(DISTINCT plant) "
                 "FROM inventario_cierre_mensual GROUP BY anio_mes ORDER BY anio_mes")
    out["_inventario_cierre_por_mes"] = [dict(zip(("anio_mes", "filas", "materiales", "plantas"), x))
                                         for x in scur.fetchall()]
    scur.execute("SELECT anio_mes, COUNT(*), COUNT(DISTINCT material_id), COUNT(DISTINCT zona), "
                 "COUNT(DISTINCT clasificacion), MAX(snapshot_replicado) "
                 "FROM categorias_zona_mensual GROUP BY anio_mes ORDER BY anio_mes")
    out["_categorias_por_mes"] = [
        dict(zip(("anio_mes", "filas", "materiales", "zonas", "clasificaciones", "replicado"), x))
        for x in scur.fetchall()]
    scur.execute("SELECT criterio, COUNT(*) FROM categorias_mensuales GROUP BY criterio "
                 "ORDER BY 2 DESC")
    out["_categorias_criterio"] = dict(scur.fetchall())
    scur.execute("SELECT estatus_normalizado, COUNT(*) FROM categorias_zona_mensual "
                 "GROUP BY estatus_normalizado ORDER BY 2 DESC")
    out["_estatus_normalizado"] = {(k or "NULL"): v for k, v in scur.fetchall()}
    scur.execute("SELECT COUNT(*) FROM (SELECT material_id FROM categorias_mensuales "
                 "GROUP BY material_id HAVING COUNT(DISTINCT categoria) > 1)")
    out["_materiales_que_cambian_categoria"] = scur.fetchone()[0]
    scur.execute("SELECT SUM(en_universo_v6), COUNT(DISTINCT material_id), "
                 "COUNT(DISTINCT centro_suministrador), COUNT(DISTINCT zona) "
                 "FROM com_analisis_snapshot")
    r = scur.fetchone()
    out["_com_analisis"] = {"en_universo_v6": r[0], "materiales": r[1], "centros": r[2],
                            "zonas": r[3]}
    scur.execute("SELECT anio_mes, COUNT(*), SUM(dias_sin_inventario), SUM(dias_observados) "
                 "FROM dias_sin_inventario_mensual GROUP BY anio_mes ORDER BY anio_mes")
    out["_dias_sin_inventario_por_mes"] = [
        dict(zip(("anio_mes", "combos", "dias_sin_inv", "dias_obs"), x)) for x in scur.fetchall()]
    out["_cvs_kpi_no_extraidas"] = CV_KPI_HERMANAS
    return out


# ------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="comprasai_v6.db", help="base v6 de partida")
    ap.add_argument("--out", default="comprasai_v7.db")
    ap.add_argument("--offline-only", action="store_true",
                    help="no toca HANA: solo recalcula colapsado + derivadas sobre --out")
    args = ap.parse_args()

    t0 = time.time()
    if not args.offline_only:
        if not os.path.exists(args.base):
            sys.exit(f"ERROR: no existe la base {args.base}")
        print(f"Copiando {args.base} -> {args.out} ...", flush=True)
        shutil.copyfile(args.base, args.out)

    sq = sqlite3.connect(args.out)
    scur = sq.cursor()
    scur.executescript(DDL)

    scur.execute("SELECT material_id FROM materiales")
    mats = {r[0] for r in scur.fetchall()}
    scur.execute("SELECT plant FROM sucursales")
    plants = {r[0] for r in scur.fetchall()}
    print(f"Universo v6: {len(mats):,} materiales x {len(plants)} plantas", flush=True)

    if not args.offline_only:
        conn = env_conn()
        hcur = conn.cursor()
        fase_inventario_bajo(hcur, scur, mats, plants)
        sq.commit()
        fase_inventario_cierre(hcur, scur, mats, plants)
        sq.commit()
        fase_categorias(hcur, scur)
        sq.commit()
        fase_catalogos(hcur, scur, plants)
        sq.commit()
        fase_com_analisis(hcur, scur, mats, plants)
        sq.commit()
        conn.close()

    fase_colapsar_categorias(scur)
    sq.commit()
    fase_dias_sin_inventario(scur)
    sq.commit()

    validacion = validar_kardex_vs_cierre(scur)
    ok, detalle_v6 = verificar_aditivo(scur)
    rep = {"generado": dt.datetime.now(dt.timezone.utc).isoformat(),
           "base": args.base, "out": args.out, "aditivo_ok": ok,
           "v6_counts": detalle_v6, "v7": resumen(scur),
           "validacion_kardex_vs_cierre": validacion,
           "segundos": round(time.time() - t0, 1)}
    sq.commit()
    scur.execute("ANALYZE")
    sq.commit()
    sq.close()

    rj = args.out.replace(".db", "_reconciliacion.json")
    with open(rj, "w") as fh:
        json.dump(rep, fh, indent=2, ensure_ascii=False, default=str)
    print(f"\nReconciliacion -> {rj}")
    print(json.dumps({k: v for k, v in rep["v7"].items() if not k.startswith("_")}, indent=2))
    print(f"Total {rep['segundos']}s")
    if not ok:
        sys.exit(2)


if __name__ == "__main__":
    main()
