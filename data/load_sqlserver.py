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
from typing import Optional

# Tablas internas de SQLite que no forman parte del dataset.
SKIP_TABLES = {"sqlite_sequence", "sqlite_stat1", "sqlite_stat4"}
STG, DBO, OLD = "stg", "dbo", "old"
LOCK_NAME = "comprasai_snapshot_load"
# Colación binaria en todo texto: reproduce la semántica de SQLite (igualdad,
# DISTINCT y ORDER BY sensibles a mayúsculas, orden por code point). Con la
# colación CI de la base, DISTINCT fusionaba 'Ceramica X' con 'CERAMICA X' y
# ORDER BY cambiaba el orden (y con él las muestras deterministas del API).
# Debe coincidir con backend/app/core/sqlserver_app_schema.sql.
TEXT_COLLATION = "Latin1_General_100_BIN2"
# El swap necesita stg + dbo a la vez (~2x). Sin compresión el v7 ocupa ~2.9 GB
# y la carga llenó el disco de dbdev (25-sep-2026). PAGE reduce ~70%.
COMPRESSION = "DATA_COMPRESSION = PAGE"
# Errores de servidor donde reintentar no sirve (1105: filegroup lleno,
# 9002: log lleno): se aborta de inmediato para no seguir escribiendo.
NO_RETRY_ERRORS = ("filegroup is full", "transaction log for database")
SOCKET_TIMEOUT_S = 900
TABLE_ATTEMPTS = 3
# Configuración y decisiones de usuarios (PUT de remates/balanceos, descartes).
# NO son snapshot: las crea y siembra el backend en el schema `app`
# (backend/app/core/sqlserver_app_schema.sql) y este cargador no las toca.
APP_TABLES = {
    "balanceo_costo_corredor", "balanceo_descarte", "balanceo_pendiente",
    "balanceo_prioridad_default", "balanceo_prioridad_excepcion",
    "balanceo_umbral_dias_pedido", "meses_objetivo_default", "meses_objetivo_excepcion",
    "remate_escalas", "remate_plazas_excepcion", "remate_rutas_gam", "sugeridos_generados",
    "lotes_compra", "lotes_compra_clasificacion", "sucursal_compra", "sucursal_compra_config",
    "sucursal_compra_evidencia", "sucursal_compra_override",
}


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
    cols = [f"[{c['name']}] {c['type']}"
            f"{' COLLATE ' + TEXT_COLLATION if c['type'].startswith('NVARCHAR') else ''}"
            f"{' NOT NULL' if c['not_null'] else ''}"
            for c in spec["columns"]]
    if spec["pk"]:
        pk_cols = ", ".join(f"[{c}]" for c in spec["pk"])
        cols.append(f"CONSTRAINT [PK_{spec['table']}] PRIMARY KEY ({pk_cols})")
    return [f"CREATE TABLE {t} (\n  " + ",\n  ".join(cols) + f"\n) WITH ({COMPRESSION})"]


def index_ddl(spec: dict, schema: str) -> list[str]:
    t = f"[{schema}].[{spec['table']}]"
    return [f"CREATE INDEX [{name}] ON {t} (" + ", ".join(f"[{c}]" for c in cols)
            + f") WITH ({COMPRESSION})" for name, cols in spec["indexes"]]


# ---------------------------------------------------------------- conexión

def connect():
    # pytds (python-tds, TDS puro): soporta INSERT BULK nativo. Con INSERT
    # parametrizado el v7 (12.4 M filas) cargaba a ~170 filas/s -> horas.
    import pytds  # import tardío: --dry-run no requiere driver

    missing = [v for v in ("HOST", "DB", "USER", "PASSWORD")
               if not os.environ.get(f"COMPRASAI_SQLSERVER_{v}")]
    if missing:
        sys.exit(f"Faltan variables COMPRASAI_SQLSERVER_{{{','.join(missing)}}}")
    env = os.environ
    return pytds.connect(
        server=env["COMPRASAI_SQLSERVER_HOST"],
        port=int(env.get("COMPRASAI_SQLSERVER_PORT", "1433")),
        database=env["COMPRASAI_SQLSERVER_DB"],
        user=env["COMPRASAI_SQLSERVER_USER"],
        password=env["COMPRASAI_SQLSERVER_PASSWORD"],
        login_timeout=15,
        # Sin timeout de socket, una conexión que se cae a media carga (VPN,
        # NAT) deja al proceso esperando para siempre y la corrida huérfana.
        timeout=SOCKET_TIMEOUT_S,
        autocommit=False,
    )


