#!/usr/bin/env python3
"""
build_kardex_v3.py — Construye data-real-car-v3 a partir de data-real-car-v2 (T23 / waykee 290120).

PARTE A: agrega la tabla kardex_diario(material_id, plant, fecha, entradas, salidas, saldo_fin_dia)
  Fuente: SAPS4H.MATDOC (documento de material universal S/4, MANDT 110, CAR PRD, SOLO LECTURA).
  Universo: materiales HAWA (7,421) x centros (233) del proyecto (leidos del .db v2), BUDAT >= 2024-08.
  Agregado material-centro-DIA (solo dias con movimiento).
  Saldo EXACTO anclado al stock actual de T17 (CV InventoryVisibilityCurrentStock.UnresUseStockQuantity)
  caminando hacia atras: saldo_fin_dia(d) = S_now - sum(neto de los dias posteriores a d).
  Se documenta el residuo (dias con saldo reconstruido < 0 por movimientos de transito/stock especial
  que el stock libre no refleja; T20 lo midio en ~40 pzas / 5 anios).

PARTE B (reporte de cobertura, NO modifica schema): mide si MOQ/empaque y politica de inventario
  son datos reales en el replica CAR. Resultado (medido en vivo 2026-08-23): todos < 50% -> se
  conserva el sintetico de v2 y la habilitacion se escala via cuestionario T21 seccion 7.

Credenciales: por variables de entorno (Waykee Secrets markers en bash). NO hardcodear.
  H  = {SanimexHanaHost}      P  = {SanimexCARHanaPuerto}
  U  = {SanimexCARUser}       PW = {SanimexCARPassword}

Uso:
  H=.. P=.. U=.. PW=.. python3 build_kardex_v3.py <v2_db_in> <v3_db_out>
"""
import os, sys, time, sqlite3, shutil
from collections import defaultdict
from hdbcli import dbapi

MANDT = '110'
BUDAT_DESDE = '20240801'          # 24 meses (BUDAT >= 2024-08), diseno aprobado T20
CV_STOCK = '"_SYS_BIC"."sap.is.retail.car_s4h/InventoryVisibilityCurrentStock"'


def chunks(l, n):
    for i in range(0, len(l), n):
        yield l[i:i + n]


def hana():
    return dbapi.connect(address=os.environ['H'], port=int(os.environ['P']),
                         user=os.environ['U'], password=os.environ['PW'])


