"""Equivalencia SQLite vs SQL Server: corre los GET de la API contra cada
almacenamiento y compara el JSON. Detecta diferencias de dialecto que los
tests unitarios (SQLite en memoria) no ven: división entera, LIMIT anidado,
orden de NULLs, redondeos.

Uso (desde backend/, con la venv de la API):
  python -m analysis.compare_backends dump sqlite  /tmp/out_sqlite.json   # DB_PATH=copia del v7
  python -m analysis.compare_backends dump sqlserver /tmp/out_mssql.json  # COMPRASAI_SQLSERVER_*
  python -m analysis.compare_backends diff /tmp/out_sqlite.json /tmp/out_mssql.json
"""

from __future__ import annotations

import json
import math
import sys
import time

# Endpoints con parámetros de ruta: se prueban con un material/sucursal reales.
SAMPLE_PATHS = {"material_id": None, "plant": None, "plant_o_canal": None}
SKIP = {"/api/health"}
# Campos que cambian en cada corrida (hora de generación, UUID de sugerido).
VOLATILE = {"generado", "generado_hace_segundos", "creado", "actualizado", "id"}


def _samples(client) -> dict:
    inv = client.get("/api/inventarios", params={"page_size": 1}).json()
    rows = inv.get("items") or inv.get("data") or inv.get("rows") or []
    row = rows[0] if rows else {}
    return {"material_id": row.get("material_id"), "plant": row.get("plant"),
            "plant_o_canal": row.get("plant")}


def dump(mode: str, out: str) -> None:
    import os

    if mode == "sqlite":
        os.environ.pop("COMPRASAI_SQLSERVER_HOST", None)
    from fastapi.testclient import TestClient

    from app.main import app

    results = {}
    with TestClient(app, raise_server_exceptions=False) as client:
        samples = _samples(client)
        for path, item in sorted(app.openapi()["paths"].items()):
            if "get" not in item or path in SKIP:
                continue
            url = path
            for k, v in samples.items():
                url = url.replace("{" + k + "}", str(v))
            if "{" in url:
                continue
            t0 = time.time()
            r = client.get(url)
            try:
                body = r.json()
            except ValueError:
                body = r.text[:2000]
            results[url] = {"status": r.status_code, "ms": round(1000 * (time.time() - t0)),
                            "body": body}
            print(f"{r.status_code} {results[url]['ms']:>6}ms {url}", flush=True)
    with open(out, "w") as fh:
        json.dump(results, fh, default=str)


def _same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)
    return a == b


def _diff(a, b, path="", out=None, limit=5):
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted((set(a) | set(b)) - VOLATILE):
            _diff(a.get(k, "<falta>"), b.get(k, "<falta>"), f"{path}.{k}", out, limit)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: len {len(a)} vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            _diff(x, y, f"{path}[{i}]", out, limit)
    elif not _same(a, b):
        out.append(f"{path}: {str(a)[:80]!r} vs {str(b)[:80]!r}")
    return out


def diff(fa: str, fb: str) -> int:
    a, b = json.load(open(fa)), json.load(open(fb))
    bad = 0
    for url in sorted(set(a) | set(b)):
        ra, rb = a.get(url), b.get(url)
        if not ra or not rb:
            print(f"SOLO EN UNO  {url}")
            bad += 1
            continue
        d = [] if ra["status"] == rb["status"] else [f"status {ra['status']} vs {rb['status']}"]
        d += _diff(ra["body"], rb["body"])
        if d:
            bad += 1
            print(f"DIFF {url}  ({ra['ms']}ms vs {rb['ms']}ms)")
            for line in d:
                print(f"     {line}")
    print(f"\n{len(a)} endpoints, {bad} con diferencias")
    return 1 if bad else 0


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "dump":
        dump(sys.argv[2], sys.argv[3])
    else:
        sys.exit(diff(sys.argv[2], sys.argv[3]))