def sql(conn, stmt: str, params: tuple = (), commit: bool = False) -> list:
    """Ejecuta con un cursor nuevo: pytds cierra los cursores en cada commit."""
    cur = conn.cursor()
    cur.execute(stmt, params)
    rows = cur.fetchall() if cur.description else []
    if commit:
        conn.commit()
    return rows


def _ensure_schemas(conn) -> None:
    for s in (STG, OLD):
        sql(conn, f"IF SCHEMA_ID('{s}') IS NULL EXEC('CREATE SCHEMA [{s}]')")
    sql(conn, """
        IF OBJECT_ID('dbo.snapshot_runs') IS NULL
        CREATE TABLE dbo.snapshot_runs (
          id INT IDENTITY PRIMARY KEY,
          started_utc DATETIME2 NOT NULL,
          finished_utc DATETIME2 NULL,
          source_file NVARCHAR(400) NOT NULL,
          tables_loaded INT NULL,
          rows_loaded BIGINT NULL,
          status NVARCHAR(20) NOT NULL,
          error NVARCHAR(MAX) NULL)""", commit=True)
    # Hora de corte de los datos (mtime del SQLite que produjo el extractor);
    # started_utc es la hora de CARGA, que puede ser días después.
    sql(conn, "IF COL_LENGTH('dbo.snapshot_runs', 'data_cutoff_utc') IS NULL "
              "ALTER TABLE dbo.snapshot_runs ADD data_cutoff_utc DATETIME2 NULL", commit=True)


def _drop_schema_tables(conn, schema: str) -> None:
    for (name,) in sql(conn, "SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID(%s)",
                       (schema,)):
        sql(conn, f"DROP TABLE [{schema}].[{name}]")


# ---------------------------------------------------------------- carga

def _bulk_columns(spec: dict) -> list:
    """Metadatos tipados para INSERT BULK (sin ellos pytds asume NVARCHAR)."""
    from pytds import tds_base, tds_types

    out = []
    for c in spec["columns"]:
        t = c["type"]
        if t == "BIGINT":
            typ = tds_types.BigIntType()
        elif t == "FLOAT":
            typ = tds_types.FloatType()
        elif t == "NVARCHAR(MAX)":
            typ = tds_types.NVarCharMaxType()
        else:
            typ = tds_types.NVarCharType(size=int(t[len("NVARCHAR("):-1]))
        flags = 0 if c["not_null"] else tds_base.Column.fNullable
        out.append(tds_base.Column(name=c["name"], type=typ, flags=flags))
    return out


def load_table(src: sqlite3.Connection, conn, spec: dict, schema: str = STG) -> int:
    cols = [c["name"] for c in spec["columns"]]
    select = "SELECT " + ", ".join(f'"{c}"' for c in cols) + f' FROM "{spec["table"]}"'
    cur = conn.cursor()
    cur.copy_to(table_or_view=spec["table"], schema=schema, columns=_bulk_columns(spec),
                data=src.execute(select), keep_nulls=True, tablock=True)
    conn.commit()
    return sql(conn, f"SELECT COUNT_BIG(*) FROM [{schema}].[{spec['table']}]")[0][0]


def swap_into_dbo(conn, tables: list[str]) -> None:
    """Intercambia stg -> dbo en una sola transacción."""
    _drop_schema_tables(conn, OLD)
    for t in tables:
        sql(conn, f"IF OBJECT_ID('[{DBO}].[{t}]') IS NOT NULL "
                  f"ALTER SCHEMA [{OLD}] TRANSFER [{DBO}].[{t}]")
        sql(conn, f"ALTER SCHEMA [{DBO}] TRANSFER [{STG}].[{t}]")
    conn.commit()
    _drop_schema_tables(conn, OLD)
    conn.commit()


def _acquire_lock(conn) -> None:
    """Una sola carga a la vez: el lock de sesión muere con la conexión, así que
    un proceso caído no deja el candado puesto."""
    rc = sql(conn, "SET NOCOUNT ON; DECLARE @rc INT; EXEC @rc = sp_getapplock @Resource=%s, "
                   "@LockMode='Exclusive', @LockOwner='Session', @LockTimeout=0; SELECT @rc",
             (LOCK_NAME,))[0][0]
    if rc < 0:
        sys.exit("Otra carga del snapshot está en curso; abortando sin tocar nada.")


def _close_orphan_runs(conn) -> None:
    """Con el lock tomado, cualquier corrida 'running' es de un proceso muerto."""
    n = sql(conn, "SET NOCOUNT ON; UPDATE dbo.snapshot_runs SET status='aborted', finished_utc=SYSUTCDATETIME(), "
                  "error='Proceso terminó sin cerrar la corrida (detectado por la siguiente carga)' "
                  "WHERE status='running'; SELECT @@ROWCOUNT", commit=True)[0][0]
    if n:
        print(f"  {n} corrida(s) huérfana(s) marcadas como aborted", flush=True)


