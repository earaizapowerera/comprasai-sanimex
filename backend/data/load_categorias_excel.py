"""
Loader FILL-GAPS de categorías mensuales (T29, punto 5, waykee 291788).

Fuente hoy: el Excel muestra-compras.xlsb (hoja ARAGON) que entrega el área de
compras. Fila header = índice 4, con UNA columna por mes en las columnas 9 a
28 -- el header de esas columnas es un SERIAL DE FECHA de Excel (no texto),
por eso una búsqueda de texto por "categoria" no la encuentra. Datos desde la
fila índice 6: columna 0 = material_id, columnas 9-28 = categoría de ese mes.

FILL-GAPS: solo INSERTa (material_id, anio_mes) que NO existan ya en
categorias_mensuales -- nunca pisa filas ya sembradas por la tabla oficial
v7/HANA (hoy 2026-01..07). El Excel aporta 2025-01..12 y 2026-08, que es
justo lo que falta (ver mensaje puente 290066->291788).

Uso:
    python -m data.load_categorias_excel [--db PATH] [--excel PATH] [--sheet ARAGON]
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from pyxlsb import open_workbook

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BACKEND_DIR / "data" / "comprasai.db"
DEFAULT_EXCEL_PATH = Path("/tmp/wk291788/muestra-compras.xlsb")
DEFAULT_SHEET = "ARAGON"

HEADER_ROW_IDX = 4
DATA_START_IDX = 6
MATERIAL_COL = 0
CATEGORIA_COLS = range(9, 29)

EXCEL_EPOCH = date(1899, 12, 30)


def serial_a_anio_mes(serial: float) -> str:
    d = EXCEL_EPOCH + timedelta(days=int(serial))
    return f"{d.year:04d}-{d.month:02d}"


def leer_categorias(excel_path: Path, sheet_name: str) -> list[tuple[str, str, str]]:
    """Regresa una lista de (material_id, anio_mes, categoria) leída del Excel,
    saltando celdas de categoría NULL/vacías y filas sin material_id."""
    with open_workbook(str(excel_path)) as wb:
        with wb.get_sheet(sheet_name) as sheet:
            header: dict[int, object] = {}
            filas: list[dict[int, object]] = []
            for i, row in enumerate(sheet.rows()):
                if i == HEADER_ROW_IDX:
                    header = {cell.c: cell.v for cell in row}
                elif i >= DATA_START_IDX:
                    filas.append({cell.c: cell.v for cell in row})

    meses_por_col = {col: serial_a_anio_mes(header[col]) for col in CATEGORIA_COLS}

    triples: list[tuple[str, str, str]] = []
    for fila in filas:
        material_id = fila.get(MATERIAL_COL)
        if not material_id:
            continue
        for col, anio_mes in meses_por_col.items():
            categoria = fila.get(col)
            if categoria in (None, ""):
                continue
            triples.append((str(material_id), anio_mes, str(categoria)))
    return triples


def insertar_fill_gaps(conn: sqlite3.Connection, triples: list[tuple[str, str, str]]) -> tuple[int, int]:
    """INSERT OR IGNORE de (material_id, anio_mes, categoria) -- FILL-GAPS: si
    la pareja (material_id, anio_mes) ya existe (p.ej. sembrada por la tabla
    oficial v7/HANA), la fila entrante se descarta sin pisar el dato existente.
    Regresa (filas_antes, filas_despues)."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS categorias_mensuales (
            material_id TEXT NOT NULL,
            anio_mes    TEXT NOT NULL,
            categoria   TEXT NOT NULL,
            PRIMARY KEY (material_id, anio_mes)
        )"""
    )
    antes = conn.execute("SELECT COUNT(*) FROM categorias_mensuales").fetchone()[0]
    conn.executemany(
        """INSERT OR IGNORE INTO categorias_mensuales (material_id, anio_mes, categoria)
           VALUES (?, ?, ?)""",
        triples,
    )
    conn.commit()
    despues = conn.execute("SELECT COUNT(*) FROM categorias_mensuales").fetchone()[0]
    return antes, despues


def cargar(db_path: Path, excel_path: Path, sheet_name: str) -> None:
    triples = leer_categorias(excel_path, sheet_name)
    print(f"[load_categorias] {len(triples):,} filas leídas de {excel_path} (hoja {sheet_name})")

    conn = sqlite3.connect(str(db_path))
    try:
        antes, despues = insertar_fill_gaps(conn, triples)
    finally:
        conn.close()

    print(f"[load_categorias] categorias_mensuales: {antes:,} -> {despues:,} filas ({despues - antes:,} nuevas)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Loader FILL-GAPS de categorías mensuales desde el Excel de compras")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Ruta del SQLite destino")
    parser.add_argument("--excel", default=str(DEFAULT_EXCEL_PATH), help="Ruta del .xlsb origen")
    parser.add_argument("--sheet", default=DEFAULT_SHEET, help="Nombre de la hoja")
    args = parser.parse_args()
    cargar(Path(args.db), Path(args.excel), args.sheet)


if __name__ == "__main__":
    main()
