#!/usr/bin/env python3
"""
build_dataset.py — Constructor del dataset de la demo ComprasAI Sanimex.

FUENTE DE DATOS:
  - PREFERIDA: SAP CAR PRD (HANA, _SYS_BIC BI/ZVTA_BONO) via bot Data Expert (19952) con VPN.
  - ESTE RUN: fallback SINTETICO realista (dominio ceramica/porcelanico Sanimex-Porcelanite).
    Motivo del fallback: T1 corre en waykee2-api-vm (Azure) SIN VPN ni ruta a HANA/red Sanimex.
    Cuando la Mac (Data Expert 19952) extraiga los datos reales, se reemplazan
    materiales / sucursales / ventas_mensuales / inventarios manteniendo el mismo esquema.

CONTRATO (SQLite comprasai.db):
  materiales, sucursales, ventas_mensuales, inventarios, coberturas_objetivo, proveedores
"""
import sqlite3, random, math, os

random.seed(20260823)  # reproducible

DB = os.environ.get("COMPRASAI_OUT_DB", os.path.join(os.path.dirname(__file__), "comprasai.db"))
SCHEMA_SQL = os.environ.get("COMPRASAI_SCHEMA")  # ruta al schema.sql oficial del repo
N_MATERIALES = 1800
N_MESES = 24
ANIO_FIN = (2026, 7)  # ultimo mes con ventas: 2026-07 -> 24 meses hacia atras

# ---------- helpers ----------
def meses_atras(anio, mes, n):
    out = []
    for i in range(n):
        m = mes - i
        a = anio
        while m <= 0:
            m += 12; a -= 1
        out.append(f"{a:04d}-{m:02d}")
    return list(reversed(out))

MESES = meses_atras(*ANIO_FIN, N_MESES)

# ---------- catalogos de dominio (ceramica / porcelanico) ----------
FAMILIAS = [
    ("Piso Ceramico", 0.9, 60), ("Piso Porcelanico", 1.4, 90), ("Muro Ceramico", 0.75, 45),
    ("Loseta Vinilica", 1.1, 70), ("Adhesivos y Boquillas", 1.0, 0), ("Sanitarios", 1.0, 0),
    ("Griferia", 1.0, 0), ("Muebles de Bano", 1.0, 0), ("Impermeabilizantes", 1.0, 0),
]
FORMATOS = [
    ("20x20", 1.44), ("30x30", 1.40), ("33x33", 1.32), ("45x45", 1.62),
    ("60x60", 1.44), ("60x120", 1.44), ("15x90", 1.35), ("20x120", 1.44),
    ("N/A", 1.0),
]
COLECCIONES = ["Marmol","Concreto","Madera","Piedra","Cemento","Travertino","Nogal","Onix",
               "Pizarra","Terrazo","Lino","Rustico","Metro","Brick","Perla","Grafito",
               "Beige","Marfil","Arena","Carbon","Nieve","Sahara","Toscana","Verona"]
ACABADOS = ["Mate","Brillante","Satinado","Antideslizante","Pulido","Lappato","Estructurado"]

PROVEEDORES = [
    ("Porcelanite Lamosa", 18, 40, 40), ("Vitromex", 22, 30, 32), ("Interceramic", 25, 30, 30),
    ("Ceramica San Lorenzo", 40, 60, 48), ("Grupo Cedasa (import)", 65, 120, 100),
    ("Roca Sanitarios", 30, 12, 24), ("Helvex", 20, 10, 20), ("Urrea", 15, 15, 30),
    ("Fester (adhesivos)", 10, 50, 50), ("Comex Impermeabilizantes", 12, 40, 48),
]

ORGS = ["GAM","GSA","SA","GAMN"]
CANALES = ["Menudeo","Mayoreo","eCommerce","Outlet","Remates"]
CIUDADES = ["Monterrey","Guadalajara","CDMX","Puebla","Queretaro","Leon","Merida","Tijuana",
            "Culiacan","Hermosillo","Chihuahua","Torreon","Saltillo","Aguascalientes","Cancun",
            "Veracruz","Toluca","Morelia","San Luis","Durango","Mexicali","Reynosa","Villahermosa",
            "Oaxaca","Tuxtla","Cuernavaca","Pachuca","Tepic","Colima","Zacatecas","Campeche",
            "La Paz","Ensenada","Nuevo Laredo","Matamoros","Celaya","Irapuato","Mazatlan",
            "Los Mochis","Cd Juarez"]
