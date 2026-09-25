"""Persistencia ligera del workflow (Borrador/Propuesto/Aprobado/Rechazado).
Tabla adicional, aditiva al esquema de T3 (CREATE TABLE IF NOT EXISTS)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _ensure_tables(db: sqlite3.Connection) -> None:
    _crear_tabla_sugeridos(db)
    _crear_tablas_meses_objetivo(db)
    _crear_tabla_categorias(db)
    db.commit()


def _crear_tabla_sugeridos(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS sugeridos_generados (
            id                  TEXT PRIMARY KEY,
            material_id         TEXT NOT NULL,
            plant               TEXT NOT NULL,
            descripcion         TEXT,
            abc                 TEXT,
            cobertura_actual    REAL,
            cobertura_objetivo  REAL,
            cantidad_sugerida   REAL,
            cantidad_transferir REAL,
            cantidad_comprar    REAL,
            cantidad_final      REAL,
            costo_unitario      REAL,
            costo_estimado      REAL,
            confianza           INTEGER,
            tendencia           TEXT,
            capa                TEXT,
            explicacion         TEXT,
            factores_json       TEXT,
            datos_decision_json TEXT,
            estado              TEXT NOT NULL DEFAULT 'propuesto',
            justificacion_edicion TEXT,
            aprobado_por        TEXT,
            creado              TEXT NOT NULL,
            actualizado         TEXT NOT NULL
        )"""
    )
    # T19 (waykee 290116): tablas ya creadas ANTES de este cambio no tienen
    # datos_decision_json (CREATE TABLE IF NOT EXISTS no la agrega
    # retroactivamente) -- migración aditiva idempotente, mismo patrón con el
    # que esta tabla se sumó sobre el esquema de T3 sin tocar datos existentes.
    cols = {row["name"] for row in db.execute("PRAGMA table_info(sugeridos_generados)")}
    if "datos_decision_json" not in cols:
        db.execute("ALTER TABLE sugeridos_generados ADD COLUMN datos_decision_json TEXT")


def _crear_tablas_meses_objetivo(db: sqlite3.Connection) -> None:
    # T29 (waykee 291788, punto 1): meses objetivo a dos niveles -- DEFAULT
    # por material, EXCEPCION por material+sucursal. La EXCEPCIÓN manda
    # SIEMPRE que exista (precisión explícita del PM); el default solo aplica
    # en su ausencia. `coberturas_objetivo` (T3, 1 fila por material) queda
    # como fuente de siembra histórica -- otros módulos (kpis/inventarios/
    # materiales/balanceos) la siguen usando tal cual, fuera de alcance de
    # este ticket -- pero sugeridos.py resuelve el objetivo desde estas dos
    # tablas nuevas de aquí en adelante.
    db.execute(
        """CREATE TABLE IF NOT EXISTS meses_objetivo_default (
            material_id TEXT PRIMARY KEY,
            meses       REAL NOT NULL
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS meses_objetivo_excepcion (
            material_id TEXT NOT NULL,
            plant       TEXT NOT NULL,
            meses       REAL NOT NULL,
            PRIMARY KEY (material_id, plant)
        )"""
    )
    if _tabla_existe(db, "coberturas_objetivo"):
        # Solo siembra materiales que AÚN no tienen default propio (p.ej.
        # editado a mano vía PUT /objetivo) -- no pisa ediciones. NOT EXISTS en
        # vez de INSERT OR IGNORE para que corra igual en SQL Server.
        db.execute(
            """INSERT INTO meses_objetivo_default (material_id, meses)
               SELECT c.material_id, c.meses_objetivo FROM coberturas_objetivo c
               WHERE NOT EXISTS (SELECT 1 FROM meses_objetivo_default d WHERE d.material_id = c.material_id)"""
        )


def _crear_tabla_categorias(db: sqlite3.Connection) -> None:
    # T29 (punto 5): categoría del material, puede cambiar mes a mes -- fuente
    # hoy es el Excel muestra-compras.xlsb (hoja ARAGON, ver script de carga),
    # mañana SAP (v7, Data Expert). anio_mes formato 'YYYY-MM'.
    db.execute(
        """CREATE TABLE IF NOT EXISTS categorias_mensuales (
            material_id TEXT NOT NULL,
            anio_mes    TEXT NOT NULL,
            categoria   TEXT NOT NULL,
            PRIMARY KEY (material_id, anio_mes)
        )"""
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tabla_existe(db: sqlite3.Connection, tabla: str) -> bool:
    """T25 (waykee 290148): guard para tablas opcionales del dataset que aún
    no aterrizan (kardex_diario, backorder_detalle, pedidos_compra_detalle) --
    permite degradar con gracia (None / "disponible": False) en vez de tronar
    con 'no such table', mismo patrón que _tabla_existe en
    analysis/backtest_forecast.py."""
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", [tabla]
    ).fetchone()
    return row is not None
