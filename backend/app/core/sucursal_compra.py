"""Catálogo sucursal_compra (waykee 292252): qué sucursales compran directo a
proveedor y cuáles se surten solo por traslado.

SAP no trae ese indicador; se infiere de las OCs externas de los últimos 12
meses (evidencia extraída por data/extract_sucursal_compra.py) más el
inventario de la propia app:

  COMPRA_DIRECTA     >= umbral OCs externas/año (default 12, una al mes)
  COMPRA_ESPORADICA  1..umbral-1 OCs; se surte principalmente por traslado
  NO_COMPRA          0 OCs, con inventario: solo recibe por traslado
  SIN_OPERACION      0 OCs y sin inventario (centros de venta/facturación)
  SIN_EVIDENCIA      el centro no aparece en la evidencia -> no se filtra

El planeador puede fijar la clase de un centro (override), que manda sobre la
calculada. Efecto en los motores:
  * Sugeridos / Lotes de Compra: solo COMPRA_DIRECTA (y SIN_EVIDENCIA) generan
    sugeridos de compra.
  * Balanceos: SIN_OPERACION se excluye del universo; el resto participa.
Si el catálogo está vacío (dataset sin evidencia) no se filtra nada: la demo
sigue funcionando igual que antes."""

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from app.core.db import upsert

COMPRA_DIRECTA = "COMPRA_DIRECTA"
COMPRA_ESPORADICA = "COMPRA_ESPORADICA"
NO_COMPRA = "NO_COMPRA"
SIN_OPERACION = "SIN_OPERACION"
SIN_EVIDENCIA = "SIN_EVIDENCIA"
CLASES_OVERRIDE = (COMPRA_DIRECTA, COMPRA_ESPORADICA, NO_COMPRA, SIN_OPERACION)
CLASES_QUE_COMPRAN = {COMPRA_DIRECTA, SIN_EVIDENCIA}

DEFAULT_UMBRAL_OC_ANUAL = 12
CSV_EVIDENCIA = Path(__file__).resolve().parent.parent.parent / "data" / "sucursal_compra_evidencia.csv"
EVIDENCIA_COLS = ("plant", "oc_ext_12m", "lineas_12m", "proveedores_12m", "ult_oc_ext",
                  "oc_ext_24m", "traslados_12m", "ventana_desde", "ventana_hasta", "extraido")