CORREDORES = [f"Corredor {c}" for c in
              ["Noreste","Noroeste","Centro","Bajio","Occidente","Sureste","Golfo","Peninsula",
               "Pacifico","Norte","Metropolitano","Frontera"]]

# ---------- generadores ----------
def gen_materiales():
    mats = []
    # distribucion ABC: 20% A, 30% B, 50% C
    for i in range(N_MATERIALES):
        fam, mfac, base_precio = random.choice(FAMILIAS)
        if base_precio > 0:
            fmt, m2caja = random.choice([f for f in FORMATOS if f[0] != "N/A"])
            col = random.choice(COLECCIONES); aca = random.choice(ACABADOS)
            desc = f"{fam.split()[0]} {col} {aca} {fmt}"
            precio = round(base_precio * mfac * random.uniform(0.7, 1.6), 2)  # $/m2
        else:
            fmt, m2caja = "N/A", 1.0
            desc = f"{fam} {random.choice(COLECCIONES)} {random.randint(1,9)}L"
            precio = round(random.uniform(80, 2500), 2)
        r = random.random()
        abc = "A" if r < 0.20 else ("B" if r < 0.50 else "C")
        costo = round(precio * random.uniform(0.55, 0.78), 2)
        economico = 1 if precio < 180 and base_precio > 0 else 0
        mats.append((f"MAT{100000+i}", desc, fam, fmt, m2caja, abc, precio, costo, economico))
    return mats

def gen_sucursales():
    sucs = []
    plants = []
    # 4 CEDIS (uno por organizacion) + 36 sucursales
    for k, org in enumerate(ORGS):
        plant = f"{9000 + k}"
        sucs.append((plant, f"CEDIS {org} {CIUDADES[k]}", org, "Mayoreo", random.choice(CORREDORES), 1))
        plants.append(plant)
    idx = 4
    for j in range(36):
        org = random.choice(ORGS)
        plant = f"{2000 + j}"
        canal = random.choices(CANALES, weights=[50,20,12,10,8])[0]
        ciudad = CIUDADES[idx % len(CIUDADES)]; idx += 1
        sucs.append((plant, f"Sucursal {ciudad} {canal}", org, canal, random.choice(CORREDORES), 0))
        plants.append(plant)
    return sucs, plants

def gen_ventas(mats, sucs):
    ventas = []
    plants_venta = [(p, canal) for (p, nom, org, canal, corr, cedis) in sucs if cedis == 0]
    # estacionalidad (indice 1..12) para construccion (baja en dic/ene, alta primavera-verano)
    estac = {1:0.82,2:0.9,3:1.05,4:1.12,5:1.18,6:1.15,7:1.1,8:1.08,9:1.05,10:1.02,11:0.95,12:0.78}
    for (mid, desc, fam, fmt, m2caja, abc, precio, costo, eco) in mats:
        if fmt == "N/A":  # accesorios: menos plants
            n_plants = random.randint(4, 10)
        else:
            n_plants = {"A": random.randint(14, 26), "B": random.randint(8, 16), "C": random.randint(3, 9)}[abc]
        seleccion = random.sample(plants_venta, min(n_plants, len(plants_venta)))
        base = {"A": random.uniform(180, 900), "B": random.uniform(60, 260), "C": random.uniform(8, 70)}[abc]
        trend = random.uniform(-0.010, 0.020)  # crecimiento/decrecimiento mensual
        for (plant, canal) in seleccion:
            plant_factor = random.uniform(0.5, 1.7)
            for t, ym in enumerate(MESES):
                mes = int(ym.split("-")[1])
                nivel = base * plant_factor * (1 + trend) ** t * estac[mes] * random.uniform(0.75, 1.25)
                if random.random() < 0.05:  # meses ocasionales sin venta
                    continue
                cant_m2 = round(max(0.0, nivel), 2)
                if cant_m2 <= 0:
                    continue
                # canal ajusta ticket: eCommerce/Outlet con descuento
                pfac = {"Menudeo":1.0,"Mayoreo":0.88,"eCommerce":0.97,"Outlet":0.8,"Remates":0.65}[canal]
                importe = round(cant_m2 * precio * pfac, 2)
                ventas.append((mid, plant, canal, ym, cant_m2, importe))
    return ventas

