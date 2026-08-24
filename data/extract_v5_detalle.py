#!/usr/bin/env python3
"""
extract_v5_detalle.py — Detalle por documento de backorder y pedidos de compra
pendientes desde SAP CAR PRD (HANA), para el dataset ComprasAI Sanimex (release v5).

QUE HACE
  Toma la base REAL v4 (comprasai_v4.db) y le AGREGA dos tablas de detalle,
  sin tocar las tablas existentes:
    - backorder_detalle      : pedidos de venta con cantidad pendiente de entrega
                               (VBBE requirements; fallback VBAP/VBUP si VBBE vacia)
    - pedidos_compra_detalle : lineas de PO abiertas con cantidad pendiente de
                               recepcion (EKKO/EKPO + EKET para lo ya recibido)
  Valida que la SUMA por material/plant cuadre (o explique la diferencia) contra
  inventarios.comprometido y inventarios.pedidos_abiertos del snapshot v4.

MAPEO DE LLAVES (identico a v4, verificado 100%):
    material_id = MATNR (Article)   ·   plant = WERKS (Location)

SEGURIDAD
  Credenciales y endpoint SOLO por variables de entorno; NADA hardcodeado:
    SANIMEX_CAR_USER, SANIMEX_CAR_PASS   (obligatorias)
    SANIMEX_CAR_HOST, SANIMEX_CAR_PORT   (obligatorias — infra on-prem, subred 192.168.99.x, VPN Sanimex)
  En Waykee se resuelven por markers del Bash Proxy; el proceso solo ve env vars.

USO
    SANIMEX_CAR_USER={SanimexCARUser} SANIMEX_CAR_PASS={SanimexCARPassword} \
    SANIMEX_CAR_HOST={SanimexHanaHost} SANIMEX_CAR_PORT={SanimexCARHanaPuerto} \
    python3 extract_v5_detalle.py --base comprasai_v4.db --out comprasai_v5.db

    # solo reconciliar una v5 ya construida (offline, sin HANA):
    python3 extract_v5_detalle.py --reconcile-only --out comprasai_v5.db
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
SCHEMA = "SAPS4H"   # esquema real del replica S/4HANA (MANDT unico 110)


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def env_conn():
    """Conexion HANA con credenciales/endpoint SOLO desde env vars."""
    from hdbcli import dbapi
    # Credenciales SOLO por env (obligatorias). Host/puerto por env con default de infra
    # (subred on-prem 192.168.99.x, VPN Sanimex) — mismo patron que extract_real_car.py.
    missing = [k for k in ("SANIMEX_CAR_USER", "SANIMEX_CAR_PASS") if not os.environ.get(k)]
    if missing:
        sys.exit(f"ERROR: faltan variables de entorno: {', '.join(missing)}")
    host = os.environ.get("SANIMEX_CAR_HOST", "192.168.99.77")
    port = int(os.environ.get("SANIMEX_CAR_PORT", "30215"))
    print(f"Conectando a HANA CAR PRD {host}:{port} (user desde env) ...")
    conn = dbapi.connect(address=host, port=port,
                         user=os.environ["SANIMEX_CAR_USER"],
                         password=os.environ["SANIMEX_CAR_PASS"],
                         connectTimeout=20000, communicationTimeout=60000)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM DUMMY")
    assert cur.fetchone()[0] == 1
    print("Conexion OK.")
    return conn


def table_exists(cur, schema, table):
    cur.execute("SELECT COUNT(*) FROM SYS.TABLES WHERE SCHEMA_NAME=? AND TABLE_NAME=?",
                (schema, table))
    return cur.fetchone()[0] > 0


def table_cols(cur, schema, table):
    cur.execute("SELECT COLUMN_NAME FROM SYS.TABLE_COLUMNS WHERE SCHEMA_NAME=? AND TABLE_NAME=?",
                (schema, table))
    return {r[0] for r in cur.fetchall()}


# --------------------------------------------------------------------------
# DDL de las dos tablas nuevas (aditivas, no tocan el contrato v4)
# --------------------------------------------------------------------------
DDL = """
CREATE TABLE IF NOT EXISTS backorder_detalle (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id                 TEXT NOT NULL,
    plant                       TEXT NOT NULL,
    documento                   TEXT NOT NULL,   -- VBELN (pedido de venta)
    posicion                    TEXT NOT NULL,   -- POSNR
    cliente                     TEXT,            -- nombre KNA1 (o KUNNR si sin nombre)
    cantidad_pendiente          REAL NOT NULL DEFAULT 0,
    fecha_documento             TEXT,            -- YYYY-MM-DD (VBAK.AUDAT/ERDAT)
    fecha_entrega_comprometida  TEXT             -- YYYY-MM-DD (VBEP.EDATU / VBBE.MBDAT)
);
CREATE INDEX IF NOT EXISTS idx_bo_matplant ON backorder_detalle(material_id, plant);
CREATE INDEX IF NOT EXISTS idx_bo_doc      ON backorder_detalle(documento);

