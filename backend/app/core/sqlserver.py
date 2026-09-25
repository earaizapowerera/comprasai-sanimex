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

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence

logger = logging.getLogger("comprasai.sqlserver")
# pytds registra cada sentencia en INFO: ruido en producción.
logging.getLogger("pytds").setLevel(logging.WARNING)

APP_SCHEMA_SQL = Path(__file__).with_name("sqlserver_app_schema.sql")

_ENV = ("HOST", "PORT", "DB", "USER", "PASSWORD")


def enabled() -> bool:
    """SQL Server se activa definiendo COMPRASAI_SQLSERVER_HOST."""
    return bool(os.environ.get("COMPRASAI_SQLSERVER_HOST"))


# ---------------------------------------------------------------- traducción

_LIMIT_OFFSET = re.compile(r"\bLIMIT\s+(\?|\d+|:\w+)\s+OFFSET\s+(\?|\d+|:\w+)\s*;?\s*$",
                           re.IGNORECASE)
_LIMIT = re.compile(r"\bLIMIT\s+(\?|\d+|:\w+)\s*;?\s*$", re.IGNORECASE)
# SQLite: LIKE ignora mayúsculas (ASCII). El texto se guarda en colación
# binaria, así que LIKE se evalúa explícitamente en CI_AS.
_LIKE = re.compile(r"([\w.\]\[]+)\s+LIKE\b", re.IGNORECASE)
LIKE_COLLATION = "Latin1_General_100_CI_AS"

# LIMIT dentro de un subquery/CTE (sin paréntesis internos) -> TOP n.
_SUBQUERY_LIMIT = re.compile(r"\(\s*SELECT\s+(DISTINCT\s+)?([^()]*?)\s+LIMIT\s+(\d+)\s*\)",
                             re.IGNORECASE)
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
    # pytds aplica `sql % params` a TODO el texto (siempre se le pasan params,
    # aunque sea una tupla vacía), así que el % de un literal ('PET%') también
    # se escapa.
    out = []
    for is_lit, text in _split_literals(sql):
        text = text.replace("%", "%%")
        if not is_lit:
            text = text.replace("?", "%s")
            text = _NAMED.sub(r"%(\1)s", text)
        out.append(text)
    return "".join(out)


# SQL Server acepta máx. 2100 parámetros por request; los motores arman
# `IN (?,?,...)` con miles de materiales. Arriba de este umbral la lista viaja
# como UN parámetro JSON y se abre con OPENJSON (sigue parametrizado).
_IN_LIST = re.compile(r"\bIN\s*\(\s*\?(?:\s*,\s*\?)*\s*\)", re.IGNORECASE)
IN_LIST_MAX = 100


def _collapse_in_lists(sql: str, params: Any) -> tuple[str, Any]:
    if not isinstance(params, (list, tuple)) or len(params) <= IN_LIST_MAX:
        return sql, params
    params, out_sql, out_params, idx = list(params), [], [], 0
    for is_lit, text in _split_literals(sql):
        if is_lit:
            out_sql.append(text)
            continue
        pos = 0
        for m in _IN_LIST.finditer(text):
            before = text[pos:m.start()]
            n_before = before.count("?")
            out_params += params[idx:idx + n_before]
            idx += n_before
            n = m.group(0).count("?")
            values = params[idx:idx + n]
            idx += n
            if n <= IN_LIST_MAX:
                out_sql.append(before + m.group(0))
                out_params += values
            else:
                numeric = all(isinstance(v, int) and not isinstance(v, bool) for v in values)
                col = "BIGINT" if numeric else "NVARCHAR(450)"
                out_sql.append(before + f"IN (SELECT v FROM OPENJSON(?) WITH (v {col} '$'))")
                out_params.append(json.dumps(values, default=str))
            pos = m.end()
        rest = text[pos:]
        out_params += params[idx:idx + rest.count("?")]
        idx += rest.count("?")
        out_sql.append(rest)
    return "".join(out_sql), out_params


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
    sql, params = _collapse_in_lists(sql, params)
    sql = _LIKE.sub(lambda m: f"{m.group(1)} COLLATE {LIKE_COLLATION} LIKE", sql)
    sql = _SUBQUERY_LIMIT.sub(lambda m: f"(SELECT {m.group(1) or ''}TOP {m.group(3)} {m.group(2)})", sql)

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
    def __init__(self, rows: list[dict], rowcount: int, description, raw=None):
        self._rows, self.rowcount, self.description = rows, rowcount, description
        self._raw = raw

    @property
    def lastrowid(self) -> Optional[int]:
        """Último IDENTITY de la sesión. SCOPE_IDENTITY() no sirve aquí: cada
        sentencia parametrizada corre en su propio scope (sp_executesql). Las
        tablas `app` no tienen triggers, así que @@IDENTITY es exacto."""
        if self._raw is None:
            return None
        cur = self._raw.cursor()
        cur.execute("SELECT CAST(@@IDENTITY AS BIGINT) AS id")
        row = cur.fetchone()
        return row["id"] if row else None

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
        return _Cursor(list(rows), cur.rowcount, cur.description, self._raw)

    def executemany(self, sql: str, seq_of_params) -> _Cursor:
        tsql, _ = translate(sql, None)
        if tsql is None:
            return _EMPTY
        cur = self._raw.cursor()
        cur.executemany(tsql, [tuple(p) if isinstance(p, list) else p for p in seq_of_params])
        return _Cursor([], cur.rowcount, None)

    def executescript(self, script: str) -> None:
        """Solo DDL de tablas auxiliares (CREATE TABLE IF NOT EXISTS), que en
        SQL Server ya provisiona sqlserver_app_schema.sql."""
        for stmt in script.split(";"):
            if stmt.strip():
                self.execute(stmt)

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


_BORN: set[str] = set()


def born_this_run(table: str) -> bool:
    """True si `table` la creó ensure_app_schema en este arranque. Equivale al
    "la tabla acaba de nacer" con el que SQLite decide sembrar ejemplos."""
    return table in _BORN


def _app_tables(raw) -> set[str]:
    cur = raw.cursor()
    cur.execute("SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID('app')")
    return {r["name"] for r in cur.fetchall()}


def ensure_app_schema(conn: SqlServerConnection) -> None:
    """Crea (idempotente) el schema `app` y sus sinónimos en dbo."""
    raw = conn._raw
    before = _app_tables(raw)
    for batch in re.split(r"^\s*GO\s*$", APP_SCHEMA_SQL.read_text(), flags=re.MULTILINE):
        if batch.strip():
            cur = raw.cursor()
            cur.execute(batch)
    raw.commit()
    _BORN.update(_app_tables(raw) - before)
