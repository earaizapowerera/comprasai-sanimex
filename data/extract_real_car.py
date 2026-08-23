#!/usr/bin/env python3
"""
extract_real_car.py — Extractor de dataset REAL de SAP CAR PRD (HANA) para ComprasAI Sanimex.

Contra: 192.168.99.77:30215 (CAR PRD, VPN Sanimex requerida). SOLO LECTURA.

Fuentes reales usadas:
  - "_SYS_BIC"."BI/ZVTA_BONO"  -> ventas linea a linea (24 meses) -> ventas_mensuales
  - SAPS4H.MARA / MAKT / T023T -> materiales (descripcion, familia)
  - SAPS4H.T001W + TVKO        -> sucursales (organizacion via VKORG, canal via VTWEG+nombre)
  - SAPS4H.EKPO (+ EKKO)       -> inventarios.pedidos_abiertos (PO abiertas, real)
  - SAPS4H.MARC                -> proveedores.lead_time_dias (PLIFZ)
  - SAPS4H.EINA + LFA1         -> proveedores.proveedor (vendor real cuando existe)

Lo que NO existe en el replica de CAR (100% sintetico, marcado explicito):
  - coberturas_objetivo.meses_objetivo  (no hay parametro de cobertura objetivo en CAR)
  - proveedores.moq_cajas / cajas_por_pallet (EINE con condiciones de compra no esta replicado)
  - inventarios.comprometido = 0 para todas las filas (VBBE no existe en el replica)
  - inventarios.disponible / transito: SINTETICO anclado en demanda real (ver seccion 5).
    Verificado en vivo: MARD.LABST/UMLME y MBEW.LBKUM estan en CERO para las 6.6M/6.4M
    filas del replica completo (no solo para nuestro universo) -> las cantidades de
    stock estan enmascaradas/no replicadas en este ambiente CAR, no es dato real disponible.

Uso:
  .venv/bin/python extract_real_car.py [output_path]
"""
import sys, os, time, random
import sqlite3
from collections import defaultdict
from hdbcli import dbapi

random.seed(20260823)

HANA_HOST = os.environ.get('SANIMEX_CAR_HOST', '192.168.99.77')
HANA_PORT = int(os.environ.get('SANIMEX_CAR_PORT', '30215'))
# Credenciales SOLO por entorno (Waykee Secrets: {SanimexCARUser}/{SanimexCARPassword}).
# Nunca hardcodear: este archivo vive en git.
try:
    HANA_USER = os.environ['SANIMEX_CAR_USER']
    HANA_PASS = os.environ['SANIMEX_CAR_PASS']
except KeyError as e:
    sys.exit(f"Falta la variable de entorno {e}. Exporta SANIMEX_CAR_USER y "
             f"SANIMEX_CAR_PASS (via Waykee Secrets) antes de ejecutar.")

HERE = os.path.dirname(__file__)
DB = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'comprasai.db')
SCHEMA_SQL = os.path.join(HERE, '..', 'backend', 'app', 'core', 'schema.sql')

MES_FIN = '202608'   # ultimo mes con datos en CAR (2026-08)
MES_INICIO = '202409'  # 24 meses atras

ORG_MAP = {'1100': 'SA', '1200': 'GSA', '1300': 'GAM', '1400': 'GAMN'}


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def canal_de(name1, vtweg):
    n = (name1 or '').upper()
    if 'ECOMMERCE' in n or 'E-COMMERCE' in n:
        return 'eCommerce'
    if vtweg == '02':
        return 'Mayoreo'
    return 'Menudeo'  # cubre 01 (menudeo tiendas), 03 (profesionales), 04 (empresas)


def es_cedis_de(name1):
    n = (name1 or '').upper()
    return 1 if ('CEDIS' in n and 'MENUDEO' not in n and 'MAYOREO' not in n) else 0