DDL = """
CREATE TABLE IF NOT EXISTS sucursal_compra_evidencia (
    plant TEXT PRIMARY KEY, oc_ext_12m INTEGER NOT NULL DEFAULT 0, lineas_12m INTEGER NOT NULL DEFAULT 0,
    proveedores_12m INTEGER NOT NULL DEFAULT 0, ult_oc_ext TEXT, oc_ext_24m INTEGER NOT NULL DEFAULT 0,
    traslados_12m INTEGER NOT NULL DEFAULT 0, ventana_desde TEXT, ventana_hasta TEXT, extraido TEXT);
CREATE TABLE IF NOT EXISTS sucursal_compra_override (
    plant TEXT PRIMARY KEY, clase TEXT NOT NULL, motivo TEXT, usuario TEXT, actualizado TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sucursal_compra_config (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sucursal_compra (
    plant TEXT PRIMARY KEY, clase TEXT NOT NULL, clase_calculada TEXT NOT NULL, fuente TEXT NOT NULL,
    oc_ext_12m INTEGER, traslados_12m INTEGER, ult_oc_ext TEXT, skus_con_inventario INTEGER,
    umbral_oc_anual INTEGER NOT NULL, generado TEXT NOT NULL);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clasificar(oc_ext_12m: Optional[int], skus_con_inventario: int, umbral: int = DEFAULT_UMBRAL_OC_ANUAL) -> str:
    """Regla pura. oc_ext_12m=None significa que el centro no tiene evidencia."""
    if oc_ext_12m is None:
        return SIN_EVIDENCIA
    if oc_ext_12m >= umbral:
        return COMPRA_DIRECTA
    if oc_ext_12m >= 1:
        return COMPRA_ESPORADICA
    return NO_COMPRA if skus_con_inventario > 0 else SIN_OPERACION


def init_tables(db: sqlite3.Connection) -> None:
    """Crea las tablas y, si la evidencia está vacía, la siembra desde el CSV versionado."""
    db.executescript(DDL)
    vacia = db.execute("SELECT COUNT(*) AS n FROM sucursal_compra_evidencia").fetchone()["n"] == 0
    if vacia and CSV_EVIDENCIA.exists():
        with CSV_EVIDENCIA.open(encoding="utf-8") as f:
            reemplazar_evidencia(db, list(csv.DictReader(f)))
    db.commit()


def reemplazar_evidencia(db: sqlite3.Connection, filas: Iterable[dict]) -> None:
    db.execute("DELETE FROM sucursal_compra_evidencia")
    db.executemany(
        f"INSERT INTO sucursal_compra_evidencia ({','.join(EVIDENCIA_COLS)}) VALUES ({','.join('?' * len(EVIDENCIA_COLS))})",
        [tuple(f.get(c) for c in EVIDENCIA_COLS) for f in filas],
    )
    db.commit()


def get_umbral(db: sqlite3.Connection) -> int:
    row = db.execute("SELECT valor FROM sucursal_compra_config WHERE clave = 'umbral_oc_anual'").fetchone()
    return int(row["valor"]) if row else DEFAULT_UMBRAL_OC_ANUAL


def set_umbral(db: sqlite3.Connection, umbral: int) -> None:
    upsert(db, "sucursal_compra_config", {"clave": "umbral_oc_anual"}, {"valor": str(umbral)})
    db.commit()


def _skus_con_inventario(db: sqlite3.Connection) -> dict:
    rows = db.execute("SELECT plant, SUM(CASE WHEN disponible > 0 THEN 1 ELSE 0 END) AS n FROM inventarios GROUP BY plant")
    return {r["plant"].upper(): int(r["n"] or 0) for r in rows}


def recalcular(db: sqlite3.Connection) -> dict:
    """Reclasifica todas las sucursales. Punto de enganche del cron diario
    (vía balanceos.recalcular_propuestas) y del endpoint de recálculo."""
    init_tables(db)
    umbral = get_umbral(db)
    evidencia = {r["plant"].upper(): r for r in db.execute("SELECT * FROM sucursal_compra_evidencia")}
    overrides = {r["plant"].upper(): r["clase"] for r in db.execute("SELECT plant, clase FROM sucursal_compra_override")}
    inventario = _skus_con_inventario(db)
    generado, filas = _now(), []
    for plant in [r["plant"] for r in db.execute("SELECT plant FROM sucursales").fetchall()]:
        key, ev = plant.upper(), evidencia.get(plant.upper())
        inv = inventario.get(key, 0)
        calculada = clasificar(ev["oc_ext_12m"] if ev else None, inv, umbral) if evidencia else SIN_EVIDENCIA
        clase = overrides.get(key, calculada)
        fuente = "override" if key in overrides else ("sin_evidencia" if calculada == SIN_EVIDENCIA else "calculada")
        filas.append((plant, clase, calculada, fuente, ev["oc_ext_12m"] if ev else None,
                      ev["traslados_12m"] if ev else None, ev["ult_oc_ext"] if ev else None, inv, umbral, generado))
    db.execute("DELETE FROM sucursal_compra")
    db.executemany("INSERT INTO sucursal_compra VALUES (?,?,?,?,?,?,?,?,?,?)", filas)
    db.commit()
    return {"total": len(filas), "umbral_oc_anual": umbral, "generado": generado, "conteo": conteo(db)}


def conteo(db: sqlite3.Connection) -> dict:
    return {r["clase"]: r["n"] for r in db.execute("SELECT clase, COUNT(*) AS n FROM sucursal_compra GROUP BY clase")}


def clases_por_planta(db: sqlite3.Connection) -> dict:
    """{plant: clase}. Vacío si el catálogo no existe o no tiene filas."""
    existe = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sucursal_compra'").fetchone()
    if not existe:
        return {}
    return {r["plant"]: r["clase"] for r in db.execute("SELECT plant, clase FROM sucursal_compra")}


def plantas_sin_compra(db: sqlite3.Connection) -> set:
    """Sucursales que NO deben generar sugeridos de compra directa."""
    return {p for p, c in clases_por_planta(db).items() if c not in CLASES_QUE_COMPRAN}


def plantas_sin_operacion(db: sqlite3.Connection) -> set:
    """Sucursales fuera del universo de Balanceos."""
    return {p for p, c in clases_por_planta(db).items() if c == SIN_OPERACION}