def gen_inventarios(mats, sucs, ventas):
    # demanda mensual promedio por material/plant (ultimos 6 meses) para dimensionar stock
    from collections import defaultdict
    dem = defaultdict(list)
    ult6 = set(MESES[-6:])
    for (mid, plant, canal, ym, cant, imp) in ventas:
        if ym in ult6:
            dem[(mid, plant)].append(cant)
    invs = []
    matmap = {m[0]: m for m in mats}
    # solo genera inventario donde hay historia de venta (realista)
    claves = set(dem.keys())
    # ademas inventario en CEDIS para materiales A/B
    cedis = [s[0] for s in sucs if s[5] == 1]
    for m in mats:
        if m[5] in ("A", "B"):
            for c in random.sample(cedis, k=random.randint(1, len(cedis))):
                claves.add((m[0], c))
    for (mid, plant) in claves:
        m = matmap[mid]
        m2caja = m[4] if m[4] else 1.0
        prom = (sum(dem[(mid, plant)]) / len(dem[(mid, plant)])) if dem.get((mid, plant)) else random.uniform(5, 40)
        meses_stock = random.uniform(0.3, 3.2)
        disponible = round(max(0.0, prom * meses_stock * random.uniform(0.8, 1.2)), 2)
        transito = round(disponible * random.uniform(0.0, 0.5), 2) if random.random() < 0.4 else 0.0
        comprometido = round(disponible * random.uniform(0.0, 0.35), 2)
        pedidos_abiertos = round(prom * random.uniform(0.0, 1.5), 2) if random.random() < 0.5 else 0.0
        cajas_remanentes = int(round((disponible % m2caja) / m2caja * 1)) if m2caja else 0
        cajas_remanentes = random.randint(0, 1) if cajas_remanentes == 0 and random.random() < 0.3 else cajas_remanentes
        invs.append((mid, plant, disponible, transito, comprometido, pedidos_abiertos, cajas_remanentes))
    return invs

def gen_coberturas(mats):
    cob = []
    for m in mats:
        abc = m[5]
        base = {"A": 1.5, "B": 2.0, "C": 2.8}[abc]
        cob.append((m[0], round(base * random.uniform(0.85, 1.2), 2)))
    return cob

def gen_proveedores(mats):
    prov = []
    fam_prov = {
        "Sanitarios": ["Roca Sanitarios"], "Griferia": ["Helvex", "Urrea"],
        "Muebles de Bano": ["Roca Sanitarios"], "Adhesivos y Boquillas": ["Fester (adhesivos)"],
        "Impermeabilizantes": ["Comex Impermeabilizantes"],
    }
    pmap = {p[0]: p for p in PROVEEDORES}
    tiles = ["Porcelanite Lamosa","Vitromex","Interceramic","Ceramica San Lorenzo","Grupo Cedasa (import)"]
    for m in mats:
        fam = m[2]
        cand = fam_prov.get(fam, tiles)
        pnom = random.choice(cand)
        p = pmap[pnom]
        prov.append((m[0], pnom, p[1], p[2], p[3]))
    return prov