def main():
    t_start = time.time()
    print(f"Conectando a HANA CAR PRD {HANA_HOST}:{HANA_PORT} ...")
    conn = dbapi.connect(address=HANA_HOST, port=HANA_PORT, user=HANA_USER, password=HANA_PASS)
    cur = conn.cursor()
    cur.execute('SELECT 1 FROM DUMMY')
    assert cur.fetchone()[0] == 1
    print("Conexion OK.")

    if os.path.exists(DB):
        os.remove(DB)
    sq = sqlite3.connect(DB)
    scur = sq.cursor()
    with open(SCHEMA_SQL) as f:
        scur.executescript(f.read())
    print("Schema oficial aplicado:", SCHEMA_SQL)

    # ---------------------------------------------------------------
    # 1) SUCURSALES (real: T001W + TVKO/VKORG) -- universo completo
    # ---------------------------------------------------------------
    print("\n=== 1) Sucursales (T001W, plants reales Sanimex) ===")
    cur.execute("""
        SELECT WERKS, NAME1, VKORG, VTWEG, REGIO
        FROM SAPS4H.T001W
        WHERE MANDT='110' AND (WERKS LIKE 'M%' OR WERKS LIKE 'G%' OR WERKS LIKE 'N%' OR WERKS LIKE 'S%')
        ORDER BY WERKS
    """)
    plants_raw = cur.fetchall()
    sucursales = []
    plant_canal = {}
    plant_valid = set()
    for werks, name1, vkorg, vtweg, regio in plants_raw:
        org = ORG_MAP.get(vkorg)
        if not org:
            continue  # plant fuera de las 4 organizaciones de negocio (descartar)
        n1_upper = (name1 or '').upper()
        if 'NO UTILIZAR' in n1_upper or 'CERRADO' in n1_upper:
            continue  # sucursal dada de baja en SAP (descartar del universo de demo)
        canal = canal_de(name1, vtweg)
        cedis = es_cedis_de(name1)
        corredor = regio or None
        sucursales.append((werks.strip(), name1.strip() if name1 else werks, org, canal, corredor, cedis))
        plant_canal[werks.strip()] = canal
        plant_valid.add(werks.strip())
    print(f"  sucursales reales validas: {len(sucursales)}")

    # ---------------------------------------------------------------
    # 2) VENTAS MENSUALES (real: BI/ZVTA_BONO, 24 meses) + acumulados por material
    # ---------------------------------------------------------------
    print(f"\n=== 2) Ventas mensuales reales {MES_INICIO}..{MES_FIN} (BI/ZVTA_BONO) ===")
    t0 = time.time()
    cur.execute("""
        SELECT MATERIALNUMBER, PLANT, ZANIO_MES,
               SUM(ZMETROS) AS M2, SUM(SALESAMOUNT) AS IMPORTE,
               SUM(BASEQUANTITY) AS QTY, SUM(IMP_COST) AS COST_TOTAL
        FROM "_SYS_BIC"."BI/ZVTA_BONO"
        WHERE ZANIO_MES BETWEEN ? AND ?
        GROUP BY MATERIALNUMBER, PLANT, ZANIO_MES
    """, (MES_INICIO, MES_FIN))

    ventas_rows = []
    mat_stats = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])  # mat -> [m2, importe, qty, cost_total]
    n = 0
    batch = cur.fetchmany(50000)
    while batch:
        for matnr, plant, ym, m2, importe, qty, cost_total in batch:
            plant = plant.strip() if plant else plant
            matnr = matnr.strip() if matnr else matnr
            if plant not in plant_valid:
                continue
            m2 = float(m2 or 0); importe = float(importe or 0)
            qty = float(qty or 0); cost_total = float(cost_total or 0)
            anio_mes = f"{ym[0:4]}-{ym[4:6]}"
            canal = plant_canal[plant]
            ventas_rows.append((matnr, plant, canal, anio_mes, m2, importe))
            s = mat_stats[matnr]
            s[0] += m2; s[1] += importe; s[2] += qty; s[3] += cost_total
            n += 1
        batch = cur.fetchmany(50000)
    print(f"  filas ventas_mensuales reales (antes de filtrar MTART): {n} en {time.time()-t0:.1f}s")
    materiales_ids_pre = sorted(mat_stats.keys())
    print(f"  materiales distintos con venta en 24m (antes de filtrar MTART): {len(materiales_ids_pre)}")

    # Filtra MTART: solo HAWA (mercancia comercial fisica). Descarta DIEN (servicios,
    # p.ej. FLETES/MANIOBRAS) y UNBW (no valuados) -- no son SKUs de inventario/compra
    # y su costo=0 rompe las metricas de cobertura/dias de inventario del motor.
    mtart_map = {}
    for chunk in chunks(materiales_ids_pre, 1000):
        placeholders = ','.join(['?'] * len(chunk))
        cur.execute(f"SELECT MATNR, MTART FROM SAPS4H.MARA WHERE MANDT='110' AND MATNR IN ({placeholders})", chunk)
        for matnr, mtart in cur.fetchall():
            mtart_map[matnr.strip()] = mtart
    materiales_ids = [m for m in materiales_ids_pre if mtart_map.get(m) == 'HAWA']
    descartados_mtart = len(materiales_ids_pre) - len(materiales_ids)
    print(f"  descartados por MTART != HAWA (servicios/no-valuados): {descartados_mtart}")
    mat_ids_set = set(materiales_ids)
    ventas_rows = [r for r in ventas_rows if r[0] in mat_ids_set]
    for m in list(mat_stats.keys()):
        if m not in mat_ids_set:
            del mat_stats[m]
    print(f"  filas ventas_mensuales reales (finales, solo HAWA): {len(ventas_rows)}")
    print(f"  materiales distintos con venta en 24m (finales, solo HAWA): {len(materiales_ids)}")

    # ---------------------------------------------------------------
    # 3) ABC (Pareto por importe real 24m) + precio_venta/costo/m2_por_caja (reales, ponderados)
    # ---------------------------------------------------------------
    print("\n=== 3) Clasificacion ABC (Pareto 80/95 sobre importe real) ===")
    ranked = sorted(materiales_ids, key=lambda m: -mat_stats[m][1])
    total_importe = sum(mat_stats[m][1] for m in materiales_ids) or 1.0
    abc_map = {}
    cum = 0.0
    for m in ranked:
        cum += mat_stats[m][1]
        pct = cum / total_importe
        abc_map[m] = 'A' if pct <= 0.80 else ('B' if pct <= 0.95 else 'C')
    print("  A:", sum(1 for v in abc_map.values() if v == 'A'),
          "B:", sum(1 for v in abc_map.values() if v == 'B'),
          "C:", sum(1 for v in abc_map.values() if v == 'C'))

    # ---------------------------------------------------------------
    # 4) MATERIALES: descripcion (MAKT) + familia (MARA.MATKL + T023T)
    # ---------------------------------------------------------------
    print("\n=== 4) Materiales: descripcion (MAKT) + familia (MARA/T023T) ===")
    makt_map = {}
    matkl_map = {}
    for chunk in chunks(materiales_ids, 1000):
        placeholders = ','.join(['?'] * len(chunk))
        cur.execute(f"""SELECT MATNR, MAKTX FROM SAPS4H.MAKT
                        WHERE MANDT='110' AND SPRAS='S' AND MATNR IN ({placeholders})""", chunk)
        for matnr, maktx in cur.fetchall():
            makt_map[matnr.strip()] = maktx
        cur.execute(f"""SELECT MATNR, MATKL FROM SAPS4H.MARA
                        WHERE MANDT='110' AND MATNR IN ({placeholders})""", chunk)
        for matnr, matkl in cur.fetchall():
            matkl_map[matnr.strip()] = matkl
    print(f"  descripciones encontradas: {len(makt_map)}/{len(materiales_ids)}")
    print(f"  grupos de material encontrados: {len(matkl_map)}/{len(materiales_ids)}")

    matkl_ids = sorted(set(v for v in matkl_map.values() if v))
    t023t_map = {}
    for chunk in chunks(matkl_ids, 1000):
        placeholders = ','.join(['?'] * len(chunk))
        cur.execute(f"""SELECT MATKL, WGBEZ FROM SAPS4H.T023T
                        WHERE MANDT='110' AND SPRAS='S' AND MATKL IN ({placeholders})""", chunk)
        for matkl, wgbez in cur.fetchall():
            t023t_map[matkl] = wgbez

    materiales = []
    for m in materiales_ids:
        s = mat_stats[m]
        m2_total, importe_total, qty_total, cost_total = s
        precio_venta = round(importe_total / qty_total, 2) if qty_total > 0 else 0.0
        costo = round(cost_total / qty_total, 2) if qty_total > 0 else 0.0
        m2_por_caja = round(m2_total / qty_total, 4) if qty_total > 0 and m2_total > 0 else None
        descripcion = makt_map.get(m) or m
        matkl = matkl_map.get(m)
        familia = t023t_map.get(matkl, matkl) if matkl else 'SIN CLASIFICAR'
        economico = 1 if precio_venta > 0 and precio_venta < 180 else 0
        materiales.append((m, descripcion, familia, None, m2_por_caja, abc_map[m], precio_venta, costo, economico))

    # ---------------------------------------------------------------
    # 5) INVENTARIOS: pedidos_abiertos real (EKPO); disponible/transito SINTETICO
    #    anclado en demanda real de los ultimos 6 meses (MARD/MBEW estan
    #    enmascarados a 0 en todo el replica -- ver nota arriba)
    # ---------------------------------------------------------------
    print("\n=== 5) Inventarios: pedidos abiertos reales (EKPO) + disponible/transito sintetico (demanda real) ===")
    inv_map = {}  # (mat, plant) -> [disponible, transito, comprometido, pedidos_abiertos]

    t0 = time.time()
    for chunk in chunks(materiales_ids, 500):
        placeholders = ','.join(['?'] * len(chunk))
        cur.execute(f"""
            SELECT p.MATNR, p.WERKS, SUM(p.MENGE)
            FROM SAPS4H.EKPO p
            JOIN SAPS4H.EKKO k ON p.MANDT=k.MANDT AND p.EBELN=k.EBELN
            WHERE p.MANDT='110' AND p.MATNR IN ({placeholders})
              AND (p.ELIKZ IS NULL OR p.ELIKZ='') AND (k.LOEKZ IS NULL OR k.LOEKZ='')
            GROUP BY p.MATNR, p.WERKS
        """, chunk)
        for matnr, werks, menge in cur.fetchall():
            matnr = matnr.strip(); werks = werks.strip()
            if werks not in plant_valid:
                continue
            key = (matnr, werks)
            if key not in inv_map:
                inv_map[key] = [0.0, 0.0, 0.0, 0.0]
            inv_map[key][3] += float(menge or 0)
    print(f"  PO abiertas reales (EKPO) aplicadas: {len(inv_map)} combos ({time.time()-t0:.1f}s)")

    # demanda real ultimos 6 meses (de las ventas ya extraidas) por (material, plant)
    ult6 = set(sorted({r[3] for r in ventas_rows})[-6:])
    dem6 = defaultdict(list)
    for (matnr, plant, canal, anio_mes, m2, importe) in ventas_rows:
        if anio_mes in ult6:
            dem6[(matnr, plant)].append(m2)
    for key in dem6:
        if key not in inv_map:
            inv_map[key] = [0.0, 0.0, 0.0, 0.0]

    mat_m2caja = {m[0]: (m[4] or 1.0) for m in materiales}
    inventarios = []
    for (matnr, werks), (_disp0, _trans0, comp, pedidos) in inv_map.items():
        dem = dem6.get((matnr, werks))
        prom = (sum(dem) / len(dem)) if dem else random.uniform(2, 15)
        meses_stock = random.uniform(0.3, 3.2)
        disponible = round(max(0.0, prom * meses_stock * random.uniform(0.8, 1.2)), 2)
        transito = round(disponible * random.uniform(0.0, 0.5), 2) if random.random() < 0.4 else 0.0
        if disponible == 0 and transito == 0 and pedidos == 0:
            continue
        m2caja = mat_m2caja.get(matnr) or 1.0
        cajas_remanentes = int(round((disponible % m2caja) / m2caja)) if m2caja else 0
        inventarios.append((matnr, werks, disponible, transito, comp, round(pedidos, 2), cajas_remanentes))
    print(f"  filas inventarios (disponible sintetico + pedidos reales, > 0): {len(inventarios)}")

    # ---------------------------------------------------------------
    # 6) COBERTURAS_OBJETIVO -- 100% SINTETICO (no existe en CAR)
    # ---------------------------------------------------------------
    print("\n=== 6) Coberturas objetivo: SINTETICO (no existe parametro en CAR) ===")
    coberturas = []
    base_cob = {'A': 1.5, 'B': 2.0, 'C': 2.8}
    for m in materiales_ids:
        abc = abc_map[m]
        coberturas.append((m, round(base_cob[abc] * random.uniform(0.85, 1.2), 2)))

    # ---------------------------------------------------------------
    # 7) PROVEEDORES -- proveedor real (EINA+LFA1) + lead_time real (MARC.PLIFZ);
    #    moq_cajas / cajas_por_pallet SINTETICOS (EINE con condiciones no esta replicado)
    # ---------------------------------------------------------------
    print("\n=== 7) Proveedores: nombre real (EINA/LFA1) + lead_time real (MARC.PLIFZ) ===")
    vendor_map = {}
    for chunk in chunks(materiales_ids, 500):
        placeholders = ','.join(['?'] * len(chunk))
        cur.execute(f"""
            SELECT e.MATNR, MIN(e.LIFNR)
            FROM SAPS4H.EINA e
            WHERE e.MANDT='110' AND e.MATNR IN ({placeholders})
            GROUP BY e.MATNR
        """, chunk)
        for matnr, lifnr in cur.fetchall():
            vendor_map[matnr.strip()] = lifnr.strip() if lifnr else None
    lifnr_ids = sorted(set(v for v in vendor_map.values() if v))
    lfa1_map = {}
    for chunk in chunks(lifnr_ids, 1000):
        placeholders = ','.join(['?'] * len(chunk))
        cur.execute(f"""SELECT LIFNR, NAME1 FROM SAPS4H.LFA1 WHERE MANDT='110' AND LIFNR IN ({placeholders})""", chunk)
        for lifnr, name1 in cur.fetchall():
            lfa1_map[lifnr.strip()] = name1
    print(f"  materiales con vendor real (EINA): {len(vendor_map)}/{len(materiales_ids)}")

    plifz_map = defaultdict(list)
    for chunk in chunks(materiales_ids, 500):
        placeholders = ','.join(['?'] * len(chunk))
        cur.execute(f"""SELECT MATNR, PLIFZ FROM SAPS4H.MARC WHERE MANDT='110' AND MATNR IN ({placeholders})""", chunk)
        for matnr, plifz in cur.fetchall():
            if plifz is not None:
                plifz_map[matnr.strip()].append(float(plifz))

    FALLBACK_VENDORS = ["Porcelanite Lamosa", "Vitromex", "Interceramic", "Ceramica San Lorenzo", "Grupo Cedasa (import)"]
    proveedores = []
    for m in materiales_ids:
        lifnr = vendor_map.get(m)
        vendor_name = lfa1_map.get(lifnr) if lifnr else None
        if not vendor_name:
            vendor_name = random.choice(FALLBACK_VENDORS)  # SINTETICO: sin EINA para este material
        plifz_list = plifz_map.get(m)
        lead_time = round(sum(plifz_list) / len(plifz_list)) if plifz_list else 15  # 15 = fallback SINTETICO
        moq_cajas = random.choice([20, 30, 40, 60])          # SINTETICO
        cajas_por_pallet = random.choice([24, 32, 40, 48])   # SINTETICO
        proveedores.append((m, vendor_name.strip() if isinstance(vendor_name, str) else vendor_name,
                             lead_time, moq_cajas, cajas_por_pallet))

    # ---------------------------------------------------------------
    # INSERTS
    # ---------------------------------------------------------------
    print("\n=== Insertando en SQLite ===")
    scur.executemany("INSERT INTO sucursales(plant,nombre,organizacion,canal,corredor,es_cedis) VALUES (?,?,?,?,?,?)", sucursales)
    scur.executemany("INSERT INTO materiales(material_id,descripcion,familia,formato,m2_por_caja,abc,precio_venta,costo,economico) VALUES (?,?,?,?,?,?,?,?,?)", materiales)
    scur.executemany("INSERT INTO ventas_mensuales(material_id,plant,canal,anio_mes,cantidad_m2,importe) VALUES (?,?,?,?,?,?)", ventas_rows)
    scur.executemany("INSERT INTO inventarios(material_id,plant,disponible,transito,comprometido,pedidos_abiertos,cajas_remanentes) VALUES (?,?,?,?,?,?,?)", inventarios)
    scur.executemany("INSERT INTO coberturas_objetivo(material_id,meses_objetivo) VALUES (?,?)", coberturas)
    scur.executemany("INSERT INTO proveedores(material_id,proveedor,lead_time_dias,moq_cajas,cajas_por_pallet) VALUES (?,?,?,?,?)", proveedores)
    sq.commit()

    print("\n=== CONTEOS ===")
    for t in ["materiales", "sucursales", "ventas_mensuales", "inventarios", "coberturas_objetivo", "proveedores"]:
        print(f"{t:22s}", scur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
    print("=== rango meses ===", scur.execute("SELECT MIN(anio_mes), MAX(anio_mes) FROM ventas_mensuales").fetchone())
    print("=== ABC ===", scur.execute("SELECT abc, COUNT(*) FROM materiales GROUP BY abc").fetchall())
    print("=== orgs ===", scur.execute("SELECT organizacion, COUNT(*) FROM sucursales GROUP BY organizacion").fetchall())
    print("=== canales ===", scur.execute("SELECT canal, COUNT(*) FROM sucursales GROUP BY canal").fetchall())
    print("=== importe total ventas ($) ===", round(scur.execute("SELECT SUM(importe) FROM ventas_mensuales").fetchone()[0], 2))
    print("=== vendors reales vs fallback ===",
          sum(1 for m in materiales_ids if lfa1_map.get(vendor_map.get(m))),
          "/", len(materiales_ids))
    sq.close()
    conn.close()
    print(f"\nDB: {DB} ({os.path.getsize(DB)/1e6:.2f} MB) -- total {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