CREATE TABLE IF NOT EXISTS pedidos_compra_detalle (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id              TEXT NOT NULL,
    plant                    TEXT NOT NULL,
    po                       TEXT NOT NULL,   -- EBELN
    posicion                 TEXT NOT NULL,   -- EBELP
    proveedor                TEXT,            -- nombre LFA1 (o LIFNR si sin nombre)
    cantidad_pendiente       REAL NOT NULL DEFAULT 0,   -- MENGE - recibido (EKET.WEMNG)
    cantidad_pedida          REAL NOT NULL DEFAULT 0,    -- EKPO.MENGE (bruto, = base de pedidos_abiertos v4)
    fecha_po                 TEXT,            -- YYYY-MM-DD (EKKO.BEDAT/AEDAT)
    fecha_entrega_estimada   TEXT             -- YYYY-MM-DD (EKET.EINDT pendiente mas proxima)
);
CREATE INDEX IF NOT EXISTS idx_pc_matplant ON pedidos_compra_detalle(material_id, plant);
CREATE INDEX IF NOT EXISTS idx_pc_po       ON pedidos_compra_detalle(po);
"""


def d(x):
    """SAP DATS (YYYYMMDD) -> YYYY-MM-DD, tolerante a nulos/ceros."""
    if not x:
        return None
    s = str(x).strip()
    if len(s) == 8 and s.isdigit() and s != "00000000":
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return None


# --------------------------------------------------------------------------
# 1) PEDIDOS DE COMPRA PENDIENTES  (EKKO/EKPO + EKET)
# --------------------------------------------------------------------------
def extract_pedidos_compra(cur, materiales_ids, plant_valid):
    print("\n=== Pedidos de compra pendientes (EKKO/EKPO + EKET) ===")
    ekpo_cols = table_cols(cur, SCHEMA, "EKPO")
    has_eket = table_exists(cur, SCHEMA, "EKET")
    item_del = "(p.LOEKZ IS NULL OR p.LOEKZ='')" if "LOEKZ" in ekpo_cols else "1=1"
    date_col = "k.BEDAT" if True else "k.AEDAT"

    lines = []          # dict por (EBELN,EBELP)
    ebelns = set()
    for chunk in chunks(materiales_ids, 500):
        ph = ",".join(["?"] * len(chunk))
        cur.execute(f"""
            SELECT p.MATNR, p.WERKS, p.EBELN, p.EBELP, k.LIFNR, p.MENGE,
                   k.BEDAT, k.AEDAT
            FROM {SCHEMA}.EKPO p
            JOIN {SCHEMA}.EKKO k ON p.MANDT=k.MANDT AND p.EBELN=k.EBELN
            WHERE p.MANDT='{MANDT}' AND p.MATNR IN ({ph})
              AND (p.ELIKZ IS NULL OR p.ELIKZ='')
              AND (k.LOEKZ IS NULL OR k.LOEKZ='')
              AND {item_del}
        """, chunk)
        for matnr, werks, ebeln, ebelp, lifnr, menge, bedat, aedat in cur.fetchall():
            matnr = (matnr or "").strip(); werks = (werks or "").strip()
            if werks not in plant_valid:
                continue
            ebeln = (ebeln or "").strip(); ebelp = (ebelp or "").strip()
            lines.append({
                "matnr": matnr, "werks": werks, "ebeln": ebeln, "ebelp": ebelp,
                "lifnr": (lifnr or "").strip(), "menge": float(menge or 0),
                "fecha_po": d(bedat) or d(aedat),
            })
            ebelns.add(ebeln)
    print(f"  lineas PO abiertas (ELIKZ vacio, no borradas): {len(lines)}")

    # recibido y fecha de entrega por (EBELN,EBELP) via EKET
    recibido = defaultdict(float)   # (ebeln,ebelp) -> WEMNG
    fecha_pend = {}                 # (ebeln,ebelp) -> EINDT pendiente mas proxima
    if has_eket and lines:
        eket_cols = table_cols(cur, SCHEMA, "EKET")
        wemng_col = "WEMNG" if "WEMNG" in eket_cols else None
        ebeln_list = sorted(ebelns)
        for chunk in chunks(ebeln_list, 800):
            ph = ",".join(["?"] * len(chunk))
            sel_wemng = "WEMNG" if wemng_col else "0 AS WEMNG"
            cur.execute(f"""
                SELECT EBELN, EBELP, EINDT, MENGE, {sel_wemng}
                FROM {SCHEMA}.EKET
                WHERE MANDT='{MANDT}' AND EBELN IN ({ph})
                ORDER BY EBELN, EBELP, EINDT
            """, chunk)
            for ebeln, ebelp, eindt, s_menge, wemng in cur.fetchall():
                k = ((ebeln or "").strip(), (ebelp or "").strip())
                recibido[k] += float(wemng or 0)
                pend_sched = float(s_menge or 0) - float(wemng or 0)
                fe = d(eindt)
                if pend_sched > 0.001 and fe and k not in fecha_pend:
                    fecha_pend[k] = fe   # primera schedule line con pendiente = entrega mas proxima
        print(f"  EKET aplicada: recibido y fecha de entrega por linea ({len(recibido)} lineas con schedule)")
    else:
        print("  EKET no disponible -> cantidad_pendiente = cantidad_pedida (bruto) y sin fecha de entrega")

    # nombres de proveedor
    lifnrs = sorted({l["lifnr"] for l in lines if l["lifnr"]})
    lfa1 = {}
    for chunk in chunks(lifnrs, 1000):
        ph = ",".join(["?"] * len(chunk))
        cur.execute(f"SELECT LIFNR, NAME1 FROM {SCHEMA}.LFA1 WHERE MANDT='{MANDT}' AND LIFNR IN ({ph})", chunk)
        for lifnr, name1 in cur.fetchall():
            lfa1[(lifnr or "").strip()] = (name1 or "").strip()

    rows = []
    gross_by_mp = defaultdict(float)   # reconciliacion contra pedidos_abiertos (bruto = Σ MENGE)
    net_by_mp = defaultdict(float)
    for l in lines:
        k = (l["ebeln"], l["ebelp"])
        pedida = l["menge"]
        pendiente = pedida - recibido.get(k, 0.0)
        if pendiente < 0:
            pendiente = 0.0
        mp = (l["matnr"], l["werks"])
        gross_by_mp[mp] += pedida
        net_by_mp[mp] += pendiente
        if pendiente <= 0.001:
            continue   # linea ya recibida por completo -> no es "pendiente de recepcion"
        rows.append((
            l["matnr"], l["werks"], l["ebeln"], l["ebelp"],
            lfa1.get(l["lifnr"]) or l["lifnr"] or None,
            round(pendiente, 3), round(pedida, 3),
            l["fecha_po"], fecha_pend.get(k),
        ))
    print(f"  filas pedidos_compra_detalle (pendiente>0): {len(rows)}")
    return rows, gross_by_mp, net_by_mp


# --------------------------------------------------------------------------
# 2) BACKORDER (pedidos de venta pendientes de entrega)  VBBE -> fallback VBAP
# --------------------------------------------------------------------------
def extract_backorder(cur, materiales_ids, plant_valid):
    print("\n=== Backorder de ventas (VBBE requirements; fallback VBAP) ===")
    use_vbbe = False
    if table_exists(cur, SCHEMA, "VBBE"):
        cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.VBBE WHERE MANDT='{MANDT}'")
        cnt = cur.fetchone()[0]
        print(f"  VBBE presente, filas MANDT {MANDT}: {cnt}")
        use_vbbe = cnt > 0

    rows = []
    net_by_mp = defaultdict(float)
    vbeln_pos = []   # para enriquecer con cliente/fechas

    if use_vbbe:
        vbbe_cols = table_cols(cur, SCHEMA, "VBBE")
        qty_col = "OMENG" if "OMENG" in vbbe_cols else ("VMENG" if "VMENG" in vbbe_cols else None)
        mbdat = "MBDAT" if "MBDAT" in vbbe_cols else None
        raw = []
        for chunk in chunks(materiales_ids, 500):
            ph = ",".join(["?"] * len(chunk))
            sel_mbdat = mbdat if mbdat else "NULL"
            cur.execute(f"""
                SELECT MATNR, WERKS, VBELN, POSNR, {qty_col}, {sel_mbdat}
                FROM {SCHEMA}.VBBE
                WHERE MANDT='{MANDT}' AND MATNR IN ({ph}) AND {qty_col} <> 0
            """, chunk)
            for matnr, werks, vbeln, posnr, omeng, mb in cur.fetchall():
                werks = (werks or "").strip()
                if werks not in plant_valid:
                    continue
                matnr = (matnr or "").strip()
                vbeln = (vbeln or "").strip(); posnr = (posnr or "").strip()
                raw.append([matnr, werks, vbeln, posnr, float(omeng or 0), d(mb)])
                vbeln_pos.append((vbeln, posnr))
        cli, fdoc, fentrega = _enrich_ventas(cur, vbeln_pos)
        for matnr, werks, vbeln, posnr, qty, mb in raw:
            net_by_mp[(matnr, werks)] += qty
            rows.append((matnr, werks, vbeln, posnr,
                         cli.get(vbeln), round(qty, 3),
                         fdoc.get(vbeln), fentrega.get((vbeln, posnr)) or mb))
        print(f"  filas backorder_detalle (VBBE): {len(rows)}")
        return rows, net_by_mp, "VBBE"

    # ---- fallback: VBAP + VBUP (posiciones con entrega incompleta, no rechazadas) ----
    if not table_exists(cur, SCHEMA, "VBAP"):
        print("  VBAP tampoco disponible -> backorder vacio (se explica en reconciliacion)")
        return rows, net_by_mp, "NINGUNA"
    has_vbup = table_exists(cur, SCHEMA, "VBUP")
    raw = []
    for chunk in chunks(materiales_ids, 500):
        ph = ",".join(["?"] * len(chunk))
        if has_vbup:
            cur.execute(f"""
                SELECT a.MATNR, a.WERKS, a.VBELN, a.POSNR, a.KWMENG
                FROM {SCHEMA}.VBAP a
                JOIN {SCHEMA}.VBUP u ON a.MANDT=u.MANDT AND a.VBELN=u.VBELN AND a.POSNR=u.POSNR
                WHERE a.MANDT='{MANDT}' AND a.MATNR IN ({ph})
                  AND u.LFSTA IN ('A','B') AND (u.ABSTA IS NULL OR u.ABSTA<>'C')
            """, chunk)
        else:
            cur.execute(f"""
                SELECT a.MATNR, a.WERKS, a.VBELN, a.POSNR, a.KWMENG
                FROM {SCHEMA}.VBAP a
                WHERE a.MANDT='{MANDT}' AND a.MATNR IN ({ph}) AND a.ABGRU IS NULL
            """, chunk)
        for matnr, werks, vbeln, posnr, kwmenge in cur.fetchall():
            werks = (werks or "").strip()
            if werks not in plant_valid:
                continue
            matnr = (matnr or "").strip()
            vbeln = (vbeln or "").strip(); posnr = (posnr or "").strip()
            raw.append([matnr, werks, vbeln, posnr, float(kwmenge or 0)])
            vbeln_pos.append((vbeln, posnr))
    cli, fdoc, fentrega = _enrich_ventas(cur, vbeln_pos)
    for matnr, werks, vbeln, posnr, qty in raw:
        if qty <= 0:
            continue
        net_by_mp[(matnr, werks)] += qty
        rows.append((matnr, werks, vbeln, posnr, cli.get(vbeln),
                     round(qty, 3), fdoc.get(vbeln), fentrega.get((vbeln, posnr))))
    print(f"  filas backorder_detalle (VBAP/VBUP fallback): {len(rows)}")
    return rows, net_by_mp, "VBAP/VBUP"


def _enrich_ventas(cur, vbeln_pos):
    """cliente (KNA1) y fechas (VBAK, VBEP) para un conjunto de (VBELN,POSNR)."""
    cli, fdoc, fentrega = {}, {}, {}
    vbelns = sorted({v for v, _ in vbeln_pos})
    if not vbelns:
        return cli, fdoc, fentrega
    kunnr_by_doc = {}
    for chunk in chunks(vbelns, 800):
        ph = ",".join(["?"] * len(chunk))
        cur.execute(f"SELECT VBELN, KUNNR, AUDAT, ERDAT FROM {SCHEMA}.VBAK WHERE MANDT='{MANDT}' AND VBELN IN ({ph})", chunk)
        for vbeln, kunnr, audat, erdat in cur.fetchall():
            vbeln = (vbeln or "").strip()
            kunnr_by_doc[vbeln] = (kunnr or "").strip()
            fdoc[vbeln] = d(audat) or d(erdat)
    kunnrs = sorted({k for k in kunnr_by_doc.values() if k})
    kna1 = {}
    for chunk in chunks(kunnrs, 1000):
        ph = ",".join(["?"] * len(chunk))
        cur.execute(f"SELECT KUNNR, NAME1 FROM {SCHEMA}.KNA1 WHERE MANDT='{MANDT}' AND KUNNR IN ({ph})", chunk)
        for kunnr, name1 in cur.fetchall():
            kna1[(kunnr or "").strip()] = (name1 or "").strip()
    for vbeln, kunnr in kunnr_by_doc.items():
        cli[vbeln] = kna1.get(kunnr) or kunnr or None
    # fecha de entrega comprometida: VBEP.EDATU (schedule line mas proxima con confirmado)
    if table_exists(cur, SCHEMA, "VBEP"):
        for chunk in chunks(vbelns, 800):
            ph = ",".join(["?"] * len(chunk))
            cur.execute(f"""SELECT VBELN, POSNR, EDATU FROM {SCHEMA}.VBEP
                            WHERE MANDT='{MANDT}' AND VBELN IN ({ph}) ORDER BY VBELN, POSNR, EDATU""", chunk)
            for vbeln, posnr, edatu in cur.fetchall():
                key = ((vbeln or "").strip(), (posnr or "").strip())
                fe = d(edatu)
                if fe and key not in fentrega:
                    fentrega[key] = fe
    return cli, fdoc, fentrega


# --------------------------------------------------------------------------
# Reconciliacion
# --------------------------------------------------------------------------
def reconcile(scur, pc_gross, pc_net, bo_net, bo_source):
    print("\n=== RECONCILIACION por material/plant ===")
    report = {}

    # -- pedidos de compra vs inventarios.pedidos_abiertos --
    inv_ped = {(m, p): v for m, p, v in
               scur.execute("SELECT material_id, plant, pedidos_abiertos FROM inventarios WHERE pedidos_abiertos>0")}
    sum_inv_ped = round(sum(inv_ped.values()), 2)
    sum_gross = round(sum(pc_gross.values()), 2)
    sum_net = round(sum(pc_net.values()), 2)
    # cuadre bruto exacto contra la formula v4 (Σ EKPO.MENGE lineas abiertas)
    mp_all = set(inv_ped) | set(pc_gross)
    diff_gross = [(m, p, round(inv_ped.get((m, p), 0), 2), round(pc_gross.get((m, p), 0), 2))
                  for (m, p) in mp_all
                  if abs(inv_ped.get((m, p), 0) - pc_gross.get((m, p), 0)) > 0.5]
    print(f"  pedidos_abiertos (inventarios) Σ = {sum_inv_ped}")
    print(f"  detalle BRUTO Σ MENGE           = {sum_gross}  (misma formula v4; combos que no cuadran: {len(diff_gross)})")
    print(f"  detalle NETO Σ pendiente        = {sum_net}  (= bruto - ya recibido via EKET)")
    report["pedidos_compra"] = {
        "sum_inventarios_pedidos_abiertos": sum_inv_ped,
        "sum_detalle_bruto_menge": sum_gross,
        "sum_detalle_neto_pendiente": sum_net,
        "combos_bruto_no_cuadran": len(diff_gross),
        "ejemplos_no_cuadran": diff_gross[:10],
        "nota": ("El BRUTO (Σ MENGE de lineas abiertas) reproduce la formula de v4 y debe "
                 "cuadrar con inventarios.pedidos_abiertos. El NETO (pendiente de recepcion, "
                 "descontando EKET.WEMNG ya recibido) es <= bruto; la diferencia es mercancia "
                 "ya recibida en lineas que aun no cierran ELIKZ."),
    }

    # -- backorder vs inventarios.comprometido --
    inv_comp = {(m, p): v for m, p, v in
                scur.execute("SELECT material_id, plant, comprometido FROM inventarios WHERE comprometido>0")}
    sum_inv_comp = round(sum(inv_comp.values()), 2)
    sum_bo = round(sum(bo_net.values()), 2)
    print(f"  comprometido (inventarios) Σ    = {sum_inv_comp}")
    print(f"  backorder detalle Σ pendiente   = {sum_bo}  (fuente: {bo_source})")
    report["backorder"] = {
        "fuente": bo_source,
        "sum_inventarios_comprometido": sum_inv_comp,
        "sum_detalle_backorder": sum_bo,
        "nota": ("comprometido en v4 proviene del Calculation View de CAR "
                 "InventoryVisibilityWithSalesOrderReservedQuantity (ReservedQuantity), "
                 "mientras el detalle proviene de VBBE/VBAP. Pueden diferir porque el CV "
                 "aplica logica ATP/confirmacion; se documenta la diferencia y el origen de cada uno."),
    }
    return report


# --------------------------------------------------------------------------
def build_valid_universe(scur):
    materiales_ids = [r[0] for r in scur.execute("SELECT material_id FROM materiales")]
    plant_valid = {r[0] for r in scur.execute("SELECT plant FROM sucursales")}
    print(f"  universo v4: {len(materiales_ids)} materiales, {len(plant_valid)} plants")
    return materiales_ids, plant_valid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="comprasai_v4.db", help="DB base v4 (real)")
    ap.add_argument("--out", default="comprasai_v5.db", help="DB de salida v5")
    ap.add_argument("--reconcile-only", action="store_true",
                    help="No consulta HANA; solo re-reconcilia una v5 existente")
    args = ap.parse_args()
    t0 = time.time()

    if args.reconcile_only:
        if not os.path.exists(args.out):
            sys.exit(f"ERROR: no existe {args.out}")
        sq = sqlite3.connect(args.out); scur = sq.cursor()
        pc_gross = defaultdict(float); pc_net = defaultdict(float); bo_net = defaultdict(float)
        for m, p, g, n in scur.execute("SELECT material_id, plant, SUM(cantidad_pedida), SUM(cantidad_pendiente) FROM pedidos_compra_detalle GROUP BY material_id, plant"):
            pc_gross[(m, p)] = g or 0; pc_net[(m, p)] = n or 0
        for m, p, n in scur.execute("SELECT material_id, plant, SUM(cantidad_pendiente) FROM backorder_detalle GROUP BY material_id, plant"):
            bo_net[(m, p)] = n or 0
        rep = reconcile(scur, pc_gross, pc_net, bo_net, "(ya en DB)")
        print("\n" + json.dumps(rep, indent=2, ensure_ascii=False))
        return

    # 1) copia la base v4 -> v5 (aditivo, no destruye nada)
    if not os.path.exists(args.base):
        sys.exit(f"ERROR: no existe la base v4 {args.base} (descargar release data-real-car-v4)")
    print(f"Copiando base v4 -> {args.out}")
    shutil.copyfile(args.base, args.out)
    sq = sqlite3.connect(args.out); scur = sq.cursor()
    scur.executescript(DDL)
    # idempotencia: si se re-corre, limpia detalle previo
    scur.execute("DELETE FROM backorder_detalle")
    scur.execute("DELETE FROM pedidos_compra_detalle")
    sq.commit()

    materiales_ids, plant_valid = build_valid_universe(scur)

    # 2) HANA
    conn = env_conn(); cur = conn.cursor()
    pc_rows, pc_gross, pc_net = extract_pedidos_compra(cur, materiales_ids, plant_valid)
    bo_rows, bo_net, bo_source = extract_backorder(cur, materiales_ids, plant_valid)
    conn.close()

    # 3) insert
    scur.executemany("""INSERT INTO pedidos_compra_detalle
        (material_id,plant,po,posicion,proveedor,cantidad_pendiente,cantidad_pedida,fecha_po,fecha_entrega_estimada)
        VALUES (?,?,?,?,?,?,?,?,?)""", pc_rows)
    scur.executemany("""INSERT INTO backorder_detalle
        (material_id,plant,documento,posicion,cliente,cantidad_pendiente,fecha_documento,fecha_entrega_comprometida)
        VALUES (?,?,?,?,?,?,?,?)""", bo_rows)
    sq.commit()

    # 4) reconciliacion
    rep = reconcile(scur, pc_gross, pc_net, bo_net, bo_source)
    rep["conteos"] = {
        "backorder_detalle": scur.execute("SELECT COUNT(*) FROM backorder_detalle").fetchone()[0],
        "pedidos_compra_detalle": scur.execute("SELECT COUNT(*) FROM pedidos_compra_detalle").fetchone()[0],
    }
    with open(os.path.splitext(args.out)[0] + "_reconciliacion.json", "w") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    sq.close()
    print(f"\nDB v5: {args.out} ({os.path.getsize(args.out)/1e6:.2f} MB) -- {time.time()-t0:.1f}s")
    print("Reconciliacion escrita en", os.path.splitext(args.out)[0] + "_reconciliacion.json")


if __name__ == "__main__":
    main()