# ---------- build ----------
def main():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB); cur = con.cursor()
    if SCHEMA_SQL and os.path.exists(SCHEMA_SQL):
        # Usa el schema oficial del repo (contrato) -> interop garantizada con la API de T3
        with open(SCHEMA_SQL) as f:
            cur.executescript(f.read())
        print("schema: usando contrato oficial", SCHEMA_SQL)
    else:
        cur.executescript("""
        CREATE TABLE materiales(material_id TEXT PRIMARY KEY, descripcion TEXT, familia TEXT,
            formato TEXT, m2_por_caja REAL, abc TEXT, precio_venta REAL, costo REAL, economico INTEGER);
        CREATE TABLE sucursales(plant TEXT PRIMARY KEY, nombre TEXT, organizacion TEXT, canal TEXT,
            corredor TEXT, es_cedis INTEGER);
        CREATE TABLE ventas_mensuales(id INTEGER PRIMARY KEY AUTOINCREMENT, material_id TEXT, plant TEXT,
            canal TEXT, anio_mes TEXT, cantidad_m2 REAL, importe REAL);
        CREATE TABLE inventarios(id INTEGER PRIMARY KEY AUTOINCREMENT, material_id TEXT, plant TEXT,
            disponible REAL, transito REAL, comprometido REAL, pedidos_abiertos REAL, cajas_remanentes INTEGER);
        CREATE TABLE coberturas_objetivo(material_id TEXT PRIMARY KEY, meses_objetivo REAL);
        CREATE TABLE proveedores(material_id TEXT PRIMARY KEY, proveedor TEXT, lead_time_dias INTEGER,
            moq_cajas INTEGER, cajas_por_pallet INTEGER);
        """)
    mats = gen_materiales()
    sucs, plants = gen_sucursales()
    ventas = gen_ventas(mats, sucs)
    invs = gen_inventarios(mats, sucs, ventas)
    cob = gen_coberturas(mats)
    prov = gen_proveedores(mats)

    cur.executemany("INSERT INTO materiales(material_id,descripcion,familia,formato,m2_por_caja,abc,precio_venta,costo,economico) VALUES (?,?,?,?,?,?,?,?,?)", mats)
    cur.executemany("INSERT INTO sucursales(plant,nombre,organizacion,canal,corredor,es_cedis) VALUES (?,?,?,?,?,?)", sucs)
    cur.executemany("INSERT INTO ventas_mensuales(material_id,plant,canal,anio_mes,cantidad_m2,importe) VALUES (?,?,?,?,?,?)", ventas)
    cur.executemany("INSERT INTO inventarios(material_id,plant,disponible,transito,comprometido,pedidos_abiertos,cajas_remanentes) VALUES (?,?,?,?,?,?,?)", invs)
    cur.executemany("INSERT INTO coberturas_objetivo(material_id,meses_objetivo) VALUES (?,?)", cob)
    cur.executemany("INSERT INTO proveedores(material_id,proveedor,lead_time_dias,moq_cajas,cajas_por_pallet) VALUES (?,?,?,?,?)", prov)

    cur.executescript("""
    CREATE INDEX IF NOT EXISTS idx_ventas_material ON ventas_mensuales(material_id);
    CREATE INDEX IF NOT EXISTS idx_ventas_plant ON ventas_mensuales(plant);
    CREATE INDEX IF NOT EXISTS idx_ventas_aniomes ON ventas_mensuales(anio_mes);
    CREATE INDEX IF NOT EXISTS idx_inv_material ON inventarios(material_id);
    CREATE INDEX IF NOT EXISTS idx_inv_plant ON inventarios(plant);
    """)
    con.commit()

    print("=== CONTEOS ===")
    for t in ["materiales","sucursales","ventas_mensuales","inventarios","coberturas_objetivo","proveedores"]:
        print(f"{t:22s}", cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
    print("=== rango meses ===", cur.execute("SELECT MIN(anio_mes), MAX(anio_mes) FROM ventas_mensuales").fetchone())
    print("=== ABC ===", cur.execute("SELECT abc, COUNT(*) FROM materiales GROUP BY abc").fetchall())
    print("=== orgs ===", cur.execute("SELECT organizacion, COUNT(*) FROM sucursales GROUP BY organizacion").fetchall())
    print("=== importe total ventas ($) ===", round(cur.execute("SELECT SUM(importe) FROM ventas_mensuales").fetchone()[0],2))
    con.close()
    print("DB:", DB, f"({os.path.getsize(DB)/1e6:.2f} MB)")

if __name__ == "__main__":
    main()
