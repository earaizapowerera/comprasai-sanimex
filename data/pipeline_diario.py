#!/usr/bin/env python3
"""
pipeline_diario.py — Corrida diaria del snapshot ComprasAI Sanimex (waykee 292194).

HANA CAR PRD --(extractores v1..v7)--> SQLite --(load_sqlserver)--> SQL Server
dbdev.ComprasAISanimex --(POST /api/balanceos/recalcular)--> caches del backend.

Garantías:
  - Una sola corrida a la vez (flock sobre <workdir>/.lock; el loader además toma
    sp_getapplock en SQL Server).
  - Si cualquier paso falla, NO se carga nada: la base sigue con el snapshot
    anterior, que es consistente. Se notifica al PM (#290066) por bridge-send.
  - Cada paso escribe un SQLite nuevo y el intermedio anterior se borra en cuanto
    el siguiente termina bien; al final solo queda <workdir>/ultimo_ok.db.

Configuración (archivos KEY=VALUE, modo 600, fuera del repo):
  ~/.config/comprasai/hana.env       SANIMEX_CAR_HOST/PORT/USER/PASS
  ~/.config/comprasai/sqlserver.env  COMPRASAI_SQLSERVER_*
  ~/.config/comprasai/pipeline.env   WAYKEE_BOT_TOKEN (aviso de fallas) y opcionales:
      COMPRASAI_RECALC_URLS   URLs separadas por coma a las que se hace POST al final
      COMPRASAI_PIPELINE_DIR  directorio de trabajo (default ~/comprasai-pipeline)

Uso:  python3 pipeline_diario.py [--desde PASO] [--sin-carga]
"""
import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF = Path.home() / ".config" / "comprasai"
ENV_FILES = ("hana.env", "sqlserver.env", "pipeline.env")
WAYKEE_API = "https://wk2.waykee.com/api/waykee"
WAYKEE_ORIGEN, WAYKEE_PM = 292194, 290066

# (nombre, argumentos; {inp} = SQLite del paso anterior, {out} = SQLite de este paso)
PASOS = [
    ("v1_real_car", ["extract_real_car.py", "{out}"]),
    ("v2_stock_real", ["extract_v2_stock_real.py", "--base", "{inp}", "--out", "{out}"]),
    ("v3_kardex", ["build_kardex_v3.py", "{inp}", "{out}"]),
    ("v4_leadtimes", ["build_leadtimes.py", "{inp}", "{out}"]),
    ("v5_detalle", ["extract_v5_detalle.py", "--base", "{inp}", "--out", "{out}"]),
    ("v6_ventas_stats", ["extract_v6_ventas_stats.py", "--base", "{inp}", "--out", "{out}"]),
    ("v7_inventario_categorias", ["extract_v7_inventario_categorias.py", "--base", "{inp}", "--out", "{out}"]),
]


class PasoFallido(Exception):
    def __init__(self, paso: str, detalle: str):
        super().__init__(f"{paso}: {detalle}")
        self.paso, self.detalle = paso, detalle


def cargar_env():
    for nombre in ENV_FILES:
        f = CONF / nombre
        if not f.exists():
            continue
        for linea in f.read_text().splitlines():
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                k, v = linea.split("=", 1)
                os.environ.setdefault(k.strip().removeprefix("export "), v.strip().strip("'\""))


def log(msg: str, fh):
    linea = f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z] {msg}"
    print(linea, flush=True)
    fh.write(linea + "\n")
    fh.flush()