def _open(conn=None):
    """Conexión nueva con el candado de carga tomado (el candado es de sesión)."""
    if conn is not None:
        try:
            conn.close()
        except Exception:  # la conexión vieja ya puede estar muerta
            pass
    conn = connect()
    _acquire_lock(conn)
    return conn


def _record_failure(conn, run_id: int, exc: Exception):
    """Marca la corrida en error y libera stg (dbo queda intacto). Si la
    conexión murió, reabre una: la corrida nunca debe quedar en 'running'."""
    for attempt in (1, 2):
        try:
            if attempt == 2:
                conn = _open(conn)
            conn.rollback()
            _drop_schema_tables(conn, STG)
            sql(conn, "UPDATE dbo.snapshot_runs SET finished_utc=SYSUTCDATETIME(), "
                      "status='error', error=%s WHERE id=%s", (str(exc)[:4000], run_id), commit=True)
            return conn
        except Exception as again:
            if attempt == 2:
                print(f"No se pudo registrar el error de la corrida {run_id}: {again}", file=sys.stderr)
    return conn


def stage_table(src: sqlite3.Connection, conn, spec: dict):
    """Crea y carga una tabla en stg, reintentando con conexión nueva si la red
    se cae. Devuelve (conexión vigente, filas)."""
    for attempt in range(1, TABLE_ATTEMPTS + 1):
        try:
            sql(conn, f"IF OBJECT_ID('[{STG}].[{spec['table']}]') IS NOT NULL "
                      f"DROP TABLE [{STG}].[{spec['table']}]")
            for ddl in create_ddl(spec, STG):
                sql(conn, ddl)
            conn.commit()
            n = load_table(src, conn, spec)
            for ddl in index_ddl(spec, STG):
                sql(conn, ddl)
            conn.commit()
            return conn, n
        except Exception as exc:
            if attempt == TABLE_ATTEMPTS or any(e in str(exc) for e in NO_RETRY_ERRORS):
                raise
            print(f"  {spec['table']}: intento {attempt} falló ({exc}); reconectando", flush=True)
            time.sleep(10 * attempt)
            conn = _open(conn)
    raise AssertionError("inalcanzable")


def run(sqlite_path: str, dry_run: bool, only: Optional[set] = None) -> int:
    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    tables = [r[0] for r in src.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        if r[0] not in SKIP_TABLES and (not only or r[0] in only)]
    specs = [table_spec(src, t) for t in tables if t not in APP_TABLES]
    tables = [s["table"] for s in specs]
    if dry_run:
        for s in specs:
            print(";\n".join(create_ddl(s, DBO) + index_ddl(s, DBO)) + ";\n")
        return 0

    conn = _open()
    _ensure_schemas(conn)
    _close_orphan_runs(conn)
    cutoff = datetime.fromtimestamp(os.path.getmtime(sqlite_path), timezone.utc).replace(tzinfo=None)
    run_id = sql(conn, "INSERT INTO dbo.snapshot_runs (started_utc, source_file, data_cutoff_utc, status) "
                       "OUTPUT INSERTED.id VALUES (%s, %s, %s, 'running')",
                 (datetime.now(timezone.utc).replace(tzinfo=None), sqlite_path, cutoff), commit=True)[0][0]
    try:
        _drop_schema_tables(conn, STG)
        total = 0
        for s in specs:
            t0 = time.time()
            conn, n = stage_table(src, conn, s)
            total += n
            print(f"  {s['table']:34} {n:>10} filas  {time.time() - t0:6.1f}s", flush=True)
        swap_into_dbo(conn, tables)
        sql(conn, "UPDATE dbo.snapshot_runs SET finished_utc=SYSUTCDATETIME(), "
                  "tables_loaded=%s, rows_loaded=%s, status='ok' WHERE id=%s",
            (len(tables), total, run_id), commit=True)
        print(f"OK: {len(tables)} tablas, {total} filas (run {run_id})")
        return 0
    except Exception as exc:  # se registra y se propaga el código de salida
        print(f"ERROR: {exc}", file=sys.stderr)
        conn = _record_failure(conn, run_id, exc)
        return 1
    finally:
        conn.close()
        src.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sqlite", required=True, help="Dataset SQLite de los extractores")
    ap.add_argument("--dry-run", action="store_true", help="Solo imprime el DDL")
    ap.add_argument("--tables", help="Lista separada por comas (pruebas); default todas")
    args = ap.parse_args()
    only = set(args.tables.split(",")) if args.tables else None
    sys.exit(run(args.sqlite, args.dry_run, only))


if __name__ == "__main__":
    main()
