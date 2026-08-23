"""
Generador de dataset sintético para ComprasAI Sanimex.

Crea (o recrea) la base SQLite `comprasai.db` siguiendo el CONTRATO DE DATOS
definido en app/core/schema.sql. Cuando T1 entregue el extracto real de SAP
CAR PRD, basta con reemplazar el archivo .db en la misma ruta -- el código de
la API y de los motores (T4/T5/T6) no necesita cambiar porque consume el
mismo contrato de tablas/columnas.

Uso:
    python -m data.seed_sintetico [--db PATH] [--force]

    --force  Recrea el archivo aunque ya exista.
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sqlite3
from pathlib import Path

random.seed(42)

BACKEND_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = BACKEND_DIR / "app" / "core" / "schema.sql"
DEFAULT_DB_PATH = BACKEND_DIR / "data" / "comprasai.db"

# ---------------------------------------------------------------------------
# Catálogos de referencia (estilo Sanimex: pisos, azulejos, sanitarios, etc.)
# ---------------------------------------------------------------------------

FAMILIAS_FORMATOS = {
    "Piso Cerámico": ["30x30", "33x33", "40x40", "45x45"],
    "Piso Porcelanato": ["60x60", "60x120", "80x80", "120x120"],
    "Azulejo": ["20x30", "25x40", "30x60"],
    "Fachada": ["Ladrillo Aparente", "Piedra Rústica", "Cantera"],
    "Pegazulejo": ["Bulto 25kg", "Bulto 20kg"],
    "Boquilla": ["Bolsa 5kg", "Bolsa 1kg", "Bolsa 20kg"],
    "Sanitarios": ["Unitario Blanco", "Dueto Blanco", "Unitario Color"],
    "Accesorios de Instalación": ["Crucetas 2mm", "Niveladores", "Llana Dentada"],
}

# Rango de precio de venta (MXN) y costo aproximado (60-75% del precio) por familia
PRECIO_RANGO = {
    "Piso Cerámico": (85, 160),
    "Piso Porcelanato": (190, 480),
    "Azulejo": (95, 210),
    "Fachada": (140, 320),
    "Pegazulejo": (180, 260),
    "Boquilla": (60, 140),
    "Sanitarios": (950, 3800),
    "Accesorios de Instalación": (35, 180),
}

PROVEEDORES = [
    "Porcelanite Lamosa", "Interceramic", "Vitromex", "Cerámica San Lorenzo",
    "Importados del Balsas", "Grupo IMSA Cerámica", "Roca Sanitarios",
    "Helvex", "Mapei México", "Pegatop",
]

CIUDADES = [
    "Monterrey Centro", "Monterrey San Nicolás", "Monterrey Apodaca",
    "Guadalajara Centro", "Guadalajara Zapopan", "CDMX Iztapalapa",
    "CDMX Coyoacán", "CDMX Naucalpan", "Puebla Centro", "Querétaro Centro",
    "León Centro", "Saltillo Centro", "Torreón Centro", "Chihuahua Centro",
    "Tijuana Centro", "Mexicali Centro", "Culiacán Centro", "Hermosillo Centro",
    "Mérida Centro", "Cancún Centro", "Veracruz Centro", "Xalapa Centro",
    "Toluca Centro", "Morelia Centro", "Aguascalientes Centro", "Reynosa Centro",
    "Matamoros Centro", "Durango Centro", "San Luis Potosí Centro",
    "Villahermosa Centro", "Tuxtla Gutiérrez Centro", "Oaxaca Centro",
    "Pachuca Centro", "Cuernavaca Centro", "Tepic Centro", "Colima Centro",
    "La Paz Centro", "Ensenada Centro", "Nuevo Laredo Centro", "Celaya Centro",
]

ORGANIZACIONES = ["GAM", "GSA", "SA", "GAMN"]
CANALES = ["Menudeo", "Mayoreo", "eCommerce", "Outlet", "Remates"]
CANAL_PESOS = [0.45, 0.30, 0.12, 0.08, 0.05]
CORREDORES = [
    "Corredor Noreste", "Corredor Bajío", "Corredor Centro", "Corredor Occidente",
    "Corredor Sureste", "Corredor Frontera Norte", "Corredor Golfo", "Corredor Pacífico",
]

N_SUCURSALES = 40
N_CEDIS = 4


def month_range(n_meses: int, end_year: int, end_month: int) -> list[str]:
    """Regresa una lista de 'YYYY-MM' de los últimos n_meses terminando en end_year-end_month."""
    meses = []
    y, m = end_year, end_month
    for _ in range(n_meses):
        meses.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    meses.reverse()
    return meses


def build_materiales(conn: sqlite3.Connection) -> list[dict]:
    materiales = []
    seq = 1
    familia_codes = {f: f.split()[0][:3].upper() for f in FAMILIAS_FORMATOS}
    for familia, formatos in FAMILIAS_FORMATOS.items():
        n_items = 24 if familia in ("Piso Cerámico", "Piso Porcelanato", "Azulejo") else 12
        for _ in range(n_items):
            formato = random.choice(formatos)
            precio_min, precio_max = PRECIO_RANGO[familia]
            precio = round(random.uniform(precio_min, precio_max), 2)
            costo = round(precio * random.uniform(0.55, 0.78), 2)
            abc = random.choices(["A", "B", "C"], weights=[0.25, 0.40, 0.35])[0]
            m2_por_caja = round(random.uniform(1.0, 2.4), 2) if "Piso" in familia or familia in ("Azulejo", "Fachada") else None
            economico = 1 if precio <= precio_min + (precio_max - precio_min) * 0.35 else 0
            material_id = f"SAN-{familia_codes[familia]}-{seq:04d}"
            descripcion = f"{familia} {formato}" + (" Económico" if economico else "")
            materiales.append({
                "material_id": material_id,
                "descripcion": descripcion,
                "familia": familia,
                "formato": formato,
                "m2_por_caja": m2_por_caja,
                "abc": abc,
                "precio_venta": precio,
                "costo": costo,
                "economico": economico,
            })
            seq += 1

    conn.executemany(
        """INSERT INTO materiales
           (material_id, descripcion, familia, formato, m2_por_caja, abc, precio_venta, costo, economico)
           VALUES (:material_id, :descripcion, :familia, :formato, :m2_por_caja, :abc,
                   :precio_venta, :costo, :economico)""",
        materiales,
    )
    return materiales


def build_sucursales(conn: sqlite3.Connection) -> list[dict]:
    sucursales = []
    ciudades = list(CIUDADES)
    random.shuffle(ciudades)
    for i in range(N_SUCURSALES):
        ciudad = ciudades[i % len(ciudades)]
        organizacion = ORGANIZACIONES[i % len(ORGANIZACIONES)]
        es_cedis = 1 if i < N_CEDIS else 0
        canal = "Mayoreo" if es_cedis else random.choices(CANALES, weights=CANAL_PESOS)[0]
        corredor = random.choice(CORREDORES)
        plant = f"P{i + 1:03d}"
        nombre = f"CEDIS {ciudad}" if es_cedis else f"Sanimex {ciudad}"
        sucursales.append({
            "plant": plant,
            "nombre": nombre,
            "organizacion": organizacion,
            "canal": canal,
            "corredor": corredor,
            "es_cedis": es_cedis,
        })

    conn.executemany(
        """INSERT INTO sucursales (plant, nombre, organizacion, canal, corredor, es_cedis)
           VALUES (:plant, :nombre, :organizacion, :canal, :corredor, :es_cedis)""",
        sucursales,
    )
    return sucursales


def build_proveedores_y_coberturas(conn: sqlite3.Connection, materiales: list[dict]) -> None:
    proveedores_rows = []
    coberturas_rows = []
    meses_objetivo_por_abc = {"A": 1.5, "B": 2.5, "C": 4.0}
    for mat in materiales:
        proveedores_rows.append({
            "material_id": mat["material_id"],
            "proveedor": random.choice(PROVEEDORES),
            "lead_time_dias": random.randint(7, 45),
            "moq_cajas": random.randint(20, 200),
            "cajas_por_pallet": random.choice([32, 40, 48, 54, 60]),
        })
        base = meses_objetivo_por_abc[mat["abc"]]
        coberturas_rows.append({
            "material_id": mat["material_id"],
            "meses_objetivo": round(base + random.uniform(-0.3, 0.3), 2),
        })

    conn.executemany(
        """INSERT INTO proveedores (material_id, proveedor, lead_time_dias, moq_cajas, cajas_por_pallet)
           VALUES (:material_id, :proveedor, :lead_time_dias, :moq_cajas, :cajas_por_pallet)""",
        proveedores_rows,
    )
    conn.executemany(
        """INSERT INTO coberturas_objetivo (material_id, meses_objetivo)
           VALUES (:material_id, :meses_objetivo)""",
        coberturas_rows,
    )


def build_ventas_e_inventarios(
    conn: sqlite3.Connection, materiales: list[dict], sucursales: list[dict], meses: list[str]
) -> None:
    abc_share = {"A": (60, 220), "B": (20, 90), "C": (5, 35)}  # rango de m2/pza base mensual
    ventas_rows = []
    inventarios_rows = []

    no_cedis = [s for s in sucursales if not s["es_cedis"]]

    for mat in materiales:
        # Cada material se vende en un subconjunto de sucursales (40%-75%)
        n_activas = max(3, int(len(no_cedis) * random.uniform(0.4, 0.75)))
        plants_activos = random.sample(no_cedis, n_activas)

        lo, hi = abc_share[mat["abc"]]
        for suc in plants_activos:
            base_demand = random.uniform(lo, hi)
            # Sucursales eCommerce/Outlet/Remates tienden a mover volúmenes distintos
            canal_factor = {
                "Menudeo": 1.0, "Mayoreo": 1.8, "eCommerce": 0.6,
                "Outlet": 0.8, "Remates": 1.3,
            }[suc["canal"]]
            base_demand *= canal_factor

            serie_m2 = []
            for idx, anio_mes in enumerate(meses):
                mes_num = int(anio_mes.split("-")[1])
                # Estacionalidad: pico primavera-verano (abr-sep), baja en dic-ene
                estacional = 1 + 0.25 * math.sin((mes_num - 3) / 12 * 2 * math.pi)
                ruido = random.uniform(0.75, 1.25)
                # Ocasionalmente un mes sin venta (quiebre / material descontinuado temporalmente)
                quiebre = 0 if random.random() < 0.04 else 1
                cantidad = max(0.0, base_demand * estacional * ruido * quiebre)
                cantidad = round(cantidad, 2)
                importe = round(cantidad * mat["precio_venta"], 2)
                serie_m2.append(cantidad)
                ventas_rows.append({
                    "material_id": mat["material_id"],
                    "plant": suc["plant"],
                    "canal": suc["canal"],
                    "anio_mes": anio_mes,
                    "cantidad_m2": cantidad,
                    "importe": importe,
                })

            # Inventario actual: basado en demanda promedio de los últimos 3 meses
            demanda_prom = sum(serie_m2[-3:]) / 3 if serie_m2 else base_demand
            # 8% de los pares quedan en quiebre de stock para alimentar alertas urgentes
            en_quiebre = random.random() < 0.08
            cobertura_actual = 0.0 if en_quiebre else random.uniform(0.3, 3.5)
            disponible = 0.0 if en_quiebre else round(demanda_prom * cobertura_actual, 2)
            transito = round(demanda_prom * random.uniform(0, 1.2), 2) if random.random() < 0.5 else 0.0
            comprometido = round(disponible * random.uniform(0, 0.25), 2)
            pedidos_abiertos = round(demanda_prom * random.uniform(0, 0.8), 2) if random.random() < 0.4 else 0.0
            cajas_remanentes = random.randint(0, 15)

            inventarios_rows.append({
                "material_id": mat["material_id"],
                "plant": suc["plant"],
                "disponible": disponible,
                "transito": transito,
                "comprometido": comprometido,
                "pedidos_abiertos": pedidos_abiertos,
                "cajas_remanentes": cajas_remanentes,
            })

    conn.executemany(
        """INSERT INTO ventas_mensuales (material_id, plant, canal, anio_mes, cantidad_m2, importe)
           VALUES (:material_id, :plant, :canal, :anio_mes, :cantidad_m2, :importe)""",
        ventas_rows,
    )
    conn.executemany(
        """INSERT INTO inventarios
           (material_id, plant, disponible, transito, comprometido, pedidos_abiertos, cajas_remanentes)
           VALUES (:material_id, :plant, :disponible, :transito, :comprometido, :pedidos_abiertos, :cajas_remanentes)""",
        inventarios_rows,
    )
    print(f"  ventas_mensuales: {len(ventas_rows):,} filas")
    print(f"  inventarios: {len(inventarios_rows):,} filas")


def generate(db_path: Path, force: bool = False) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if db_path.exists() and not force:
        print(f"[seed] {db_path} ya existe. Usa --force para recrear.")
        return

    if db_path.exists() and force:
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)

    print(f"[seed] Generando dataset sintético en {db_path} ...")
    materiales = build_materiales(conn)
    print(f"  materiales: {len(materiales):,} filas")
    sucursales = build_sucursales(conn)
    print(f"  sucursales: {len(sucursales):,} filas")
    build_proveedores_y_coberturas(conn, materiales)
    print(f"  proveedores + coberturas_objetivo: {len(materiales):,} filas c/u")

    meses = month_range(24, end_year=2026, end_month=8)
    build_ventas_e_inventarios(conn, materiales, sucursales, meses)

    conn.commit()
    conn.close()
    print("[seed] Listo.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera el dataset sintético de ComprasAI Sanimex")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Ruta del archivo SQLite a generar")
    parser.add_argument("--force", action="store_true", help="Recrea el archivo aunque ya exista")
    args = parser.parse_args()
    generate(Path(args.db), force=args.force)


if __name__ == "__main__":
    main()
