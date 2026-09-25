#!/usr/bin/env python3
"""
extract_v2_stock_real.py — Paso v2 del dataset ComprasAI Sanimex: reemplaza el
inventario SINTETICO de v1 por el REAL de SAP CAR PRD (HANA).

Reconstruye la semántica del release data-real-car-v2 (el script original no
quedó en git):
    disponible       = InventoryVisibilityStockQuantities.UnresUseStockQuantity
    transito         = InTransitStockQuantity + InTransferStockQuantity
    comprometido     = InventoryVisibilityWithSalesOrderReservedQuantity.ReservedQuantity
    pedidos_abiertos = EKPO (se conserva el de v1, ya era real)
    cajas_remanentes = round((disponible % m2_por_caja) / m2_por_caja)  (misma fórmula
                       que v1; verificada 177,172/177,172 contra v7)
Solo pares material x centro existentes en materiales/sucursales; negativos -> 0;
se descartan filas con las cuatro cantidades en 0 (igual que v7).

Credenciales SOLO por entorno: SANIMEX_CAR_HOST / _PORT / _USER / _PASS.

Uso:
    python3 extract_v2_stock_real.py --base comprasai_v1.db --out comprasai_v2.db
"""
import argparse
import os
import shutil
import sqlite3
import sys
import time

MANDT = "110"
CV = '"_SYS_BIC"."sap.is.retail.car_s4h/{}"'
Q_STOCK = f"""
    SELECT "Article", "Location", SUM("UnresUseStockQuantity"),
           SUM("InTransitStockQuantity") + SUM("InTransferStockQuantity")
    FROM {CV.format("InventoryVisibilityStockQuantities")}
    WHERE "SAPClient" = ?
    GROUP BY "Article", "Location"
    HAVING SUM("UnresUseStockQuantity") > 0
        OR SUM("InTransitStockQuantity") + SUM("InTransferStockQuantity") > 0
"""
Q_RESERVADO = f"""
    SELECT "Article", "Location", SUM("ReservedQuantity")
    FROM {CV.format("InventoryVisibilityWithSalesOrderReservedQuantity")}
    WHERE "SAPClient" = ?
    GROUP BY "Article", "Location"
    HAVING SUM("ReservedQuantity") <> 0
"""


def hana():
    from hdbcli import dbapi
    faltan = [k for k in ("SANIMEX_CAR_HOST", "SANIMEX_CAR_PORT", "SANIMEX_CAR_USER", "SANIMEX_CAR_PASS")
              if not os.environ.get(k)]
    if faltan:
        sys.exit(f"ERROR: faltan variables de entorno: {', '.join(faltan)}")
    return dbapi.connect(address=os.environ["SANIMEX_CAR_HOST"], port=int(os.environ["SANIMEX_CAR_PORT"]),
                         user=os.environ["SANIMEX_CAR_USER"], password=os.environ["SANIMEX_CAR_PASS"])


def leer_hana():
    """(mat, plant) -> [disponible, transito, comprometido] desde los CVs de visibilidad."""
    conn = hana()
    cur = conn.cursor()
    inv = {}
    t0 = time.time()
    cur.execute(Q_STOCK, (MANDT,))
    for mat, plant, disp, trans in cur.fetchall():
        inv[(mat.strip(), plant.strip())] = [float(disp or 0), float(trans or 0), 0.0]
    cur.execute(Q_RESERVADO, (MANDT,))
    for mat, plant, res in cur.fetchall():
        inv.setdefault((mat.strip(), plant.strip()), [0.0, 0.0, 0.0])[2] = float(res or 0)
    conn.close()
    print(f"  HANA: {len(inv):,} pares material x centro ({time.time() - t0:.1f}s)")
    return inv


def construir_filas(scur, hana_inv):
    materiales = dict(scur.execute("SELECT material_id, m2_por_caja FROM materiales"))
    plantas = {r[0] for r in scur.execute("SELECT plant FROM sucursales")}
    pedidos = {(m, p): po for m, p, po in scur.execute(
        "SELECT material_id, plant, pedidos_abiertos FROM inventarios WHERE pedidos_abiertos > 0")}
    filas = []
    for key in set(hana_inv) | set(pedidos):
        mat, plant = key
        if mat not in materiales or plant not in plantas:
            continue
        disp, trans, comp = (max(0.0, round(v, 3)) for v in hana_inv.get(key, (0.0, 0.0, 0.0)))
        po = round(pedidos.get(key, 0.0), 2)
        if disp == 0 and trans == 0 and comp == 0 and po == 0:
            continue
        m2caja = materiales[mat] or 1.0
        cajas = int(round((disp % m2caja) / m2caja))
        filas.append((mat, plant, disp, trans, comp, po, cajas))
    return filas


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--base", required=True, help="SQLite v1 (entrada, no se modifica)")
    ap.add_argument("--out", required=True, help="SQLite v2 (salida)")
    a = ap.parse_args()
    shutil.copyfile(a.base, a.out)
    print("=== v2: inventario real (InventoryVisibility) ===")
    hana_inv = leer_hana()
    db = sqlite3.connect(a.out)
    scur = db.cursor()
    filas = construir_filas(scur, hana_inv)
    if not filas:
        sys.exit("ERROR: 0 filas de inventario; no se sobrescribe")
    scur.execute("DELETE FROM inventarios")
    scur.executemany(
        "INSERT INTO inventarios(material_id,plant,disponible,transito,comprometido,pedidos_abiertos,cajas_remanentes)"
        " VALUES (?,?,?,?,?,?,?)", filas)
    db.commit()
    tot = scur.execute("SELECT COUNT(*), SUM(disponible>0), SUM(transito>0), SUM(comprometido>0),"
                       " SUM(pedidos_abiertos>0) FROM inventarios").fetchone()
    print(f"  inventarios: {tot[0]:,} filas | disp>0 {tot[1]:,} | transito>0 {tot[2]:,}"
          f" | comprometido>0 {tot[3]:,} | pedidos>0 {tot[4]:,}")
    db.execute("VACUUM")
    db.close()


if __name__ == "__main__":
    main()
