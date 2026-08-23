"""Helpers de conexión a SQLite. Sin ORM a propósito: el contrato de datos
(ver core/schema.sql) es la interfaz estable entre el generador sintético,
los datos reales de SAP y los motores C1/C2/C3."""

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.core.config import DB_PATH


def _row_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    fields = [col[0] for col in cursor.description]
    return dict(zip(fields, row))


def get_raw_connection() -> sqlite3.Connection:
    # check_same_thread=False: FastAPI resuelve dependencias sync y ejecuta el
    # endpoint vía run_in_threadpool en llamadas *separadas*, que pueden caer en
    # threads distintos del pool para la misma request. La conexión se crea en
    # un thread y se usa en otro -> sqlite3.ProgrammingError sin este flag,
    # visto en vivo como 500 intermitente en cualquier endpoint (p.ej.
    # /api/engines/sugeridos/opciones). El acceso sigue siendo secuencial
    # dentro de una misma request (una conexión por request, cerrada al
    # finalizar), así que es seguro desactivar el chequeo de thread-affinity.
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = _row_factory
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = get_raw_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_db() -> Iterator[sqlite3.Connection]:
    """Dependencia de FastAPI: una conexión por request."""
    with get_connection() as conn:
        yield conn