def correr(paso: str, args: list[str], fh):
    t0 = time.time()
    log(f">> {paso}: {' '.join(Path(a).name if a.endswith('.db') else a for a in args)}", fh)
    r = subprocess.run([sys.executable, *args], cwd=HERE, stdout=fh, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        raise PasoFallido(paso, f"exit {r.returncode}")
    log(f"<< {paso} OK ({time.time() - t0:.0f}s)", fh)


def extraer(workdir: Path, desde: str | None, fh) -> Path:
    """Corre la cadena v1..v7 (+ sucursal_compra) y devuelve el SQLite final."""
    nombres = [p[0] for p in PASOS]
    inicio = nombres.index(desde) if desde else 0
    previo = workdir / f"{nombres[inicio - 1]}.db" if inicio else None
    for nombre, plantilla in PASOS[inicio:]:
        out = workdir / f"{nombre}.db"
        args = [a.format(inp=previo, out=out) for a in plantilla]
        correr(nombre, args, fh)
        if previo and previo.exists():
            previo.unlink()
        previo = out
    correr("sucursal_compra", ["extract_sucursal_compra.py", "--db", str(previo),
                               "--out", str(workdir / "sucursal_compra_evidencia.csv")], fh)
    return previo


def recalcular(fh):
    for url in filter(None, os.environ.get("COMPRASAI_RECALC_URLS", "").split(",")):
        try:
            req = urllib.request.Request(url.strip(), method="POST", data=b"")
            with urllib.request.urlopen(req, timeout=600) as r:
                log(f"recalcular {url}: HTTP {r.status} {r.read(300).decode(errors='replace')}", fh)
        except Exception as exc:  # noqa: BLE001 -- el snapshot ya quedó cargado
            raise PasoFallido("recalcular", f"{url}: {type(exc).__name__}: {exc}") from exc


def notificar(texto: str):
    token = os.environ.get("WAYKEE_BOT_TOKEN")
    if not token:
        print("WARN: sin WAYKEE_BOT_TOKEN, no se notifica", file=sys.stderr)
        return
    body = json.dumps({"SourceWaykeeId": WAYKEE_ORIGEN, "TargetWaykeeId": WAYKEE_PM,
                       "Message": texto, "Category": "info"}).encode()
    req = urllib.request.Request(f"{WAYKEE_API}/messages/bridge-send", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30).close()
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: no se pudo notificar: {exc}", file=sys.stderr)


def cola_log(ruta: Path, n: int = 15) -> str:
    lineas = ruta.read_text(errors="replace").splitlines()[-n:]
    return "\n".join(l[:200] for l in lineas)


def main():
    ap = argparse.ArgumentParser(description="Snapshot diario ComprasAI (HANA -> SQL Server)")
    ap.add_argument("--desde", choices=[p[0] for p in PASOS], help="Retomar desde este paso")
    ap.add_argument("--sin-carga", action="store_true", help="Solo extraer (no toca SQL Server)")
    a = ap.parse_args()

    cargar_env()
    workdir = Path(os.environ.get("COMPRASAI_PIPELINE_DIR", Path.home() / "comprasai-pipeline"))
    (workdir / "logs").mkdir(parents=True, exist_ok=True)
    lock = open(workdir / ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("Otra corrida del pipeline sigue en curso; no se inicia otra.")

    ruta_log = workdir / "logs" / f"{datetime.now(timezone.utc):%Y-%m-%d_%H%M}.log"
    with open(ruta_log, "w") as fh:
        t0 = time.time()
        try:
            final = extraer(workdir, a.desde, fh)
            if a.sin_carga:
                log(f"--sin-carga: queda {final}", fh)
                return
            correr("load_sqlserver", ["load_sqlserver.py", "--sqlite", str(final)], fh)
            final.replace(workdir / "ultimo_ok.db")
            recalcular(fh)
            log(f"PIPELINE OK en {(time.time() - t0) / 60:.1f} min", fh)
        except Exception as exc:  # noqa: BLE001 -- cualquier falla se reporta
            paso = exc.paso if isinstance(exc, PasoFallido) else "orquestador"
            log(f"PIPELINE FALLÓ en {paso}: {exc}", fh)
            estado = ("El snapshot nuevo SÍ quedó cargado; solo faltó recalcular caches."
                      if paso == "recalcular" else "SQL Server sigue con el snapshot anterior.")
            notificar(f"[cron snapshot ComprasAI] Falló el paso {paso} ({exc}). {estado} "
                      f"Log en la Mac: {ruta_log}\n```\n{cola_log(ruta_log)}\n```")
            sys.exit(1)


if __name__ == "__main__":
    main()
