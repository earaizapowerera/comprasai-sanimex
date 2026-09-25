#!/usr/bin/env python3
"""
extract_sucursal_compra.py — Evidencia SAP para el catálogo sucursal_compra (waykee 292252).

QUE HACE
  SAP no trae un indicador "esta sucursal compra / no compra" (T001W.VLFKZ solo
  distingue tienda vs CEDIS, WRF1 solo trae bloqueos de apertura y MARC.BWSCL
  no separa grupos). El comportamiento se infiere de las órdenes de compra
  reales. Este extractor saca, por centro receptor (EKPO.WERKS):

    oc_ext_12m       OCs a proveedor externo en los últimos 12 meses
    lineas_12m       líneas de esas OCs
    proveedores_12m  proveedores distintos
    ult_oc_ext       fecha (YYYY-MM-DD) de la OC externa más reciente
    oc_ext_24m       OCs externas en 24 meses (contexto)
    traslados_12m    pedidos de traslado recibidos (RESWK lleno) en 12 meses

  "OC externa" = EKKO.BSTYP='F', RESWK vacío (no es traslado), BSART<>'ZDEV'
  (devolución), EKPO.MATNR no vacío, KNTTP vacío (a stock, no gasto/servicio)
  y LOEKZ vacío (no borrada).

  Salida: CSV (default backend/data/sucursal_compra_evidencia.csv), que el
  backend carga en la tabla sucursal_compra_evidencia y reclasifica con el
  umbral configurable (ver backend/app/core/sucursal_compra.py). Opcional:
  --db para escribir la tabla directo en un SQLite (el cron diario).

SEGURIDAD
  Credenciales y endpoint SOLO por variables de entorno, nada hardcodeado:
    SANIMEX_CAR_USER, SANIMEX_CAR_PASS, SANIMEX_CAR_HOST, SANIMEX_CAR_PORT

USO
    SANIMEX_CAR_USER=... SANIMEX_CAR_PASS=... SANIMEX_CAR_HOST=... SANIMEX_CAR_PORT=... \
    python3 data/extract_sucursal_compra.py [--out ruta.csv] [--db comprasai.db]
"""
import argparse
import csv
import datetime as dt
import os
import sqlite3
import sys
from pathlib import Path

SCHEMA = "SAPS4H"  # réplica S/4HANA en CAR (MANDT único 110)
MANDT = "110"
COLS = ["plant", "oc_ext_12m", "lineas_12m", "proveedores_12m", "ult_oc_ext",
        "oc_ext_24m", "traslados_12m", "ventana_desde", "ventana_hasta", "extraido"]
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "backend" / "data" / "sucursal_compra_evidencia.csv"

FILTRO_EXT = """k.BSTYP='F' AND k.RESWK='' AND k.BSART<>'ZDEV'
    AND p.MATNR<>'' AND p.KNTTP='' AND p.LOEKZ=''"""


def _connect():
    faltan = [k for k in ("SANIMEX_CAR_USER", "SANIMEX_CAR_PASS", "SANIMEX_CAR_HOST", "SANIMEX_CAR_PORT")
              if not os.environ.get(k)]
    if faltan:
        sys.exit(f"Faltan variables de entorno: {', '.join(faltan)}")
    from hdbcli import dbapi
    return dbapi.connect(address=os.environ["SANIMEX_CAR_HOST"], port=int(os.environ["SANIMEX_CAR_PORT"]),
                         user=os.environ["SANIMEX_CAR_USER"], password=os.environ["SANIMEX_CAR_PASS"],
                         connectTimeout=20000, communicationTimeout=600000)


def _rows(cur, sql: str, params: tuple) -> list:
    cur.execute(sql, params)
    return [r for r in cur.fetchall() if r[0] and r[0].strip()]


def _query(cur, sql: str, params: tuple) -> dict:
    rows = _rows(cur, sql, params)
    cols = [d[0] for d in cur.description]
    return {r[0].strip().upper(): dict(zip(cols, r)) for r in rows}


def extraer(cur, hoy: dt.date) -> list[dict]:
    d12 = (hoy - dt.timedelta(days=365)).strftime("%Y%m%d")
    d24 = (hoy - dt.timedelta(days=730)).strftime("%Y%m%d")
    base = f"FROM {SCHEMA}.EKKO k JOIN {SCHEMA}.EKPO p ON p.MANDT=k.MANDT AND p.EBELN=k.EBELN WHERE k.MANDT=?"
    ext12 = _query(cur, f"""SELECT p.WERKS, COUNT(DISTINCT k.EBELN) OC, COUNT(*) LIN,
        COUNT(DISTINCT k.LIFNR) PROVS, MAX(k.BEDAT) ULT {base} AND k.BEDAT>=? AND {FILTRO_EXT}
        GROUP BY p.WERKS""", (MANDT, d12))
    ext24 = _query(cur, f"""SELECT p.WERKS, COUNT(DISTINCT k.EBELN) OC {base} AND k.BEDAT>=? AND {FILTRO_EXT}
        GROUP BY p.WERKS""", (MANDT, d24))
    sto = _query(cur, f"""SELECT p.WERKS, COUNT(DISTINCT k.EBELN) OC {base} AND k.BEDAT>=?
        AND k.BSTYP='F' AND k.RESWK<>'' AND p.LOEKZ='' GROUP BY p.WERKS""", (MANDT, d12))
    centros = [r[0].strip().upper() for r in _rows(cur, f"SELECT WERKS FROM {SCHEMA}.T001W WHERE MANDT=?", (MANDT,))]
    extraido = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    filas = []
    # Todos los centros de T001W, con ceros si no tuvieron OCs: la ausencia de
    # actividad ES la evidencia de "no compra".
    for plant in sorted(set(centros) | set(ext12) | set(ext24) | set(sto)):
        e = ext12.get(plant, {})
        ult = e.get("ULT") or ""
        filas.append({
            "plant": plant, "oc_ext_12m": int(e.get("OC") or 0), "lineas_12m": int(e.get("LIN") or 0),
            "proveedores_12m": int(e.get("PROVS") or 0),
            "ult_oc_ext": f"{ult[:4]}-{ult[4:6]}-{ult[6:8]}" if len(ult) == 8 else "",
            "oc_ext_24m": int(ext24.get(plant, {}).get("OC") or 0),
            "traslados_12m": int(sto.get(plant, {}).get("OC") or 0),
            "ventana_desde": (hoy - dt.timedelta(days=365)).isoformat(), "ventana_hasta": hoy.isoformat(),
            "extraido": extraido,
        })
    return filas


def escribir_csv(filas: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(filas)


def escribir_db(filas: list[dict], db_path: Path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
    from app.core import sucursal_compra  # import diferido: el backend define el esquema
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = lambda c, r: dict(zip([x[0] for x in c.description], r))
    try:
        sucursal_compra.init_tables(conn)
        sucursal_compra.reemplazar_evidencia(conn, filas)
        print("Reclasificación:", sucursal_compra.recalcular(conn)["conteo"])
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--db", type=Path, help="SQLite de ComprasAI a actualizar (opcional)")
    args = ap.parse_args()
    conn = _connect()
    try:
        filas = extraer(conn.cursor(), dt.datetime.now(dt.timezone.utc).date())
    finally:
        conn.close()
    escribir_csv(filas, args.out)
    print(f"{len(filas)} centros con evidencia -> {args.out}")
    if args.db:
        escribir_db(filas, args.db)


if __name__ == "__main__":
    main()
