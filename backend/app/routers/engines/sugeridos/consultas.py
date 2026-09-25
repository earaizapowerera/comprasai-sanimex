"""Endpoints de consulta: catálogos del filtro, vista del Gerente, drill-downs
y exportación a SAP (RF-009)."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, Query
from fastapi.responses import StreamingResponse

from app.core.db import get_db

from .persistencia import _ensure_tables, _tabla_existe


def opciones(db: sqlite3.Connection = Depends(get_db)):
    """Catálogos para los combobox searchable del filtro (familia/proveedor/corredor)."""
    familias = [r["familia"] for r in db.execute("SELECT DISTINCT familia FROM materiales ORDER BY familia")]
    proveedores = [r["proveedor"] for r in db.execute("SELECT DISTINCT proveedor FROM proveedores ORDER BY proveedor")]
    corredores = [r["corredor"] for r in db.execute("SELECT DISTINCT corredor FROM sucursales WHERE corredor IS NOT NULL ORDER BY corredor")]
    return {"familias": familias, "proveedores": proveedores, "corredores": corredores}


def lista_sugeridos(
    estado: Optional[str] = Query(None, pattern="^(propuesto|aprobado|rechazado)$"),
    db: sqlite3.Connection = Depends(get_db),
):
    """Vista del Gerente: lo ya propuesto por el Planeador, listo para decidir."""
    _ensure_tables(db)
    where = "WHERE estado = ?" if estado else ""
    params = [estado] if estado else []
    rows = [
        dict(r)
        for r in db.execute(
            f"""SELECT * FROM sugeridos_generados {where} ORDER BY actualizado DESC, material_id, plant""",
            params,
        ).fetchall()
    ]
    for r in rows:
        # T19 (waykee 290116): factores_json queda como columna muerta
        # (compatibilidad con filas históricas) -- ya no se expone al
        # frontend; datos_decision_json es la fuente real de la explicación.
        r.pop("factores_json", None)
        r["datos_decision"] = json.loads(r.pop("datos_decision_json", None) or "{}")
    return {"items": rows}


def backorder_detalle(
    material_id: str = Query(...),
    plant: str = Query(...),
    db: sqlite3.Connection = Depends(get_db),
):
    """T25 (waykee 290148): drill-down documento a documento del comprometido
    (backorder) de una línea material+plant, para el clic desde ExplainPanel.
    La tabla `backorder_detalle` (dataset v5: documento, posicion, cliente,
    cantidad_pendiente, fecha_documento, fecha_entrega_comprometida) la sigue
    extrayendo el Data Expert en waykee 290147 -- mientras no exista se
    responde `disponible: False` para que el frontend muestre el aviso de
    "detalle en camino" en vez de un 500."""
    if not _tabla_existe(db, "backorder_detalle"):
        return {"disponible": False, "material_id": material_id, "plant": plant, "documentos": []}
    rows = db.execute(
        """SELECT documento, posicion, cliente, cantidad_pendiente,
                  fecha_documento, fecha_entrega_comprometida
           FROM backorder_detalle
           WHERE material_id = ? AND plant = ?
           ORDER BY fecha_entrega_comprometida""",
        [material_id, plant],
    ).fetchall()
    return {"disponible": True, "material_id": material_id, "plant": plant, "documentos": rows}


def pedidos_detalle(
    material_id: str = Query(...),
    plant: str = Query(...),
    db: sqlite3.Connection = Depends(get_db),
):
    """T25 (waykee 290148): drill-down por orden de compra de "pedidos por
    cumplir" (tránsito) de una línea material+plant. Tabla
    `pedidos_compra_detalle` (dataset v5: po, posicion, proveedor,
    cantidad_pendiente, fecha_po, fecha_entrega_estimada), misma coordinación
    con el Data Expert en waykee 290147 y mismo fallback degradado que
    backorder-detalle mientras no aterriza."""
    if not _tabla_existe(db, "pedidos_compra_detalle"):
        return {"disponible": False, "material_id": material_id, "plant": plant, "pedidos": []}
    rows = db.execute(
        """SELECT po, posicion, proveedor, cantidad_pendiente,
                  fecha_po, fecha_entrega_estimada
           FROM pedidos_compra_detalle
           WHERE material_id = ? AND plant = ?
           ORDER BY fecha_entrega_estimada""",
        [material_id, plant],
    ).fetchall()
    return {"disponible": True, "material_id": material_id, "plant": plant, "pedidos": rows}


def exportar_sap(db: sqlite3.Connection = Depends(get_db)):
    """RF-009: plantilla de carga masiva a SAP con los sugeridos aprobados."""
    _ensure_tables(db)
    rows = db.execute(
        """SELECT material_id, plant, cantidad_final, costo_estimado, aprobado_por, actualizado
           FROM sugeridos_generados WHERE estado = 'aprobado' ORDER BY plant, material_id"""
    ).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Material", "Centro", "Cantidad", "UMB", "Importe estimado", "Aprobado por", "Fecha aprobación"])
    for r in rows:
        writer.writerow([
            r["material_id"], r["plant"], int(r["cantidad_final"] or 0), "CAJ",
            r["costo_estimado"], r["aprobado_por"], r["actualizado"],
        ])
    buf.seek(0)
    filename = f"plantilla_sap_comprasai_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
