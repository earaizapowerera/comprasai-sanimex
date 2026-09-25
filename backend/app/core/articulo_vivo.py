"""Datos de UN artículo al abrirlo: HANA en vivo, snapshot solo como respaldo.

Regla de Enrique (waykee 292300): "al momento de abrir un artículo quiero
datos reales, traídos en el instante de HANA". El snapshot diario (SQL Server)
es el papel de trabajo de los motores; aquí solo se usa si HANA no responde, y
entonces la respuesta lo dice explícitamente:

    fuente = {"live": True,  "fuente": "hana_car", "consultado_utc": ...}
    fuente = {"live": False, "fuente": "snapshot", "motivo_fallback": ...,
              "corte_snapshot_utc": ...}

`corte_snapshot_utc` viaja siempre, para que la UI pueda mostrar la hora del
respaldo cuando lo esté usando.
"""

import os
from datetime import datetime, timezone
from typing import Optional

from app.core import hana_articulo, hana_live, sqlserver
from app.core.config import DB_PATH

PARTES = ("posicion", "pedidos", "backorder", "venta_mes")


def ahora_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def corte_snapshot(db) -> Optional[str]:
    """Hora UTC de corte de los datos del snapshot vigente (la de extracción,
    no la de carga; corridas viejas sin ese dato caen a la hora de carga)."""
    if sqlserver.enabled():
        row = db.execute(
            "SELECT COALESCE(data_cutoff_utc, finished_utc) AS f FROM snapshot_runs "
            "WHERE status = 'ok' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        f = row["f"] if row else None
        if f is None:
            return None
        return f if isinstance(f, str) else f.replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
    try:
        mtime = os.path.getmtime(DB_PATH)
    except OSError:
        return None
    return datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds")


def _tabla_existe(db, tabla: str) -> bool:
    # sqlite_master lo traduce app.core.sqlserver cuando el backend es SQL Server.
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", [tabla]
    ).fetchone() is not None


def _where(material_id: str, plant: Optional[str]) -> tuple[str, list]:
    if plant:
        return "material_id = ? AND plant = ?", [material_id, plant]
    return "material_id = ?", [material_id]


def _posicion_snapshot(db, material_id, plant) -> dict:
    w, p = _where(material_id, plant)
    rows = db.execute(f"SELECT plant, disponible, transito, comprometido FROM inventarios WHERE {w}", p).fetchall()
    return {r["plant"]: {"disponible": float(r["disponible"] or 0), "transito": float(r["transito"] or 0),
                         "comprometido": float(r["comprometido"] or 0)} for r in rows}


def _docs_snapshot(db, tabla: str, cols: str, orden: str, material_id, plant) -> list[dict]:
    if not _tabla_existe(db, tabla):
        return []
    w, p = _where(material_id, plant)
    rows = db.execute(f"SELECT plant, {cols} FROM {tabla} WHERE {w} ORDER BY {orden}", p).fetchall()
    return [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()} for r in rows]


def _snapshot(db, material_id: str, plant: Optional[str], partes) -> dict:
    lectores = {
        "posicion": lambda: _posicion_snapshot(db, material_id, plant),
        "pedidos": lambda: _docs_snapshot(
            db, "pedidos_compra_detalle",
            "po, posicion, proveedor, cantidad_pendiente, fecha_po, fecha_entrega_estimada",
            "fecha_entrega_estimada", material_id, plant),
        "backorder": lambda: _docs_snapshot(
            db, "backorder_detalle",
            "documento, posicion, cliente, cantidad_pendiente, fecha_documento, fecha_entrega_comprometida",
            "fecha_entrega_comprometida", material_id, plant),
        # El snapshot no guarda el mes en curso como dato fiable (se extrae de
        # madrugada): sin HANA, la venta del mes se reporta como desconocida.
        "venta_mes": lambda: None,
    }
    return {p: lectores[p]() for p in partes}


def leer(db, material_id: str, plant: Optional[str] = None, partes=PARTES) -> dict:
    """{<parte>: datos, ..., "fuente": {...}} -- en vivo o con respaldo marcado."""
    corte = corte_snapshot(db)
    try:
        datos = hana_articulo.leer(material_id, plant, partes)
        fuente = {"live": True, "fuente": "hana_car", "consultado_utc": ahora_utc(), "corte_snapshot_utc": corte}
    except hana_live.HanaNoDisponible as exc:
        datos = _snapshot(db, material_id, plant, partes)
        fuente = {"live": False, "fuente": "snapshot", "motivo_fallback": str(exc), "corte_snapshot_utc": corte}
    return {**datos, "fuente": fuente}
