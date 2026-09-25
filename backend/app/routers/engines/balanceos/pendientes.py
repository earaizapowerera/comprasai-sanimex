"""Descartes (snooze) y Grid 2: pendientes / generar traslado / marcar
entregado (Balanceos v2, waykee 292187)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Body, Depends, Query

from app.core.db import get_db

from .constantes import _now
from .persistencia import _ensure_tables


def crear_descarte(
    material_id: str = Body(...),
    plant: str = Body(...),
    dias: int = Body(..., gt=0),
    motivo: Optional[str] = Body(None),
    db: sqlite3.Connection = Depends(get_db),
):
    _ensure_tables(db)
    hasta = (datetime.now(timezone.utc).date() + timedelta(days=dias)).isoformat()
    db.execute(
        """INSERT INTO balanceo_descarte (material_id, plant, hasta_fecha, motivo, creado)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(material_id, plant) DO UPDATE SET
               hasta_fecha = excluded.hasta_fecha, motivo = excluded.motivo, creado = excluded.creado""",
        (material_id, plant, hasta, motivo, _now()),
    )
    db.commit()
    return {"ok": True, "hastaFecha": hasta}


def _postear_traslado_sap(origen_plant: str, destino_plant: str, cajas_total: float) -> str:
    """Stub de posteo a SAP como "Pedido de traslado" (waykee 292187).
    Interfaz separada A PROPÓSITO para conectar el conector SAP real después
    sin tocar el resto del endpoint -- por ahora NO hay integración real,
    solo genera una referencia única."""
    return f"SAP-STUB-{uuid.uuid4().hex[:10].upper()}"


def agregar_pendiente(
    material_id: str = Body(...),
    origen_plant: str = Body(...),
    destino_plant: str = Body(...),
    cajas: float = Body(..., gt=0),
    db: sqlite3.Connection = Depends(get_db),
):
    _ensure_tables(db)
    db.execute(
        """INSERT INTO balanceo_pendiente (material_id, origen_plant, destino_plant, cajas, estado, creado)
           VALUES (?, ?, ?, ?, 'pendiente', ?)""",
        (material_id, origen_plant, destino_plant, cajas, _now()),
    )
    db.commit()
    return {"ok": True}


def listar_pendientes(estado: str = Query("pendiente"), db: sqlite3.Connection = Depends(get_db)):
    """Grid 2: agrupado por ruta (origen->destino) mientras estado='pendiente'
    (suma de todos los "Agregar" hechos desde Grid 1); agrupado por
    traslado_ref para 'posteado'/'entregado' (un traslado ya generado)."""
    _ensure_tables(db)
    if estado == "pendiente":
        rows = db.execute(
            """SELECT p.origen_plant, p.destino_plant, so.nombre AS origen_nombre, sd.nombre AS destino_nombre,
                      SUM(p.cajas) AS cajas, COUNT(*) AS items
               FROM balanceo_pendiente p
               JOIN sucursales so ON so.plant = p.origen_plant
               JOIN sucursales sd ON sd.plant = p.destino_plant
               WHERE p.estado = 'pendiente'
               GROUP BY p.origen_plant, p.destino_plant
               ORDER BY cajas DESC"""
        ).fetchall()
        return {"items": rows}

    rows = db.execute(
        """SELECT p.traslado_ref, p.origen_plant, p.destino_plant, so.nombre AS origen_nombre, sd.nombre AS destino_nombre,
                  SUM(p.cajas) AS cajas, COUNT(*) AS items, MIN(p.posteado_en) AS posteado_en
           FROM balanceo_pendiente p
           JOIN sucursales so ON so.plant = p.origen_plant
           JOIN sucursales sd ON sd.plant = p.destino_plant
           WHERE p.estado = ?
           GROUP BY p.traslado_ref
           ORDER BY posteado_en DESC""",
        (estado,),
    ).fetchall()
    return {"items": rows}


def generar_traslado(
    origen_plant: str = Body(...),
    destino_plant: str = Body(...),
    db: sqlite3.Connection = Depends(get_db),
):
    _ensure_tables(db)
    rows = db.execute(
        "SELECT id, cajas FROM balanceo_pendiente WHERE origen_plant = ? AND destino_plant = ? AND estado = 'pendiente'",
        (origen_plant, destino_plant),
    ).fetchall()
    if not rows:
        return {"error": "No hay pendientes en esa ruta"}
    cajas_total = sum(r["cajas"] for r in rows)
    ref = _postear_traslado_sap(origen_plant, destino_plant, cajas_total)
    ids = [r["id"] for r in rows]
    ph = ",".join("?" * len(ids))
    db.execute(
        f"UPDATE balanceo_pendiente SET estado = 'posteado', traslado_ref = ?, posteado_en = ? WHERE id IN ({ph})",
        [ref, _now(), *ids],
    )
    db.commit()
    return {"trasladoRef": ref, "cajasTotal": cajas_total, "items": len(ids)}


def marcar_entregado(traslado_ref: str = Body(..., embed=True), db: sqlite3.Connection = Depends(get_db)):
    """Transición Posteado -> Entregado. Por ahora manual (no definido en el
    ticket cómo se auto-detecta la entrega)."""
    _ensure_tables(db)
    db.execute(
        "UPDATE balanceo_pendiente SET estado = 'entregado', entregado_en = ? WHERE traslado_ref = ? AND estado = 'posteado'",
        (_now(), traslado_ref),
    )
    db.commit()
    return {"ok": True}
