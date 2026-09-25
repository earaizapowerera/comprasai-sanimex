"""Conexión a SQL Server (snapshot diario en dbdev) con la MISMA interfaz que
los routers ya usan sobre sqlite3: `db.execute(sql, params)` devuelve un
cursor cuyas filas son dicts, más `executemany`, `commit`, `rollback`,
`close`. Así los motores no cambian de contrato al mover el almacenamiento.

El SQL de los routers se escribe en el dialecto común de SQLite/T-SQL. Lo
poco que es mecánicamente distinto se traduce aquí (placeholders, LIMIT,
PRAGMA, sqlite_master); lo que no es mecánico (upserts, ORDER BY sobre
booleanos) se escribió portable en el propio router.

Las tablas de configuración/decisiones de usuarios viven en el schema `app`
(ver sqlserver_app_schema.sql) y se exponen en `dbo` con sinónimos, porque el
swap diario del snapshot (data/load_sqlserver.py) reemplaza `dbo`.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence

logger = logging.getLogger("comprasai.sqlserver")

APP_SCHEMA_SQL = Path(__file__).with_name("sqlserver_app_schema.sql")

_ENV = ("HOST", "PORT", "DB", "USER", "PASSWORD")


def enabled() -> bool:
    """SQL Server se activa definiendo COMPRASAI_SQLSERVER_HOST."""
    return bool(os.environ.get("COMPRASAI_SQLSERVER_HOST"))


# ---------------------------------------------------------------- traducción

_LIMIT_OFFSET = re.compile(r"\bLIMIT\s+(\?|\d+|:\w+)\s+OFFSET\s+(\?|\d+|:\w+)\s*;?\s*$",
                           re.IGNORECASE)
_LIMIT = re.compile(r"\bLIMIT\s+(\?|\d+|:\w+)\s*;?\s*$", re.IGNORECASE)
_NAMED = re.compile(r"(?<!:):([A-Za-z_]\w*)")
_PRAGMA_TABLE_INFO = re.compile(r"^\s*PRAGMA\s+table_info\s*\(\s*['\"]?(\w+)['\"]?\s*\)\s*$",
                                re.IGNORECASE)
_SQLITE_MASTER = re.compile(r"\bFROM\s+sqlite_master\s+WHERE\s+type\s*=\s*'table'", re.IGNORECASE)
_DDL_NOOP = re.compile(r"^\s*(PRAGMA\b|CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\b"
                       r"|ALTER\s+TABLE\s+\w+\s+ADD\s+COLUMN\b)",
                       re.IGNORECASE)


def _split_literals(sql: str) -> list[tuple[bool, str]]:
    """Parte el SQL en tramos (es_literal, texto) para no tocar '...'."""
    parts, buf, in_str, i = [], [], False, 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            if in_str and i + 1 < len(sql) and sql[i + 1] == "'":
                buf.append("''")
                i += 2
                continue
            if not in_str:
                parts.append((False, "".join(buf)))
                buf = ["'"]
            else:
                buf.append("'")
                parts.append((True, "".join(buf)))
                buf = []
            in_str = not in_str
        else:
            buf.append(ch)
        i += 1
    parts.append((in_str, "".join(buf)))
    return parts


def _placeholders(sql: str) -> str:
    out = []
    for is_lit, text in _split_literals(sql):
        if not is_lit:
            text = text.replace("%", "%%").replace("?", "%s")
            text = _NAMED.sub(r"%(\1)s", text)
        out.append(text)
    return "".join(out)


def translate(sql: str, params: Any) -> tuple[Optional[str], Any]:
    """SQLite -> T-SQL. Devuelve (None, _) si la sentencia es un no-op."""
    m = _PRAGMA_TABLE_INFO.match(sql)
    if m:
        # Resuelve sinónimos (dbo.x -> app.x) antes de listar columnas.
        return ("SELECT c.name AS name FROM sys.columns c WHERE c.object_id = COALESCE("
                "OBJECT_ID((SELECT base_object_name FROM sys.synonyms WHERE name = %s)), "
                "OBJECT_ID(%s))", (m.group(1), m.group(1)))
    if _DDL_NOOP.match(sql):
        # Esquema de configuración provisionado por sqlserver_app_schema.sql.
        return None, params
    sql = _SQLITE_MASTER.sub("FROM sys.objects WHERE type IN ('U', 'SN')", sql)

    m = _LIMIT_OFFSET.search(sql)
    if m:
        lim, off = m.group(1), m.group(2)
        sql = sql[:m.start()] + f"OFFSET {off} ROWS FETCH NEXT {lim} ROWS ONLY"
        if lim == "?" and off == "?" and isinstance(params, (list, tuple)):
            params = list(params[:-2]) + [params[-1], params[-2]]
    else:
        m = _LIMIT.search(sql)
        if m:
            sql = sql[:m.start()] + f"OFFSET 0 ROWS FETCH NEXT {m.group(1)} ROWS ONLY"
    return _placeholders(sql), params


# ---------------------------------------------------------------- conexión

class _Cursor:
    def __init__(self, rows: list[dict], rowcount: int, description):
        self._rows, self.rowcount, self.description = rows, rowcount, description

    def fetchone(self) -> Optional[dict]:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[dict]:
        rows, self._rows = self._rows, []
        return rows

    def __iter__(self) -> Iterator[dict]:
        return iter(self.fetchall())


_EMPTY = _Cursor([], -1, None)


class SqlServerConnection:
    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql: str, params: Sequence | dict | None = None) -> _Cursor:
        tsql, params = translate(sql, params or ())
        if tsql is None:
            return _EMPTY
        cur = self._raw.cursor()
        cur.execute(tsql, tuple(params) if isinstance(params, list) else params)
        rows = cur.fetchall() if cur.description else []
        return _Cursor(list(rows), cur.rowcount, cur.description)

    def executemany(self, sql: str, seq_of_params) -> _Cursor:
        tsql, _ = translate(sql, None)
        if tsql is None:
            return _EMPTY
        cur = self._raw.cursor()
        cur.executemany(tsql, [tuple(p) if isinstance(p, list) else p for p in seq_of_params])
        return _Cursor([], cur.rowcount, None)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()


def describe() -> str:
    """Identificador para logs/health, sin host ni credenciales."""
    return f"sqlserver:{os.environ.get('COMPRASAI_SQLSERVER_DB', '')}"


def last_snapshot(conn: SqlServerConnection) -> Optional[dict]:
    """Última carga exitosa: es la fecha de corte de la ruta analítica."""
    return conn.execute(
        "SELECT TOP 1 id, finished_utc, tables_loaded, rows_loaded FROM dbo.snapshot_runs "
        "WHERE status = 'ok' ORDER BY finished_utc DESC").fetchone()


def connect() -> SqlServerConnection:
    import pytds

    env = {k: os.environ.get(f"COMPRASAI_SQLSERVER_{k}", "") for k in _ENV}
    raw = pytds.connect(
        server=env["HOST"], port=int(env["PORT"] or 1433), database=env["DB"],
        user=env["USER"], password=env["PASSWORD"], as_dict=True,
        autocommit=False, login_timeout=15, timeout=120,
    )
    return SqlServerConnection(raw)


def ensure_app_schema(conn: SqlServerConnection) -> None:
    """Crea (idempotente) el schema `app` y sus sinónimos en dbo."""
    raw = conn._raw
    for batch in re.split(r"^\s*GO\s*$", APP_SCHEMA_SQL.read_text(), flags=re.MULTILINE):
        if batch.strip():
            cur = raw.cursor()
            cur.execute(batch)
    raw.commit()
