"""Tablas de Balanceos (DDL) y lecturas de configuración/universo."""

from __future__ import annotations

import sqlite3
from datetime import date

from app.core import sucursal_compra

from .constantes import UMBRAL_DIAS_PEDIDO_DEFAULT


def _crear_tablas_config(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS balanceo_costo_corredor (
            corredor TEXT PRIMARY KEY,
            costo_caja_traslado REAL NOT NULL
        )"""
    )
    # categoria='__default__' es el único valor usado por ahora (umbral
    # global). La columna categoria queda lista para "por categoría" (spec
    # lo deja abierto: "global o por categoría si aplica") sin rediseñar la
    # tabla cuando se necesite.
    db.execute(
        """CREATE TABLE IF NOT EXISTS balanceo_umbral_dias_pedido (
            categoria TEXT PRIMARY KEY,
            umbral_dias INTEGER NOT NULL
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS balanceo_descarte (
            material_id TEXT NOT NULL,
            plant TEXT NOT NULL,
            hasta_fecha TEXT NOT NULL,
            motivo TEXT,
            creado TEXT NOT NULL,
            PRIMARY KEY (material_id, plant)
        )"""
    )
    # Mismo patrón default/excepción que meses_objetivo_default/_excepcion
    # en sugeridos.py: excepción (material_id+plant) siempre gana sobre
    # default (material_id); si ninguna existe, el llamador usa demanda
    # como proxy (ver _prioridad_efectiva).
    db.execute(
        """CREATE TABLE IF NOT EXISTS balanceo_prioridad_default (
            material_id TEXT PRIMARY KEY,
            prioridad REAL NOT NULL
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS balanceo_prioridad_excepcion (
            material_id TEXT NOT NULL,
            plant TEXT NOT NULL,
            prioridad REAL NOT NULL,
            PRIMARY KEY (material_id, plant)
        )"""
    )


def _crear_tabla_pendiente(db: sqlite3.Connection) -> None:
    # Renglones individuales creados por "Agregar" en el modal de Grid 1.
    # Grid 2 los agrupa por ruta (origen_plant, destino_plant) mientras
    # estado='pendiente'; "Generar Traslado" los pasa a 'posteado' con un
    # traslado_ref compartido; "Marcar entregado" los pasa a 'entregado'.
    db.execute(
        """CREATE TABLE IF NOT EXISTS balanceo_pendiente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id TEXT NOT NULL,
            origen_plant TEXT NOT NULL,
            destino_plant TEXT NOT NULL,
            cajas REAL NOT NULL,
            estado TEXT NOT NULL DEFAULT 'pendiente',
            traslado_ref TEXT,
            creado TEXT NOT NULL,
            posteado_en TEXT,
            entregado_en TEXT
        )"""
    )


def _ensure_tables(db: sqlite3.Connection) -> None:
    _crear_tablas_config(db)
    _crear_tabla_pendiente(db)
    db.commit()


def _costo_traslado_por_corredor(db: sqlite3.Connection) -> dict:
    # NO llama _ensure_tables aquí (hot path de GET /propuestas): causaba
    # "database is locked" bajo concurrencia. La tabla se crea UNA vez en
    # el startup de la app vía init_tables() (ver main.py).
    rows = db.execute("SELECT corredor, costo_caja_traslado FROM balanceo_costo_corredor").fetchall()
    return {r["corredor"]: r["costo_caja_traslado"] for r in rows}


def init_tables(db: sqlite3.Connection) -> None:
    """Llamado UNA vez desde el startup de la app (main.py)."""
    _ensure_tables(db)


def _sin_plantas_fuera_de_universo(db: sqlite3.Connection, filas: list[dict]) -> list[dict]:
    """292252: sucursales SIN_OPERACION (sin OCs ni inventario) no participan
    en Balanceos. Esporádicas y no-compra sí: su abasto ES el traslado."""
    fuera = sucursal_compra.plantas_sin_operacion(db)
    return [f for f in filas if f["plant"] not in fuera] if fuera else filas


def _umbral_dias_pedido(db: sqlite3.Connection) -> int:
    row = db.execute(
        "SELECT umbral_dias FROM balanceo_umbral_dias_pedido WHERE categoria = '__default__'"
    ).fetchone()
    return row["umbral_dias"] if row else UMBRAL_DIAS_PEDIDO_DEFAULT


def _descartes_activos(db: sqlite3.Connection, material_id: str, hoy: date) -> set:
    rows = db.execute(
        "SELECT plant FROM balanceo_descarte WHERE material_id = ? AND hasta_fecha >= ?",
        (material_id, hoy.isoformat()),
    ).fetchall()
    return {r["plant"] for r in rows}


def _prioridad_efectiva(db: sqlite3.Connection, material_id: str, plant: str, demanda_fallback: float):
    """Mismo patrón default/excepción que meses_objetivo en sugeridos.py.
    Sin override configurado, usa demanda mensual como proxy (ver
    permite_transferencia_por_prioridad)."""
    row = db.execute(
        "SELECT prioridad FROM balanceo_prioridad_excepcion WHERE material_id = ? AND plant = ?",
        (material_id, plant),
    ).fetchone()
    if row is not None:
        return row["prioridad"], "excepcion"
    row = db.execute(
        "SELECT prioridad FROM balanceo_prioridad_default WHERE material_id = ?",
        (material_id,),
    ).fetchone()
    if row is not None:
        return row["prioridad"], "default"
    return demanda_fallback, "demanda_proxy"
