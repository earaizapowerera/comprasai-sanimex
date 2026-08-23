#!/usr/bin/env python3
"""
build_leadtimes.py — T26 (waykee 290124). Lead times REALES por proveedor.

Construye data-real-car-v4 a partir de v3 (kardex, waykee 290120): agrega la tabla
leadtimes_reales con la DISTRIBUCION de lead time real (pedido -> entrada 101), NO un
promedio. El lead time no es lineal (depende de la corrida de produccion de la fabrica),
por eso se entregan mediana/P90/desv/min/max, % surtidos parciales, y deteccion de modas
multiples; ademas se compara contra el PLIFZ teorico de MARC (v1).

Fuentes reales (SAPS4H, MANDT 110, CAR PRD, SOLO LECTURA):
  - EKKO + EKPO  -> pedidos de compra (proveedor LIFNR, fecha pedido BEDAT, posicion, MATNR, WERKS, MENGE)
  - MATDOC       -> entradas de mercancia BWART 101 (neteadas con 102 reversa), por EBELN/EBELP, BUDAT
  - MARC.PLIFZ   -> lead time teorico por material (para comparar plan vs realidad)
  - LFA1         -> nombre del proveedor

Definiciones por pedido-posicion (EBELN,EBELP):
  - fecha pedido        = EKKO.BEDAT
  - cantidad pedida     = EKPO.MENGE (unidad de pedido)
  - recepciones         = MATDOC neto por dia = SUM(101.MENGE) - SUM(102.MENGE) (unidad base)
  - primera entrada     = primer dia con recepcion neta > 0
  - fecha 95%           = primer dia en que la recepcion ACUMULADA >= 0.95 * cantidad pedida
  - lead_time_primera   = primera_entrada - BEDAT           (dias)
  - lead_time_completo  = fecha_95pct   - BEDAT             (dias)
  - pct_surtido         = recibido_total / cantidad_pedida
  - estado: 'nunca' (sin 101), 'parcial' (0<pct<0.95), 'completo' (pct>=0.95)

Credenciales: por variables de entorno (Waykee Secrets markers en bash). NO hardcodear.
  H={SanimexHanaHost} P={SanimexCARHanaPuerto} U={SanimexCARUser} PW={SanimexCARPassword}

Uso:
  H=.. P=.. U=.. PW=.. python3 build_leadtimes.py <v3_db_in> <v4_db_out>
"""
import os, sys, time, sqlite3, shutil
from collections import defaultdict
from datetime import datetime
from hdbcli import dbapi

MANDT = '110'
BEDAT_DESDE = '20240801'   # pedidos de los ultimos 24 meses (BEDAT >= 2024-08)
UMBRAL_COMPLETO = 0.95     # % surtido que cuenta como "entrega completa"
MIN_N_MATERIAL = 10        # minimo de pedidos recibidos para publicar fila a nivel material


def hana():
    return dbapi.connect(address=os.environ['H'], port=int(os.environ['P']),
                         user=os.environ['U'], password=os.environ['PW'])


def d(s):
    """BUDAT/BEDAT 'YYYYMMDD' -> date; None si vacio/invalido."""
    if not s or s == '00000000':
        return None
    try:
        return datetime.strptime(s, '%Y%m%d').date()
    except ValueError:
        return None


