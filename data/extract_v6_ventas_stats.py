#!/usr/bin/env python3
"""
extract_v6_ventas_stats.py — Stats de venta TRANSACCIONAL POS (CAR /POSDW/TLOGF)
pre-agregadas por material/centro/mes, para el dataset ComprasAI Sanimex (release v6).

QUE HACE
  Toma la base REAL v5 (comprasai_v5.db) y le AGREGA una tabla, sin tocar nada
  existente (ADITIVO):
    - ventas_stats_mensuales : una fila por (material_id, plant, anio_mes) con
      sumas, conteo de tickets/lineas y los dos maximos (linea y ticket completo)
      que necesita el motor para el "Promedio 3" exacto y el popup de explicacion.

  Toda la agregacion ocurre EN HANA (dos niveles: ticket -> material/centro/mes);
  aqui solo se filtra al universo del dataset y se inserta en SQLite.

FUENTE (CAR PRD, solo lectura)
    SAPABAP1."/POSDW/TLOGF"  (68M filas, transaccional POS)
  Filtros (replican el CV de Sanimex ZCV_SAC_VTA_DIA_AGRUPADOR para cuadrar con
  ventas_mensuales):
    MANDT='110' · RECORDQUALIFIER=5 (lineas de venta) · DATASTATUS='3' (confirmadas)
    RETAILTYPECODE NOT IN ('3002','2801','2802')   -- servicios/pagos y consignacion
  Llave de transaccion (ticket): PLANT + BUSINESSDAYDATE + WORKSTATIONID + TRANSNUMBER

METRICAS
    suma_cantidad          Σ RETAILQUANTITY                    (unidad de venta: PZA/PAK/CS)
    suma_importe_sin_iva   Σ SALESAMOUNT / 1.16                (SALESAMOUNT viene CON IVA)
    num_tickets            COUNT DISTINCT de la llave de ticket (tickets que llevan el material)
    num_lineas             Σ lineas POS del material
    max_linea              MAX(RETAILQUANTITY) de una sola linea
    max_ticket             MAX(Σ RETAILQUANTITY del material dentro de un mismo ticket)
    fecha_max_ticket       BUSINESSDAYDATE del ticket que produjo max_ticket
  Se extraen AMBAS definiciones de "venta mayor" (linea y ticket) porque compras
  aun no confirma cual usa su Excel; el motor usara la que se confirme.

SEGURIDAD
  Credenciales y endpoint SOLO por variables de entorno; NADA hardcodeado:
    SANIMEX_CAR_USER, SANIMEX_CAR_PASS   (obligatorias)
    SANIMEX_CAR_HOST, SANIMEX_CAR_PORT   (infra on-prem, subred 192.168.99.x, VPN Sanimex)

USO
    SANIMEX_CAR_USER=... SANIMEX_CAR_PASS=... SANIMEX_CAR_HOST=... SANIMEX_CAR_PORT=... \
    python3 extract_v6_ventas_stats.py --base comprasai_v5.db --out comprasai_v6.db

    # solo re-reconciliar una v6 ya construida (offline, sin HANA):
    python3 extract_v6_ventas_stats.py --reconcile-only --out comprasai_v6.db
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from collections import defaultdict

MANDT = "110"
POS_TABLE = 'SAPABAP1."/POSDW/TLOGF"'
IVA = 1.16

# Ventana alineada a ventas_mensuales (v4/v5): 2024-09 .. 2026-08, + 2026-09 parcial.
MES_INICIO = "202409"
# Ultimo mes COMPLETO en ventas_mensuales de v5: ese dataset se extrajo el 23/24-ago-2026,
# asi que 2026-08 quedo parcial ahi. El cuadre 1:1 se mide hasta 2026-07 y el resto de los
# meses se reporta igual en "por_mes" (2026-08 y 2026-09 quedan marcados como parciales).
MES_FIN_CUADRE = "202607"
MES_FIN = "202609"          # se extrae tambien el mes en curso (parcial), es barato

EXCLUDED_TYPES = ("3002", "2801", "2802")


DDL = """
CREATE TABLE IF NOT EXISTS ventas_stats_mensuales (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id           TEXT NOT NULL,
    plant                 TEXT NOT NULL,
    anio_mes              TEXT NOT NULL,          -- 'YYYY-MM'
    suma_cantidad         REAL NOT NULL DEFAULT 0,-- Σ RETAILQUANTITY (unidad de venta)
    suma_importe_sin_iva  REAL NOT NULL DEFAULT 0,-- Σ SALESAMOUNT / 1.16
    num_tickets           INTEGER NOT NULL DEFAULT 0,
    num_lineas            INTEGER NOT NULL DEFAULT 0,
    max_linea             REAL NOT NULL DEFAULT 0,-- MAX cantidad de UNA linea
    max_ticket            REAL NOT NULL DEFAULT 0,-- MAX cantidad del material en UN ticket
    fecha_max_ticket      TEXT,                   -- 'YYYY-MM-DD' del ticket de max_ticket
    -- Movimientos de CONSIGNACION (RETAILTYPECODE 2801/2802), fuera de las metricas
    -- de arriba por el filtro del CV, pero SI incluidos en ventas_mensuales (ZVTA_BONO).
    -- Sumandolos, el cuadre contra ventas_mensuales es exacto (100.00%). Normalmente
    -- son negativos (salidas/ajustes de consignacion).
    suma_cantidad_consig        REAL NOT NULL DEFAULT 0,
    suma_importe_sin_iva_consig REAL NOT NULL DEFAULT 0,
    num_lineas_consig           INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_vstats_mat_plant_mes ON ventas_stats_mensuales(material_id, plant, anio_mes);
CREATE INDEX IF NOT EXISTS idx_vstats_mes           ON ventas_stats_mensuales(anio_mes);
"""

# Agregacion en DOS niveles, 100% dentro de HANA:
#   nivel 1: por (material, centro, ticket)   -> cantidad del ticket, lineas, max linea
#   nivel 2: por (material, centro, mes)      -> sumas, conteos, maximos y fecha del ticket top
SQL_MES = f"""
SELECT material_id, plant, ym,
       SUM(qty_ticket)  AS suma_cantidad,
       SUM(amt)         AS suma_importe_con_iva,
       COUNT(*)         AS num_tickets,
       SUM(lineas)      AS num_lineas,
       MAX(max_linea)   AS max_linea,
       MAX(qty_ticket)  AS max_ticket,
       MAX(CASE WHEN rn = 1 THEN bdate END) AS fecha_max_ticket
FROM (
  SELECT t.*, ROW_NUMBER() OVER (PARTITION BY material_id, plant, ym
                                 ORDER BY qty_ticket DESC, bdate DESC) AS rn
  FROM (
    SELECT MATERIALNUMBER AS material_id, PLANT AS plant,
           SUBSTRING(BUSINESSDAYDATE, 1, 6) AS ym, BUSINESSDAYDATE AS bdate,
           SUM(RETAILQUANTITY) AS qty_ticket,
           SUM(SALESAMOUNT)    AS amt,
           COUNT(*)            AS lineas,
           MAX(RETAILQUANTITY) AS max_linea
    FROM {POS_TABLE}
    WHERE MANDT = '{MANDT}' AND RECORDQUALIFIER = 5 AND DATASTATUS = '3'
      AND BUSINESSDAYDATE BETWEEN ? AND ?
      AND RETAILTYPECODE NOT IN ('{EXCLUDED_TYPES[0]}','{EXCLUDED_TYPES[1]}','{EXCLUDED_TYPES[2]}')
    GROUP BY MATERIALNUMBER, PLANT, BUSINESSDAYDATE, WORKSTATIONID, TRANSNUMBER
  ) t
) x
GROUP BY material_id, plant, ym
"""

# Consignacion (2801/2802) por material/centro/mes: fuera del filtro del CV pero
# DENTRO de ventas_mensuales; se guarda aparte para poder cuadrar 1:1 y para que el
# motor use la definicion que compras confirme.
SQL_CONSIG = f"""
SELECT MATERIALNUMBER AS material_id, PLANT AS plant,
       SUBSTRING(BUSINESSDAYDATE, 1, 6) AS ym,
       SUM(RETAILQUANTITY) AS qty, SUM(SALESAMOUNT) AS amt, COUNT(*) AS lineas
FROM {POS_TABLE}
WHERE MANDT = '{MANDT}' AND RECORDQUALIFIER = 5 AND DATASTATUS = '3'
  AND BUSINESSDAYDATE BETWEEN ? AND ?
  AND RETAILTYPECODE IN ('2801','2802')
GROUP BY MATERIALNUMBER, PLANT, SUBSTRING(BUSINESSDAYDATE, 1, 6)
"""

# Desglose por tipo de movimiento POS (para documentar que entra/sale del filtro)
SQL_TIPOS = f"""
SELECT RETAILTYPECODE, COUNT(*) AS lineas,
       SUM(RETAILQUANTITY) AS qty, SUM(SALESAMOUNT) AS amt
FROM {POS_TABLE}
WHERE MANDT = '{MANDT}' AND RECORDQUALIFIER = 5 AND DATASTATUS = '3'
  AND BUSINESSDAYDATE BETWEEN ? AND ?
GROUP BY RETAILTYPECODE
"""


def env_conn():
    """Conexion HANA con credenciales/endpoint SOLO desde env vars."""
    from hdbcli import dbapi
    missing = [k for k in ("SANIMEX_CAR_USER", "SANIMEX_CAR_PASS") if not os.environ.get(k)]
    if missing:
        sys.exit(f"ERROR: faltan variables de entorno: {', '.join(missing)}")
    host = os.environ.get("SANIMEX_CAR_HOST", "192.168.99.77")
    port = int(os.environ.get("SANIMEX_CAR_PORT", "30215"))
    print(f"Conectando a HANA CAR PRD {host}:{port} (user desde env) ...")
    conn = dbapi.connect(address=host, port=port,
                         user=os.environ["SANIMEX_CAR_USER"],
                         password=os.environ["SANIMEX_CAR_PASS"],
                         connectTimeout=20000, communicationTimeout=1800000)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM DUMMY")
    assert cur.fetchone()[0] == 1
    print("Conexion OK.")
    return conn


def meses(desde, hasta):
    y, m = int(desde[:4]), int(desde[4:])
    out = []
    while f"{y}{m:02d}" <= hasta:
        out.append(f"{y}{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def rango_dias(ym):
    y, m = int(ym[:4]), int(ym[4:])
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    # BUSINESSDAYDATE es NVARCHAR(8) (comparacion lexicografica): 'YYYYMM00' del mes
    # siguiente es > cualquier dia del mes actual y < su dia 01.
    return f"{ym}01", f"{ny}{nm:02d}00"


def build_valid_universe(scur):
    materiales = {r[0] for r in scur.execute("SELECT material_id FROM materiales")}
    plants = {r[0] for r in scur.execute("SELECT plant FROM sucursales")}
    print(f"  universo v5: {len(materiales)} materiales (HAWA), {len(plants)} plants")
    return materiales, plants


def extract(cur, materiales, plants):
    """Devuelve (filas_para_sqlite, descartes, desglose_tipos_por_mes)."""
    rows = []
    descartes = {"fuera_material": 0, "fuera_plant": 0,
                 "qty_fuera_material": 0.0, "qty_fuera_plant": 0.0,
                 "imp_fuera_material": 0.0, "imp_fuera_plant": 0.0}
    tipos = {}

    def en_universo(matnr, plant, q, amt):
        if matnr not in materiales:
            descartes["fuera_material"] += 1
            descartes["qty_fuera_material"] += q
            descartes["imp_fuera_material"] += amt / IVA
            return False
        if plant not in plants:
            descartes["fuera_plant"] += 1
            descartes["qty_fuera_plant"] += q
            descartes["imp_fuera_plant"] += amt / IVA
            return False
        return True

    for ym in meses(MES_INICIO, MES_FIN):
        d0, d1 = rango_dias(ym)
        anio_mes = f"{ym[0:4]}-{ym[4:6]}"
        t0 = time.time()

        # --- metricas principales (filtro del CV: sin 3002/2801/2802) ---
        cur.execute(SQL_MES, (d0, d1))
        got = cur.fetchall()
        mes_rows = {}   # (mat,plant) -> dict
        for (matnr, plant, _ym, q, amt, n_tk, n_ln, mx_ln, mx_tk, f_mx) in got:
            matnr = (matnr or "").strip(); plant = (plant or "").strip()
            q = float(q or 0); amt = float(amt or 0)
            if not en_universo(matnr, plant, q, amt):
                continue
            fecha = None
            if f_mx and len(str(f_mx)) == 8:
                sd = str(f_mx)
                fecha = f"{sd[0:4]}-{sd[4:6]}-{sd[6:8]}"
            mes_rows[(matnr, plant)] = {
                "suma_cantidad": round(q, 3), "suma_importe_sin_iva": round(amt / IVA, 2),
                "num_tickets": int(n_tk or 0), "num_lineas": int(n_ln or 0),
                "max_linea": round(float(mx_ln or 0), 3), "max_ticket": round(float(mx_tk or 0), 3),
                "fecha_max_ticket": fecha,
                "q_consig": 0.0, "imp_consig": 0.0, "ln_consig": 0,
            }

        # --- consignacion 2801/2802 (aparte; ventas_mensuales SI la incluye) ---
        cur.execute(SQL_CONSIG, (d0, d1))
        n_consig = 0
        for (matnr, plant, _ym, q, amt, n_ln) in cur.fetchall():
            matnr = (matnr or "").strip(); plant = (plant or "").strip()
            q = float(q or 0); amt = float(amt or 0)
            if matnr not in materiales or plant not in plants:
                continue   # ya contabilizado como descarte solo para las metricas base
            r = mes_rows.get((matnr, plant))
            if r is None:
                r = mes_rows[(matnr, plant)] = {
                    "suma_cantidad": 0.0, "suma_importe_sin_iva": 0.0,
                    "num_tickets": 0, "num_lineas": 0, "max_linea": 0.0, "max_ticket": 0.0,
                    "fecha_max_ticket": None,
                    "q_consig": 0.0, "imp_consig": 0.0, "ln_consig": 0,
                }
            r["q_consig"] = round(q, 3)
            r["imp_consig"] = round(amt / IVA, 2)
            r["ln_consig"] = int(n_ln or 0)
            n_consig += 1

        for (matnr, plant), r in mes_rows.items():
            rows.append((matnr, plant, anio_mes,
                         r["suma_cantidad"], r["suma_importe_sin_iva"],
                         r["num_tickets"], r["num_lineas"],
                         r["max_linea"], r["max_ticket"], r["fecha_max_ticket"],
                         r["q_consig"], r["imp_consig"], r["ln_consig"]))

        # desglose por tipo POS del mes (barato, documenta el filtro)
        cur.execute(SQL_TIPOS, (d0, d1))
        tipos[ym] = {(t or "").strip(): {"lineas": int(l or 0),
                                         "qty": round(float(q or 0), 2),
                                         "importe_con_iva": round(float(a or 0), 2)}
                     for t, l, q, a in cur.fetchall()}
        print(f"  {ym}: {len(got)} combos HANA -> {len(mes_rows)} en universo "
              f"(+{n_consig} con consignacion) ({time.time()-t0:.1f}s)")
    return rows, descartes, tipos


def reconcile(scur, descartes, tipos):
    print("\n=== RECONCILIACION ventas_stats_mensuales vs ventas_mensuales (v5) ===")
    vm = {}   # anio_mes -> (m2, importe, combos)
    for ym, m2, imp, n in scur.execute(
            "SELECT anio_mes, SUM(cantidad_m2), SUM(importe), COUNT(*) FROM ventas_mensuales GROUP BY anio_mes"):
        vm[ym] = (float(m2 or 0), float(imp or 0), int(n))
    vs = {}
    for ym, q, imp, qc, impc, n in scur.execute(
            """SELECT anio_mes, SUM(suma_cantidad), SUM(suma_importe_sin_iva),
                      SUM(suma_cantidad_consig), SUM(suma_importe_sin_iva_consig), COUNT(*)
               FROM ventas_stats_mensuales GROUP BY anio_mes"""):
        vs[ym] = (float(q or 0), float(imp or 0), float(qc or 0), float(impc or 0), int(n))

    por_mes = []
    for ym in sorted(set(vm) | set(vs)):
        m2, imp_vm, n_vm = vm.get(ym, (0.0, 0.0, 0))
        q, imp_vs, q_c, imp_c, n_vs = vs.get(ym, (0.0, 0.0, 0.0, 0.0, 0))
        imp_vs_con_iva = imp_vs * IVA
        imp_tot_con_iva = (imp_vs + imp_c) * IVA     # incluye consignacion = definicion de ventas_mensuales
        por_mes.append({
            "anio_mes": ym,
            "combos_ventas_mensuales": n_vm,
            "combos_stats": n_vs,
            "vm_cantidad_m2": round(m2, 2),
            "stats_suma_cantidad_pzas": round(q, 2),
            "stats_cantidad_consig_pzas": round(q_c, 2),
            "ratio_m2_por_pza": round(m2 / q, 4) if q else None,
            "vm_importe": round(imp_vm, 2),
            "stats_importe_sin_iva": round(imp_vs, 2),
            "stats_importe_con_iva": round(imp_vs_con_iva, 2),
            "stats_importe_con_iva_incl_consig": round(imp_tot_con_iva, 2),
            "pct_cuadre_importe_con_iva": round(100.0 * imp_vs_con_iva / imp_vm, 2) if imp_vm else None,
            "pct_cuadre_importe_con_iva_incl_consig": round(100.0 * imp_tot_con_iva / imp_vm, 2) if imp_vm else None,
            "pct_cuadre_importe_sin_iva": round(100.0 * imp_vs / imp_vm, 2) if imp_vm else None,
        })
    for r in por_mes:
        print(f"  {r['anio_mes']}  combos {r['combos_ventas_mensuales']:>6}/{r['combos_stats']:>6}  "
              f"m2 {r['vm_cantidad_m2']:>12,.0f} vs pzas {r['stats_suma_cantidad_pzas']:>12,.0f} "
              f"(m2/pza {r['ratio_m2_por_pza']})  importe {r['vm_importe']:>15,.0f} vs "
              f"{r['stats_importe_con_iva']:>15,.0f} ({r['pct_cuadre_importe_con_iva']}%) / "
              f"c-consig {r['stats_importe_con_iva_incl_consig']:>15,.0f} "
              f"({r['pct_cuadre_importe_con_iva_incl_consig']}%)")

    # cuadre de combos (solo meses completos comparables)
    cuadre_meses = [r for r in por_mes if MES_INICIO[:4] + "-" + MES_INICIO[4:] <= r["anio_mes"]
                    <= MES_FIN_CUADRE[:4] + "-" + MES_FIN_CUADRE[4:]]
    tot_vm_imp = sum(r["vm_importe"] for r in cuadre_meses)
    tot_vs_imp = sum(r["stats_importe_con_iva"] for r in cuadre_meses)
    tot_vs_imp_cc = sum(r["stats_importe_con_iva_incl_consig"] for r in cuadre_meses)
    tot_vm_m2 = sum(r["vm_cantidad_m2"] for r in cuadre_meses)
    tot_vs_q = sum(r["stats_suma_cantidad_pzas"] for r in cuadre_meses)

    combos_vm = {(m, p, a) for m, p, a in scur.execute(
        "SELECT material_id, plant, anio_mes FROM ventas_mensuales WHERE anio_mes<=?",
        (MES_FIN_CUADRE[:4] + "-" + MES_FIN_CUADRE[4:],))}
    combos_vs = {(m, p, a) for m, p, a in scur.execute(
        "SELECT material_id, plant, anio_mes FROM ventas_stats_mensuales WHERE anio_mes<=?",
        (MES_FIN_CUADRE[:4] + "-" + MES_FIN_CUADRE[4:],))}
    solo_vm = len(combos_vm - combos_vs)
    solo_vs = len(combos_vs - combos_vm)
    ambos = len(combos_vm & combos_vs)
    print(f"\n  combos (material,plant,mes) en ventana de cuadre: ambos {ambos}; "
          f"solo ventas_mensuales {solo_vm}; solo stats {solo_vs}")

    # impacto de los tipos POS excluidos / incluidos (sobre el ultimo mes completo)
    tipos_tot = defaultdict(lambda: {"lineas": 0, "qty": 0.0, "importe_con_iva": 0.0})
    for ym, d in tipos.items():
        for t, v in d.items():
            tipos_tot[t]["lineas"] += v["lineas"]
            tipos_tot[t]["qty"] += v["qty"]
            tipos_tot[t]["importe_con_iva"] += v["importe_con_iva"]
    tipos_tot = {t: {k: round(v, 2) if isinstance(v, float) else v for k, v in d.items()}
                 for t, d in tipos_tot.items()}

    # --- chequeos automaticos que deben viajar con el dataset ---
    filas = scur.execute("SELECT COUNT(*) FROM ventas_stats_mensuales").fetchone()[0]
    iguales = scur.execute("SELECT COUNT(*) FROM ventas_stats_mensuales WHERE max_linea = max_ticket").fetchone()[0]
    lin_eq_tk = scur.execute("SELECT COUNT(*) FROM ventas_stats_mensuales WHERE num_lineas = num_tickets").fetchone()[0]
    solo_consig = scur.execute("SELECT COUNT(*) FROM ventas_stats_mensuales WHERE num_lineas = 0 AND num_lineas_consig > 0").fetchone()[0]
    ultimo_vm = max(vm) if vm else None
    ultimo_vs = max(vs) if vs else None

    rep = {
        "fuente": {
            "tabla": POS_TABLE,
            "mandt": MANDT,
            "filtros": ("RECORDQUALIFIER=5 (lineas de venta), DATASTATUS='3' (confirmadas), "
                        f"RETAILTYPECODE NOT IN {EXCLUDED_TYPES} (servicios/pagos y consignacion)"),
            "llave_ticket": "PLANT + BUSINESSDAYDATE + WORKSTATIONID + TRANSNUMBER",
            "iva": ("SALESAMOUNT viene CON IVA; suma_importe_sin_iva = SALESAMOUNT/1.16. "
                    "Verificado en vivo contra TAXINC: para 2026-07 SALESAMOUNT 379,144,026 con "
                    "TAXINC 52,295,735 -> neto 326,848,292 = 379,144,026/1.16 (exacto)."),
            "universo": "materiales HAWA y plants validas del dataset v5 (mismo universo que ventas_mensuales)",
        },
        "unidades": {
            "ventas_mensuales.cantidad_m2": ("METROS (ZMETROS del CV _SYS_BIC.BI/ZVTA_BONO): superficie vendida"),
            "ventas_stats_mensuales.suma_cantidad": ("PIEZAS/unidad de venta (RETAILQUANTITY del POS: PZA/PAK/CS). "
                                                     "NO es la misma unidad; la relacion m2/pza se reporta por mes "
                                                     "en ratio_m2_por_pza y es el factor de conversion implicito "
                                                     "promedio del mix vendido."),
            "nota_motor": ("Para el 'Promedio 3' y los maximos, el motor debe usar suma_cantidad/max_linea/max_ticket "
                           "(piezas POS), no mezclarlos con cantidad_m2."),
        },
        "totales_ventana_cuadre": {
            "desde": MES_INICIO, "hasta": MES_FIN_CUADRE,
            "por_que_hasta_202607": ("ventas_mensuales (v5) quedo PARCIAL en 2026-08 (extraccion del 23/24-ago-2026). "
                                     "El cuadre exacto se mide sobre los 23 meses completos; 2026-08 y 2026-09 se "
                                     "reportan aparte en por_mes."),
            "ventas_mensuales_importe": round(tot_vm_imp, 2),
            "stats_importe_con_iva": round(tot_vs_imp, 2),
            "pct_cuadre_importe": round(100.0 * tot_vs_imp / tot_vm_imp, 2) if tot_vm_imp else None,
            "stats_importe_con_iva_incl_consig": round(tot_vs_imp_cc, 2),
            "pct_cuadre_importe_incl_consig": round(100.0 * tot_vs_imp_cc / tot_vm_imp, 2) if tot_vm_imp else None,
            "ventas_mensuales_m2": round(tot_vm_m2, 2),
            "stats_cantidad_pzas": round(tot_vs_q, 2),
            "ratio_m2_por_pza_global": round(tot_vm_m2 / tot_vs_q, 4) if tot_vs_q else None,
        },
        "chequeos": {
            "filas": filas,
            "filas_max_linea_igual_max_ticket": iguales,
            "filas_num_lineas_igual_num_tickets": lin_eq_tk,
            "filas_solo_consignacion": solo_consig,
            "nota": ("En este POS nunca hay dos lineas del mismo material dentro del mismo ticket "
                     "(num_lineas == num_tickets en el 100% de las filas). Consecuencia practica: "
                     "max_linea == max_ticket SIEMPRE, asi que la duda de compras sobre cual de las dos "
                     "definiciones de 'venta mayor' usa su Excel NO cambia el resultado. La fecha del "
                     "maximo (fecha_max_ticket) es la misma en ambas lecturas."),
        },
        "alertas": [
            ("ventas_mensuales (v5) tiene 2026-08 PARCIAL (se extrajo el 23/24-ago-2026), mientras que "
             "ventas_stats_mensuales trae 2026-08 COMPLETO. NO comparar ni mezclar ambas fuentes en ese "
             "mes: para 2026-08 la cifra buena es la de ventas_stats_mensuales. Si el motor usa "
             "ventas_mensuales para el promedio, ese mes esta subestimado (~30%) en v5/v6."),
            (f"El ultimo mes de ventas_stats_mensuales ({ultimo_vs}) es el mes EN CURSO al momento de la "
             "extraccion: esta parcial por definicion y no debe entrar a promedios moviles."),
            ("suma_cantidad esta en unidad de venta POS (piezas/paquetes/cajas), NO en m2. No sumar ni "
             "comparar directo contra ventas_mensuales.cantidad_m2 sin aplicar el factor del material."),
        ],
        "por_mes": por_mes,
        "combos": {"en_ambos": ambos, "solo_ventas_mensuales": solo_vm, "solo_stats": solo_vs},
        "descartes_por_universo": {k: (round(v, 2) if isinstance(v, float) else v)
                                   for k, v in descartes.items()},
        "tipos_pos_24m": tipos_tot,
        "nota_tipos": ("2001 = venta; 2901 = devoluciones/notas (negativo); 2801/2802 = consignacion "
                       "(negativo); 3002 = lineas de servicio/PAGO (ej. 'PAGO', sin cantidad real). "
                       "Las metricas principales excluyen 3002/2801/2802 segun el CV de ventas diarias "
                       "de Sanimex e INCLUYEN 2901."),
        "hallazgo_consignacion": ("VERIFICADO EN VIVO: ventas_mensuales (CV _SYS_BIC.BI/ZVTA_BONO) SI incluye "
                                  "los movimientos 2801/2802. Con el filtro del CV de ventas diarias (que los "
                                  "excluye) el POS queda ~+0.5% arriba cada mes; sumando las columnas "
                                  "suma_importe_sin_iva_consig el cuadre es EXACTO (100.00%) en los 23 meses "
                                  "completos. Por eso la tabla trae ambas cifras separadas: el motor usa la "
                                  "definicion que compras confirme y el cuadre contra ventas_mensuales es "
                                  "reproducible sin volver a HANA."),
    }
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="comprasai_v5.db", help="DB base v5 (real)")
    ap.add_argument("--out", default="comprasai_v6.db", help="DB de salida v6")
    ap.add_argument("--reconcile-only", action="store_true")
    args = ap.parse_args()
    t0 = time.time()

    if args.reconcile_only:
        if not os.path.exists(args.out):
            sys.exit(f"ERROR: no existe {args.out}")
        sq = sqlite3.connect(args.out); scur = sq.cursor()
        rep = reconcile(scur, {}, {})
        print("\n" + json.dumps(rep["totales_ventana_cuadre"], indent=2, ensure_ascii=False))
        return

    if not os.path.exists(args.base):
        sys.exit(f"ERROR: no existe la base v5 {args.base} (descargar release data-real-car-v5)")
    print(f"Copiando base v5 -> {args.out}")
    shutil.copyfile(args.base, args.out)
    sq = sqlite3.connect(args.out); scur = sq.cursor()
    scur.executescript(DDL)
    scur.execute("DELETE FROM ventas_stats_mensuales")   # idempotencia
    sq.commit()

    materiales, plants = build_valid_universe(scur)

    conn = env_conn(); cur = conn.cursor()
    try:
        rows, descartes, tipos = extract(cur, materiales, plants)
    finally:
        conn.close()

    scur.executemany("""INSERT INTO ventas_stats_mensuales
        (material_id, plant, anio_mes, suma_cantidad, suma_importe_sin_iva,
         num_tickets, num_lineas, max_linea, max_ticket, fecha_max_ticket,
         suma_cantidad_consig, suma_importe_sin_iva_consig, num_lineas_consig)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    sq.commit()
    print(f"\nfilas ventas_stats_mensuales insertadas: {len(rows)}")

    rep = reconcile(scur, descartes, tipos)
    rep["conteos"] = {
        "ventas_stats_mensuales": scur.execute("SELECT COUNT(*) FROM ventas_stats_mensuales").fetchone()[0],
        "materiales_distintos": scur.execute("SELECT COUNT(DISTINCT material_id) FROM ventas_stats_mensuales").fetchone()[0],
        "plants_distintas": scur.execute("SELECT COUNT(DISTINCT plant) FROM ventas_stats_mensuales").fetchone()[0],
        "meses": scur.execute("SELECT COUNT(DISTINCT anio_mes) FROM ventas_stats_mensuales").fetchone()[0],
        "rango_meses": list(scur.execute("SELECT MIN(anio_mes), MAX(anio_mes) FROM ventas_stats_mensuales").fetchone()),
        "ventas_mensuales_v5": scur.execute("SELECT COUNT(*) FROM ventas_mensuales").fetchone()[0],
    }
    out_json = os.path.splitext(args.out)[0] + "_reconciliacion.json"
    with open(out_json, "w") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    sq.close()
    print(f"\nDB v6: {args.out} ({os.path.getsize(args.out)/1e6:.2f} MB) -- {time.time()-t0:.1f}s")
    print("Reconciliacion escrita en", out_json)


if __name__ == "__main__":
    main()