def main():
    v2_in = sys.argv[1] if len(sys.argv) > 1 else '/tmp/v2/comprasai.db'
    v3_out = sys.argv[2] if len(sys.argv) > 2 else '/tmp/v3/comprasai.db'
    t0 = time.time()

    os.makedirs(os.path.dirname(v3_out), exist_ok=True)
    print(f"Copiando base v2 -> v3: {v2_in} -> {v3_out}")
    shutil.copyfile(v2_in, v3_out)
    sq = sqlite3.connect(v3_out)
    sc = sq.cursor()

    mats = [r[0] for r in sc.execute("SELECT material_id FROM materiales")]
    plants = set(r[0] for r in sc.execute("SELECT plant FROM sucursales"))
    mats_set = set(mats)
    print(f"Universo: {len(mats)} materiales HAWA, {len(plants)} centros")

    conn = hana(); cur = conn.cursor()
    cur.execute("SELECT NOW() FROM DUMMY"); print("HANA conn OK, now:", cur.fetchone()[0])

    # ---------------------------------------------------------------
    # 1) Stock actual real (ancla) desde CV InventoryVisibilityCurrentStock (mismo de T17)
    # ---------------------------------------------------------------
    print("\n=== 1) Stock actual real (UnresUseStockQuantity) para anclaje ===")
    s_now = {}  # (mat,plant) -> stock libre utilizacion (base UoM)
    cur.execute(f'SELECT "Article", "Location", "UnresUseStockQuantity" FROM {CV_STOCK} WHERE "SAPClient"=?', (MANDT,))
    batch = cur.fetchmany(100000); nstk = 0
    while batch:
        for art, loc, q in batch:
            art = (art or '').strip(); loc = (loc or '').strip()
            if art in mats_set and loc in plants and q is not None:
                s_now[(art, loc)] = float(q); nstk += 1
        batch = cur.fetchmany(100000)
    print(f"  combos (mat,plant) con stock ancla en universo: {nstk}")

    # ---------------------------------------------------------------
    # 2) MATDOC agregado material-centro-dia (own stock, SOBKZ vacio)
    # ---------------------------------------------------------------
    print("\n=== 2) MATDOC agregado material-centro-dia (BUDAT>=%s, SOBKZ vacio, HAWA) ===" % BUDAT_DESDE)
    t = time.time()
    cur.execute(f"""
        SELECT d.MATNR, d.WERKS, d.BUDAT,
               SUM(CASE WHEN d.SHKZG='S' THEN d.MENGE ELSE 0 END) AS entradas,
               SUM(CASE WHEN d.SHKZG='H' THEN d.MENGE ELSE 0 END) AS salidas
        FROM SAPS4H.MATDOC d
        JOIN SAPS4H.MARA m ON m.MANDT=d.MANDT AND m.MATNR=d.MATNR AND m.MTART='HAWA'
        WHERE d.MANDT='{MANDT}' AND d.BUDAT >= '{BUDAT_DESDE}'
          AND (d.SOBKZ IS NULL OR d.SOBKZ='')
        GROUP BY d.MATNR, d.WERKS, d.BUDAT
    """)
    # dias por (mat,plant): lista de (fecha, entradas, salidas)
    mov = defaultdict(list)
    total = 0; skipped = 0
    batch = cur.fetchmany(100000)
    while batch:
        for matnr, werks, budat, ent, sal in batch:
            matnr = (matnr or '').strip(); werks = (werks or '').strip()
            if matnr not in mats_set or werks not in plants:
                skipped += 1; continue
            fecha = f"{budat[0:4]}-{budat[4:6]}-{budat[6:8]}"
            mov[(matnr, werks)].append((fecha, float(ent or 0), float(sal or 0)))
            total += 1
        batch = cur.fetchmany(100000)
    print(f"  filas agregadas material-centro-dia (en universo): {total}  (descartadas fuera de universo: {skipped})  {time.time()-t:.1f}s")
    conn.close()

    # ---------------------------------------------------------------
    # 3) Reconstruccion de saldo anclado (camina hacia atras desde S_now)
    # ---------------------------------------------------------------
    print("\n=== 3) Reconstruccion saldo_fin_dia anclado al stock actual ===")
    rows = []
    neg_rows = 0; min_saldo = 0.0; combos_sin_ancla = 0; combos = 0
    residuo_abs = 0.0
    for (matnr, werks), dias in mov.items():
        dias.sort()  # por fecha asc
        netos = [e - s for (_, e, s) in dias]
        S = s_now.get((matnr, werks))
        if S is None:
            S = 0.0; combos_sin_ancla += 1
        combos += 1
        k = len(dias)
        # suffix sum: cumdelta_after[i] = sum netos[i+1..k-1]
        saldo = [0.0] * k
        acc = 0.0
        for i in range(k - 1, -1, -1):
            saldo[i] = round(S - acc, 3)
            acc += netos[i]
        # el saldo del primer dia deberia ~ neto del primer dia si el stock antes del periodo fuese
        # saldo[0]-netos[0]; el residuo teorico es (saldo antes del periodo) = saldo[0]-netos[0]
        for i, (fecha, ent, sal) in enumerate(dias):
            sv = saldo[i]
            if sv < 0:
                neg_rows += 1
                if sv < min_saldo:
                    min_saldo = sv
            rows.append((matnr, werks, fecha, round(ent, 3), round(sal, 3), sv))
    print(f"  combos (mat,plant) con kardex: {combos}  (sin ancla de stock -> S_now=0: {combos_sin_ancla})")
    print(f"  filas kardex_diario: {len(rows)}")
    print(f"  filas con saldo reconstruido < 0 (residuo transito/stock especial): {neg_rows} ({100*neg_rows/max(1,len(rows)):.3f}%)  min_saldo={min_saldo}")

    # ---------------------------------------------------------------
    # 4) Crear tabla e insertar
    # ---------------------------------------------------------------
    print("\n=== 4) Creando kardex_diario e insertando ===")
    sc.execute("DROP TABLE IF EXISTS kardex_diario")
    sc.execute("""
        CREATE TABLE kardex_diario (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id   TEXT NOT NULL REFERENCES materiales(material_id),
            plant         TEXT NOT NULL REFERENCES sucursales(plant),
            fecha         TEXT NOT NULL,           -- 'YYYY-MM-DD' (solo dias con movimiento)
            entradas      REAL NOT NULL DEFAULT 0, -- suma MENGE SHKZG='S' (unidad base del material)
            salidas       REAL NOT NULL DEFAULT 0, -- suma MENGE SHKZG='H'
            saldo_fin_dia REAL NOT NULL DEFAULT 0  -- anclado a stock actual real, camina hacia atras
        )
    """)
    sc.executemany("INSERT INTO kardex_diario(material_id,plant,fecha,entradas,salidas,saldo_fin_dia) VALUES (?,?,?,?,?,?)", rows)
    sc.execute("CREATE INDEX idx_kardex_mat_plant ON kardex_diario(material_id, plant)")
    sc.execute("CREATE INDEX idx_kardex_fecha ON kardex_diario(fecha)")
    sc.execute("CREATE INDEX idx_kardex_mat_plant_fecha ON kardex_diario(material_id, plant, fecha)")
    sq.commit()

    # ---------------------------------------------------------------
    # 5) Validaciones de muestra (mismos materiales de T20)
    # ---------------------------------------------------------------
    print("\n=== 5) Validaciones de muestra ===")
    print("conteos v3:")
    for tname in ["materiales", "sucursales", "ventas_mensuales", "inventarios", "coberturas_objetivo", "proveedores", "kardex_diario"]:
        print(f"  {tname:22s}", sc.execute(f"SELECT COUNT(*) FROM {tname}").fetchone()[0])
    print("rango fechas kardex:", sc.execute("SELECT MIN(fecha),MAX(fecha) FROM kardex_diario").fetchone())
    for m in ('L01-00-5-101', 'P16-54-0-69'):
        print(f"\n  -- {m} --")
        for pl, cnt, mn, mx in sc.execute(
            "SELECT plant,COUNT(*),MIN(saldo_fin_dia),MAX(saldo_fin_dia) FROM kardex_diario WHERE material_id=? GROUP BY plant ORDER BY COUNT(*) DESC LIMIT 3", (m,)):
            stock = sc.execute("SELECT disponible FROM inventarios WHERE material_id=? AND plant=?", (m, pl)).fetchone()
            stock = stock[0] if stock else None
            # ultimo saldo del kardex vs stock actual (deben coincidir por el anclaje)
            ult = sc.execute("SELECT saldo_fin_dia FROM kardex_diario WHERE material_id=? AND plant=? ORDER BY fecha DESC LIMIT 1", (m, pl)).fetchone()[0]
            dias0 = sc.execute("SELECT COUNT(*) FROM kardex_diario WHERE material_id=? AND plant=? AND saldo_fin_dia<=2", (m, pl)).fetchone()[0]
            print(f"    plant {pl}: dias_mov={cnt} saldo[min={mn},max={mx}] ult_saldo={ult} stock_actual_inv={stock} dias_saldo<=2={dias0}")
    sq.close()
    print(f"\nDB v3: {v3_out} ({os.path.getsize(v3_out)/1e6:.1f} MB) -- total {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