def pctl(sorted_vals, p):
    """Percentil p (0-100) por interpolacion lineal sobre lista YA ordenada."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    lo = int(k); hi = min(lo + 1, len(sorted_vals) - 1)
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo))


def stddev(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    return (sum((x - m) ** 2 for x in vals) / (n - 1)) ** 0.5


def modas(vals, bin_dias=15, min_frac_2a=0.15):
    """Deteccion simple de bimodalidad sobre histograma de bins de `bin_dias`.
    Devuelve (bimodal 0/1, moda1_centro, moda2_centro). moda2=None si no bimodal.
    Un proveedor que surte en ~15 o ~60 dias segun corrida de produccion aparece bimodal."""
    if len(vals) < 8:
        return 0, (pctl(sorted(vals), 50) if vals else None), None
    hist = defaultdict(int)
    for v in vals:
        hist[int(v // bin_dias)] += 1
    bins = sorted(hist.items())  # [(bin_idx, count), ...]
    # picos locales: count[i] >= vecinos
    peaks = []
    for i, (bidx, cnt) in enumerate(bins):
        left = bins[i - 1][1] if i > 0 else 0
        right = bins[i + 1][1] if i < len(bins) - 1 else 0
        if cnt >= left and cnt >= right:
            peaks.append((cnt, bidx))
    peaks.sort(reverse=True)  # por altura desc
    n = len(vals)
    if len(peaks) >= 2:
        (c1, b1), (c2, b2) = peaks[0], peaks[1]
        # bimodal solo si el 2o pico es material y esta SEPARADO del 1o (no adyacente)
        if c2 >= min_frac_2a * n and abs(b1 - b2) >= 2:
            centro = lambda b: int((b + 0.5) * bin_dias)
            m1, m2 = sorted([centro(b1), centro(b2)])
            return 1, m1, m2
    return 0, int((peaks[0][1] + 0.5) * bin_dias), None


def main():
    v3_in = sys.argv[1] if len(sys.argv) > 1 else '/tmp/comprasai_v3.db'
    v4_out = sys.argv[2] if len(sys.argv) > 2 else '/tmp/comprasai_v4.db'
    t0 = time.time()

    os.makedirs(os.path.dirname(v4_out) or '.', exist_ok=True)
    print(f"Copiando base v3 -> v4: {v3_in} -> {v4_out}")
    shutil.copyfile(v3_in, v4_out)
    sq = sqlite3.connect(v4_out); sc = sq.cursor()

    mats_set = set(r[0] for r in sc.execute("SELECT material_id FROM materiales"))
    plants_set = set(r[0] for r in sc.execute("SELECT plant FROM sucursales"))
    print(f"Universo: {len(mats_set)} materiales HAWA, {len(plants_set)} centros")

    conn = hana(); cur = conn.cursor()
    cur.execute("SELECT NOW() FROM DUMMY"); print("HANA conn OK, now:", cur.fetchone()[0])

    # ---------------------------------------------------------------
    # 1) PEDIDOS DE COMPRA (EKKO + EKPO), HAWA, 24m, sin borrado
    # ---------------------------------------------------------------
    print(f"\n=== 1) Pedidos EKKO+EKPO (BEDAT>={BEDAT_DESDE}, HAWA, sin LOEKZ) ===")
    t = time.time()
    cur.execute(f"""
        SELECT k.EBELN, p.EBELP, k.LIFNR, k.BEDAT, p.MATNR, p.WERKS, p.MENGE, k.BSART
        FROM SAPS4H.EKPO p
        JOIN SAPS4H.EKKO k ON p.MANDT=k.MANDT AND p.EBELN=k.EBELN
        WHERE p.MANDT='{MANDT}' AND k.BEDAT >= '{BEDAT_DESDE}' AND p.MTART='HAWA'
          AND (k.LOEKZ IS NULL OR k.LOEKZ='') AND (p.LOEKZ IS NULL OR p.LOEKZ='')
          AND (p.SOBKZ IS NULL OR p.SOBKZ='')
    """)
    po = {}           # (ebeln,ebelp) -> dict
    fuera_univ = 0; menge0 = 0; sto_excluidos = 0
    sto_bsart = defaultdict(int)   # traslados internos (sin LIFNR) por tipo de documento
    batch = cur.fetchmany(100000)
    while batch:
        for ebeln, ebelp, lifnr, bedat, matnr, werks, menge, bsart in batch:
            matnr = (matnr or '').strip(); werks = (werks or '').strip()
            if matnr not in mats_set or werks not in plants_set:
                fuera_univ += 1; continue
            lifnr = (lifnr or '').strip()
            if not lifnr:
                # EKKO sin proveedor = traslado interno (STO: BSART UB/ZTR*) — NO es compra a proveedor
                sto_excluidos += 1; sto_bsart[(bsart or '').strip()] += 1; continue
            m = float(menge or 0)
            if m <= 0:
                menge0 += 1; continue
            bd = d(bedat)
            if bd is None:
                continue
            po[(ebeln.strip(), ebelp.strip())] = {
                'lifnr': lifnr, 'bedat': bd,
                'matnr': matnr, 'werks': werks, 'menge': m,
                'recs': []  # (fecha, neto)
            }
        batch = cur.fetchmany(100000)
    print(f"  PO-items proveedor en universo: {len(po)}  (fuera de universo: {fuera_univ}, menge<=0: {menge0})  {time.time()-t:.1f}s")
    print(f"  EXCLUIDOS traslados internos (STO, sin LIFNR): {sto_excluidos}  por BSART: {dict(sto_bsart)}")

    # ---------------------------------------------------------------
    # 2) ENTRADAS DE MERCANCIA MATDOC (101 neteado con 102), por PO-item y dia
    # ---------------------------------------------------------------
    print(f"\n=== 2) Entradas MATDOC BWART 101/102 por EBELN/EBELP/BUDAT ===")
    t = time.time()
    cur.execute(f"""
        SELECT EBELN, EBELP, BUDAT,
               SUM(CASE WHEN BWART='101' THEN MENGE ELSE 0 END)
             - SUM(CASE WHEN BWART='102' THEN MENGE ELSE 0 END) AS neto
        FROM SAPS4H.MATDOC
        WHERE MANDT='{MANDT}' AND BWART IN ('101','102') AND EBELN<>'' AND BUDAT>='{BEDAT_DESDE}'
        GROUP BY EBELN, EBELP, BUDAT
    """)
    gr_rows = 0; gr_match = 0
    batch = cur.fetchmany(100000)
    while batch:
        for ebeln, ebelp, budat, neto in batch:
            gr_rows += 1
            key = ((ebeln or '').strip(), (ebelp or '').strip())
            rec = po.get(key)
            if rec is None:
                continue
            bd = d(budat)
            if bd is None:
                continue
            rec['recs'].append((bd, float(neto or 0)))
            gr_match += 1
        batch = cur.fetchmany(100000)
    conn_matdoc_done = time.time() - t
    print(f"  filas GR (dia) leidas: {gr_rows}, casadas a PO-item del universo: {gr_match}  {conn_matdoc_done:.1f}s")

    # ---------------------------------------------------------------
    # 3) PLIFZ teorico (MARC) por material + nombre de proveedor (LFA1)
    # ---------------------------------------------------------------
    print("\n=== 3) PLIFZ teorico (MARC) + nombre proveedor (LFA1) ===")
    plifz_mat = {}
    def chunks(l, n):
        for i in range(0, len(l), n):
            yield l[i:i+n]
    mats_list = sorted(mats_set)
    for ch in chunks(mats_list, 500):
        ph = ','.join(['?']*len(ch))
        cur.execute(f"SELECT MATNR, PLIFZ FROM SAPS4H.MARC WHERE MANDT='{MANDT}' AND MATNR IN ({ph})", ch)
        agg = defaultdict(list)
        for matnr, plifz in cur.fetchall():
            if plifz is not None:
                agg[matnr.strip()].append(float(plifz))
        for m, l in agg.items():
            plifz_mat[m] = sum(l)/len(l)   # promedio entre centros (igual que v1)
    lifnrs = sorted(set(v['lifnr'] for v in po.values() if v['lifnr']))
    lfa1 = {}
    for ch in chunks(lifnrs, 1000):
        ph = ','.join(['?']*len(ch))
        cur.execute(f"SELECT LIFNR, NAME1 FROM SAPS4H.LFA1 WHERE MANDT='{MANDT}' AND LIFNR IN ({ph})", ch)
        for lifnr, name1 in cur.fetchall():
            lfa1[lifnr.strip()] = (name1 or '').strip()
    conn.close()
    print(f"  materiales con PLIFZ: {len(plifz_mat)}/{len(mats_set)} · proveedores (LIFNR): {len(lifnrs)}")

    # ---------------------------------------------------------------
    # 4) Metricas por pedido-posicion
    # ---------------------------------------------------------------
    print("\n=== 4) Lead time por pedido-posicion ===")
    # acumuladores por proveedor y por (proveedor,material)
    prov = defaultdict(lambda: {'n':0,'lead1':[],'leadc':[],'pct':[],'nunca':0,'parcial':0,'completo':0,'neg':0})
    provmat = defaultdict(lambda: {'n':0,'lead1':[],'leadc':[],'pct':[],'nunca':0,'parcial':0,'completo':0,'neg':0})
    ejemplos = []  # para validacion manual
    neg_lead = 0
    for key, r in po.items():
        lifnr = r['lifnr'] or '(sin proveedor)'
        matnr = r['matnr']; bedat = r['bedat']; ordered = r['menge']
        recs = sorted(r['recs'])
        pk = prov[lifnr]; pmk = provmat[(lifnr, matnr)]
        pk['n'] += 1; pmk['n'] += 1
        # acumulado
        cum = 0.0; first_recv = None; fecha95 = None
        for (fecha, neto) in recs:
            if neto > 0 and first_recv is None:
                first_recv = fecha
            cum += neto
            if fecha95 is None and ordered > 0 and cum >= UMBRAL_COMPLETO * ordered:
                fecha95 = fecha
        recibido_total = cum
        pct = (recibido_total / ordered) if ordered > 0 else 0.0
        # estado
        if first_recv is None or recibido_total <= 0:
            pk['nunca'] += 1; pmk['nunca'] += 1
            pk['pct'].append(0.0); pmk['pct'].append(0.0)
            continue
        lead1 = (first_recv - bedat).days
        pk['pct'].append(min(pct, 5.0)); pmk['pct'].append(min(pct, 5.0))
        if lead1 < 0:
            pk['neg'] += 1; pmk['neg'] += 1; neg_lead += 1  # anomalia: entrada antes del pedido
        else:
            pk['lead1'].append(lead1); pmk['lead1'].append(lead1)
        if pct >= UMBRAL_COMPLETO and fecha95 is not None:
            pk['completo'] += 1; pmk['completo'] += 1
            leadc = (fecha95 - bedat).days
            if leadc >= 0:
                pk['leadc'].append(leadc); pmk['leadc'].append(leadc)
        else:
            pk['parcial'] += 1; pmk['parcial'] += 1
        if len(ejemplos) < 40 and lead1 >= 0:
            ejemplos.append((key, lifnr, matnr, bedat, ordered, first_recv, fecha95, recibido_total, pct, lead1, recs[:6]))
    print(f"  PO-items procesados: {len(po)}  (lead negativo/anomalo: {neg_lead})")

    # ---------------------------------------------------------------
    # 5) Construir tabla leadtimes_reales
    # ---------------------------------------------------------------
    print("\n=== 5) Agregando y creando leadtimes_reales ===")

    def fila(pid, mat, acc):
        n = acc['n']
        l1 = sorted(acc['lead1']); lc = sorted(acc['leadc'])
        n_rec = len(acc['lead1']) + acc['neg']  # recibidos (incluye lead negativo)
        n_comp = acc['completo']
        parciales = acc['parcial'] + acc['nunca']
        med = pctl(l1, 50); p90 = pctl(l1, 90)
        dsv = round(stddev(l1), 1) if len(l1) >= 2 else 0.0
        mn = float(l1[0]) if l1 else None; mx = float(l1[-1]) if l1 else None
        medc = pctl(lc, 50); p90c = pctl(lc, 90)
        pct_surt = round(sum(acc['pct'])/len(acc['pct']), 3) if acc['pct'] else 0.0
        bim, m1, m2 = modas(acc['lead1'])
        plt = plifz_mat.get(mat) if mat else None
        if mat is None:  # nivel proveedor: PLIFZ ponderado por # pedidos de sus materiales
            wl = [(provmat[(pid, mm)]['n'], plifz_mat.get(mm)) for (pp, mm) in provmat if pp == pid]
            wl = [(w, pl) for (w, pl) in wl if pl is not None]
            plt = round(sum(w*pl for w, pl in wl)/sum(w for w, _ in wl), 1) if wl else None
        delta = round(med - plt, 1) if (med is not None and plt is not None) else None
        return (pid, lfa1.get(pid, None), mat, ('material' if mat else 'proveedor'),
                n, n_rec, n_comp,
                round(med,1) if med is not None else None,
                round(p90,1) if p90 is not None else None,
                dsv, mn, mx,
                round(medc,1) if medc is not None else None,
                round(p90c,1) if p90c is not None else None,
                round(100.0*parciales/n,1) if n else None,
                round(100.0*acc['nunca']/n,1) if n else None,
                pct_surt,
                round(plt,1) if plt is not None else None,
                delta, bim,
                float(m1) if m1 is not None else None,
                float(m2) if m2 is not None else None)

    filas = []
    for pid, acc in prov.items():
        filas.append(fila(pid, None, acc))
    # nivel material: solo top (>= MIN_N_MATERIAL recibidos) para no inflar la tabla
    n_mat_rows = 0
    for (pid, mat), acc in provmat.items():
        if len(acc['lead1']) >= MIN_N_MATERIAL:
            filas.append(fila(pid, mat, acc)); n_mat_rows += 1

    sc.execute("DROP TABLE IF EXISTS leadtimes_reales")
    sc.execute("""
        CREATE TABLE leadtimes_reales (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            proveedor_id          TEXT,              -- LIFNR (SAP vendor); '(sin proveedor)' si EKKO sin LIFNR
            proveedor_nombre      TEXT,              -- LFA1.NAME1
            material_id           TEXT,              -- NULL = agregado a nivel proveedor; no-NULL = por material (top)
            nivel                 TEXT NOT NULL,     -- 'proveedor' | 'material'
            n_pedidos             INTEGER NOT NULL,  -- pedido-posiciones (EBELN/EBELP) en 24m
            n_recibidos           INTEGER NOT NULL,  -- con al menos una entrada 101
            n_completos           INTEGER NOT NULL,  -- surtidos >= 95%
            mediana_dias          REAL,              -- lead a PRIMERA entrada (mediana)
            p90_dias              REAL,
            desv_dias             REAL,
            min_dias              REAL,
            max_dias              REAL,
            mediana_completo_dias REAL,              -- lead a 95% surtido (mediana)
            p90_completo_dias     REAL,
            pct_parciales         REAL,              -- % pedidos nunca surtidos o parciales (<95%)
            pct_nunca             REAL,              -- % pedidos sin ninguna entrada
            pct_surtido_prom      REAL,              -- promedio de (recibido/pedido), cap 5.0
            plifz_teorico_dias    REAL,              -- MARC.PLIFZ (plan)
            delta_vs_plifz_dias   REAL,              -- mediana_dias - plifz_teorico (realidad - plan)
            bimodal               INTEGER NOT NULL DEFAULT 0,  -- 1 si hay 2 modas separadas
            moda1_dias            REAL,
            moda2_dias            REAL
        )
    """)
    sc.executemany("""INSERT INTO leadtimes_reales
        (proveedor_id,proveedor_nombre,material_id,nivel,n_pedidos,n_recibidos,n_completos,
         mediana_dias,p90_dias,desv_dias,min_dias,max_dias,mediana_completo_dias,p90_completo_dias,
         pct_parciales,pct_nunca,pct_surtido_prom,plifz_teorico_dias,delta_vs_plifz_dias,
         bimodal,moda1_dias,moda2_dias)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", filas)
    sc.execute("CREATE INDEX idx_lt_prov ON leadtimes_reales(proveedor_id)")
    sc.execute("CREATE INDEX idx_lt_mat ON leadtimes_reales(material_id)")
    sc.execute("CREATE INDEX idx_lt_nivel ON leadtimes_reales(nivel)")
    sq.commit()
    print(f"  filas leadtimes_reales: {len(filas)}  (proveedor: {len(prov)}, material top: {n_mat_rows})")

    # ---------------------------------------------------------------
    # 6) Resumen y 3 ejemplos validados a mano
    # ---------------------------------------------------------------
    print("\n=== 6) Resumen ===")
    print("  Top 12 proveedores por # pedidos:")
    for row in sc.execute("""SELECT proveedor_id,substr(coalesce(proveedor_nombre,''),1,28),n_pedidos,n_recibidos,
                             mediana_dias,p90_dias,desv_dias,pct_parciales,plifz_teorico_dias,delta_vs_plifz_dias,bimodal,moda1_dias,moda2_dias
                             FROM leadtimes_reales WHERE nivel='proveedor' ORDER BY n_pedidos DESC LIMIT 12"""):
        print("   ", row)
    print(f"\n  Proveedores bimodales: ",
          sc.execute("SELECT COUNT(*) FROM leadtimes_reales WHERE nivel='proveedor' AND bimodal=1").fetchone()[0])
    print("  Ejemplos bimodales (proveedor):")
    for row in sc.execute("""SELECT proveedor_id,substr(coalesce(proveedor_nombre,''),1,24),n_recibidos,mediana_dias,moda1_dias,moda2_dias,p90_dias
                             FROM leadtimes_reales WHERE nivel='proveedor' AND bimodal=1 ORDER BY n_pedidos DESC LIMIT 6"""):
        print("   ", row)

    print("\n=== 3 EJEMPLOS VALIDADOS A MANO (pedido -> entradas -> lead time) ===")
    # elegir 3 ejemplos: uno completo rapido, uno completo lento, uno con varias entradas
    ejemplos.sort(key=lambda e: e[9])  # por lead1
    sel = []
    if ejemplos:
        sel.append(ejemplos[0])                      # mas rapido
        sel.append(ejemplos[len(ejemplos)//2])       # mediano
        multi = [e for e in ejemplos if len(e[10]) >= 2]
        sel.append(multi[-1] if multi else ejemplos[-1])  # con varias entradas / mas lento
    for (key, lifnr, matnr, bedat, ordered, first_recv, fecha95, recibido, pct, lead1, recs) in sel:
        print(f"\n  Pedido {key[0]}/{key[1]} · proveedor {lifnr} ({lfa1.get(lifnr,'?')}) · material {matnr}")
        print(f"    BEDAT (pedido)      = {bedat}   cantidad pedida = {ordered}")
        print(f"    entradas (fecha,neto): {[(str(f),n) for f,n in recs]}")
        print(f"    1a entrada          = {first_recv}  -> lead_time_primera = {lead1} dias")
        print(f"    fecha 95% surtido   = {fecha95}   recibido_total = {round(recibido,2)}  pct_surtido = {round(pct,3)}")
        if fecha95:
            print(f"    lead_time_completo  = {(fecha95-bedat).days} dias")

    print("\n=== CONTEOS v4 ===")
    for t_ in ["materiales","sucursales","ventas_mensuales","inventarios","proveedores","kardex_diario","leadtimes_reales"]:
        print(f"  {t_:22s}", sc.execute(f"SELECT COUNT(*) FROM {t_}").fetchone()[0])
    sq.close()
    print(f"\nDB v4: {v4_out} ({os.path.getsize(v4_out)/1e6:.1f} MB) -- total {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
