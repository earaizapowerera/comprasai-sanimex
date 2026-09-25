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

from app.core import articulo_vivo
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


def _detalle_vivo(db, material_id: str, plant: str, parte: str, tabla: str) -> dict:
    """292300: el drill-down se abre sobre UN artículo -> HANA en vivo, con el
    snapshot (tabla v5 `tabla`) solo como respaldo marcado en `fuente`."""
    datos = articulo_vivo.leer(db, material_id, plant, partes=(parte,))
    disponible = datos["fuente"]["live"] or _tabla_existe(db, tabla)
    return {"disponible": disponible, "material_id": material_id, "plant": plant,
            "fuente": datos["fuente"], "docs": datos[parte]}


def backorder_detalle(
    material_id: str = Query(...),
    plant: str = Query(...),
    db: sqlite3.Connection = Depends(get_db),
):
    """T25 (waykee 290148): drill-down documento a documento del comprometido
    (backorder = entregas abiertas LIPS/LIKP): documento, posicion, cliente,
    cantidad_pendiente, fecha_documento, fecha_entrega_comprometida.
    `disponible: False` solo si HANA no responde Y el snapshot no trae la
    tabla de detalle -- el frontend muestra entonces el aviso degradado."""
    r = _detalle_vivo(db, material_id, plant, "backorder", "backorder_detalle")
    r["documentos"] = r.pop("docs")
    return r


def pedidos_detalle(
    material_id: str = Query(...),
    plant: str = Query(...),
    db: sqlite3.Connection = Depends(get_db),
):
    """T25 (waykee 290148): drill-down por orden de compra de "pedidos por
    cumplir": po, posicion, proveedor, cantidad_pendiente, fecha_po,
    fecha_entrega_estimada. Mismo contrato en vivo/respaldo que
    backorder-detalle."""
    r = _detalle_vivo(db, material_id, plant, "pedidos", "pedidos_compra_detalle")
    r["pedidos"] = r.pop("docs")
    return r


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
