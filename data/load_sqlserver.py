"""Carga el dataset SQLite generado por los extractores a SQL Server (dbdev).

Por qué SQLite como paso intermedio: los extractores v5..v7 ya están
validados como aditivos y reproducibles sobre SQLite. Este cargador los deja
intactos y convierte el archivo resultante en el snapshot oficial en SQL
Server, que es lo que lee el backend.

Refresco atómico: todas las tablas se cargan primero en el schema `stg` y al
final se intercambian con `dbo` en UNA transacción (ALTER SCHEMA TRANSFER).
Los lectores ven el snapshot anterior completo o el nuevo completo, nunca uno
a medias. Si algo falla antes del swap, `dbo` queda intacto.

Conexión SOLO por variables de entorno (nunca en código ni commits):
  COMPRASAI_SQLSERVER_HOST / _PORT / _DB / _USER / _PASSWORD

Uso:
  python data/load_sqlserver.py --sqlite ruta/comprasai_v7.db
  python data/load_sqlserver.py --sqlite ruta/comprasai_v7.db --dry-run   # solo imprime DDL
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from typing import Iterable, Optional

# Tablas internas de SQLite que no forman parte del dataset.
SKIP_TABLES = {"sqlite_sequence", "sqlite_stat1", "sqlite_stat4"}
# SQL Server limita a 2100 parámetros por sentencia.
MAX_PARAMS = 2000
MAX_ROWS_PER_INSERT = 1000
STG, DBO, OLD = "stg", "dbo", "old"


# ---------------------------------------------------------------- esquema

def _sql_type(sqlite_type: str, max_len: Optional[int], is_key: bool) -> str:
    t = (sqlite_type or "").upper()
    if t == "INTEGER":
        return "BIGINT"
    if t == "REAL":
        return "FLOAT"
    # TEXT o sin tipo declarado: NVARCHAR dimensionado al dato real. Las
    # columnas de llave/índice necesitan longitud acotada (máx 450 en índice).
    # Holgura x2: el snapshot de mañana puede traer textos más largos.
    n = max(32, 2 * (max_len or 0))
    if is_key:
        return f"NVARCHAR({min(450, _round_up(n))})"
    return "NVARCHAR(MAX)" if n > 4000 else f"NVARCHAR({_round_up(n)})"


def _round_up(n: int) -> int:
    size = 16
    while size < n:
        size *= 2
    return min(size, 4000)


def _indexes(src: sqlite3.Connection, table: str) -> list[tuple[str, list[str]]]:
    out = []
    for _, name, unique, origin, _ in src.execute(f'PRAGMA index_list("{table}")'):
        if origin != "c":  # solo índices explícitos; PK/UNIQUE van en el DDL
            continue
        cols = [r[2] for r in src.execute(f'PRAGMA index_info("{name}")')]
        out.append((name, cols))
    return out


def table_spec(src: sqlite3.Connection, table: str) -> dict:
    cols = src.execute(f'PRAGMA table_info("{table}")').fetchall()
    pk = [c[1] for c in sorted(cols, key=lambda c: c[5]) if c[5]]
    idx = _indexes(src, table)
    keyed = set(pk) | {c for _, cs in idx for c in cs}
    specs = []
    for _, name, ctype, notnull, _, _ in cols:
        max_len = None
        if (ctype or "").upper() not in ("INTEGER", "REAL"):
            max_len = src.execute(
                f'SELECT MAX(LENGTH("{name}")) FROM "{table}"').fetchone()[0]
        specs.append({
            "name": name,
            "type": _sql_type(ctype, max_len, name in keyed),
            "not_null": bool(notnull) or name in pk,
        })
    return {"table": table, "columns": specs, "pk": pk, "indexes": idx}


def create_ddl(spec: dict, schema: str) -> list[str]:
    t = f"[{schema}].[{spec['table']}]"
    cols = [f"[{c['name']}] {c['type']}{' NOT NULL' if c['not_null'] else ''}"
            for c in spec["columns"]]
    if spec["pk"]:
        pk_cols = ", ".join(f"[{c}]" for c in spec["pk"])
        cols.append(f"CONSTRAINT [PK_{spec['table']}] PRIMARY KEY ({pk_cols})")
    return [f"CREATE TABLE {t} (\n  " + ",\n  ".join(cols) + "\n)"]


def index_ddl(spec: dict, schema: str) -> list[str]:
    t = f"[{schema}].[{spec['table']}]"
    return [f"CREATE INDEX [{name}] ON {t} (" + ", ".join(f"[{c}]" for c in cols) + ")"
            for name, cols in spec["indexes"]]


# ---------------------------------------------------------------- conexión

def connect():
    import pymssql  # import tardío: --dry-run no requiere driver

    missing = [v for v in ("HOST", "DB", "USER", "PASSWORD")
               if not os.environ.get(f"COMPRASAI_SQLSERVER_{v}")]
    if missing:
        sys.exit(f"Faltan variables COMPRASAI_SQLSERVER_{{{','.join(missing)}}}")
    env = os.environ
    return pymssql.connect(
        server=env["COMPRASAI_SQLSERVER_HOST"],
        port=env.get("COMPRASAI_SQLSERVER_PORT", "1433"),
        database=env["COMPRASAI_SQLSERVER_DB"],
        user=env["COMPRASAI_SQLSERVER_USER"],
        password=env["COMPRASAI_SQLSERVER_PASSWORD"],
        login_timeout=15,
        autocommit=False,
    )


def _ensure_schemas(cur) -> None:
    for s in (STG, OLD):
        cur.execute(f"IF SCHEMA_ID('{s}') IS NULL EXEC('CREATE SCHEMA [{s}]')")
    cur.execute("""
        IF OBJECT_ID('dbo.snapshot_runs') IS NULL
        CREATE TABLE dbo.snapshot_runs (
          id INT IDENTITY PRIMARY KEY,
          started_utc DATETIME2 NOT NULL,
          finished_utc DATETIME2 NULL,
          source_file NVARCHAR(400) NOT NULL,
          tables_loaded INT NULL,
          rows_loaded BIGINT NULL,
          status NVARCHAR(20) NOT NULL,
          error NVARCHAR(MAX) NULL)""")


def _drop_schema_tables(cur, schema: str) -> None:
    cur.execute("SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID(%s)", (schema,))
    for (name,) in cur.fetchall():
        cur.execute(f"DROP TABLE [{schema}].[{name}]")


# ---------------------------------------------------------------- carga

def _batches(rows: Iterable[tuple], size: int) -> Iterable[list[tuple]]:
    batch = []
    for r in rows:
        batch.append(r)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def load_table(src: sqlite3.Connection, conn, spec: dict) -> int:
    cols = [c["name"] for c in spec["columns"]]
    per_insert = max(1, min(MAX_ROWS_PER_INSERT, MAX_PARAMS // len(cols)))
    row_ph = "(" + ", ".join(["%s"] * len(cols)) + ")"
    head = (f"INSERT INTO [{STG}].[{spec['table']}] ("
            + ", ".join(f"[{c}]" for c in cols) + ") VALUES ")
    select = "SELECT " + ", ".join(f'"{c}"' for c in cols) + f' FROM "{spec["table"]}"'
    cur, total = conn.cursor(), 0
    for batch in _batches(src.execute(select), per_insert):
        sql = head + ", ".join([row_ph] * len(batch))
        cur.execute(sql, tuple(v for row in batch for v in row))
        total += len(batch)
        if total % 200_000 < per_insert:
            conn.commit()
    conn.commit()
    return total


def swap_into_dbo(conn, tables: list[str]) -> None:
    """Intercambia stg -> dbo en una sola transacción."""
    cur = conn.cursor()
    _drop_schema_tables(cur, OLD)
    for t in tables:
        cur.execute(f"IF OBJECT_ID('[{DBO}].[{t}]') IS NOT NULL "
                    f"ALTER SCHEMA [{OLD}] TRANSFER [{DBO}].[{t}]")
        cur.execute(f"ALTER SCHEMA [{DBO}] TRANSFER [{STG}].[{t}]")
    conn.commit()
    _drop_schema_tables(cur, OLD)
    conn.commit()


def run(sqlite_path: str, dry_run: bool) -> int:
    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    tables = [r[0] for r in src.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        if r[0] not in SKIP_TABLES]
    specs = [table_spec(src, t) for t in tables]
    if dry_run:
        for s in specs:
            print(";\n".join(create_ddl(s, DBO) + index_ddl(s, DBO)) + ";\n")
        return 0

    conn = connect()
    cur = conn.cursor()
    _ensure_schemas(cur)
    cur.execute("INSERT INTO dbo.snapshot_runs (started_utc, source_file, status) "
                "OUTPUT INSERTED.id VALUES (%s, %s, 'running')",
                (datetime.now(timezone.utc).replace(tzinfo=None), sqlite_path))
    run_id = cur.fetchone()[0]
    conn.commit()
    try:
        _drop_schema_tables(cur, STG)
        total = 0
        for s in specs:
            t0 = time.time()
            for ddl in create_ddl(s, STG):
                cur.execute(ddl)
            conn.commit()
            n = load_table(src, conn, s)
            for ddl in index_ddl(s, STG):
                cur.execute(ddl)
            conn.commit()
            total += n
            print(f"  {s['table']:34} {n:>10} filas  {time.time() - t0:6.1f}s", flush=True)
        swap_into_dbo(conn, tables)
        cur.execute("UPDATE dbo.snapshot_runs SET finished_utc=SYSUTCDATETIME(), "
                    "tables_loaded=%s, rows_loaded=%s, status='ok' WHERE id=%s",
                    (len(tables), total, run_id))
        conn.commit()
        print(f"OK: {len(tables)} tablas, {total} filas (run {run_id})")
        return 0
    except Exception as exc:  # se registra y se propaga el código de salida
        conn.rollback()
        cur.execute("UPDATE dbo.snapshot_runs SET finished_utc=SYSUTCDATETIME(), "
                    "status='error', error=%s WHERE id=%s", (str(exc)[:4000], run_id))
        conn.commit()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
        src.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sqlite", required=True, help="Dataset SQLite de los extractores")
    ap.add_argument("--dry-run", action="store_true", help="Solo imprime el DDL")
    args = ap.parse_args()
    sys.exit(run(args.sqlite, args.dry_run))


if __name__ == "__main__":
    main()
