"""Semáforo de Cumplimiento (Lite) — T11 (waykee 290099).

Tablero de pedidos abiertos (backorders) con estado de cumplimiento:
  - rojo    -> vencido (la fecha esperada de llegada ya pasó)
  - amarillo-> próximo a vencer (dentro de la ventana configurable `umbral_dias`)
  - verde   -> en tiempo (aún falta más que `umbral_dias` para la fecha esperada)

El contrato de datos (schema.sql) no trae fecha de pedido/llegada explícita
para cada backorder — solo `inventarios.pedidos_abiertos` (cantidad) y
`proveedores.lead_time_dias`. Para la demo simulamos una fecha de pedido
determinística (hash estable de material_id+plant, NO aleatoria en cada
request) y derivamos la fecha esperada = fecha_pedido + lead_time_dias.
Cuando T1 entregue pedidos reales de SAP con fechas propias, sustituir
`_fecha_pedido_simulada` por la columna real sin tocar el resto del router.
"""

import hashlib
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
import sqlite3

from app.core.db import get_db

router = APIRouter(prefix="/api/semaforo", tags=["semaforo"])

DEFAULT_UMBRAL_DIAS = 3
MAX_ANTIGUEDAD_DIAS = 45  # ventana de simulación: pedidos "colocados" en los últimos N días


def _fecha_pedido_simulada(material_id: str, plant: str, hoy: date) -> date:
    """Fecha de pedido determinística en [hoy - MAX_ANTIGUEDAD_DIAS, hoy]."""
    h = hashlib.md5(f"{material_id}|{plant}".encode()).hexdigest()
    offset = int(h[:8], 16) % (MAX_ANTIGUEDAD_DIAS + 1)
    return hoy - timedelta(days=offset)


BASE_SQL = """
    SELECT i.material_id, i.plant, m.descripcion, m.familia, m.abc, m.costo,
           s.nombre AS nombre_sucursal, s.organizacion, s.canal, s.corredor,
           i.pedidos_abiertos, i.transito,
           p.proveedor, COALESCE(p.lead_time_dias, 15) AS lead_time_dias
    FROM inventarios i
    JOIN materiales m ON m.material_id = i.material_id
    JOIN sucursales s ON s.plant = i.plant
    LEFT JOIN proveedores p ON p.material_id = i.material_id
    WHERE i.pedidos_abiertos > 0
"""


def _filters(organizacion, canal, corredor, proveedor, search):
    where = []
    params: list = []
    if organizacion:
        where.append("s.organizacion = ?")
        params.append(organizacion)
    if canal:
        where.append("s.canal = ?")
        params.append(canal)
    if corredor:
        where.append("s.corredor = ?")
        params.append(corredor)
    if proveedor:
        where.append("p.proveedor = ?")
        params.append(proveedor)
    if search:
        where.append("(i.material_id LIKE ? OR m.descripcion LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like])
    return where, params


def _rows_con_estado(db: sqlite3.Connection, organizacion, canal, corredor, proveedor, search, umbral_dias):
    where, params = _filters(organizacion, canal, corredor, proveedor, search)
    where_sql = (" AND " + " AND ".join(where)) if where else ""
    rows = db.execute(BASE_SQL + where_sql + " ORDER BY i.material_id, i.plant", params).fetchall()

    hoy = date.today()
    out = []
    for r in rows:
        r = dict(r)
        fecha_pedido = _fecha_pedido_simulada(r["material_id"], r["plant"], hoy)
        fecha_esperada = fecha_pedido + timedelta(days=r["lead_time_dias"])
        dias_para_vencer = (fecha_esperada - hoy).days  # negativo = ya vencido
        dias_transcurridos = (hoy - fecha_pedido).days

        if dias_para_vencer < 0:
            estado = "rojo"
        elif dias_para_vencer <= umbral_dias:
            estado = "amarillo"
        else:
            estado = "verde"

        r["monto_riesgo"] = round((r["pedidos_abiertos"] or 0) * (r["costo"] or 0), 2)
        r["fecha_pedido"] = fecha_pedido.isoformat()
        r["fecha_esperada"] = fecha_esperada.isoformat()
        r["dias_transcurridos"] = dias_transcurridos
        r["dias_atraso"] = max(0, -dias_para_vencer)
        r["dias_para_vencer"] = dias_para_vencer
        r["estado"] = estado
        r.pop("costo", None)
        out.append(r)
    return out


@router.get("/resumen")
def resumen(
    organizacion: Optional[str] = None,
    canal: Optional[str] = None,
    corredor: Optional[str] = None,
    proveedor: Optional[str] = None,
    search: Optional[str] = None,
    umbral_dias: int = Query(DEFAULT_UMBRAL_DIAS, ge=0, le=30),
    db: sqlite3.Connection = Depends(get_db),
):
    """3 tarjetas del semáforo: conteo + monto en riesgo por estado, más total en tránsito ligado."""
    rows = _rows_con_estado(db, organizacion, canal, corredor, proveedor, search, umbral_dias)

    def _agg(estado):
        subset = [r for r in rows if r["estado"] == estado]
        return {
            "count": len(subset),
            "monto": round(sum(r["monto_riesgo"] for r in subset), 2),
        }

    return {
        "umbral_dias": umbral_dias,
        "verde": _agg("verde"),
        "amarillo": _agg("amarillo"),
        "rojo": _agg("rojo"),
        "total_pedidos": len(rows),
        "monto_total_riesgo": round(sum(r["monto_riesgo"] for r in rows), 2),
        "transito_ligado": round(sum(r["transito"] or 0 for r in rows), 2),
    }


@router.get("/detalle")
def detalle(
    estado: Optional[str] = Query(None, pattern="^(verde|amarillo|rojo)$"),
    organizacion: Optional[str] = None,
    canal: Optional[str] = None,
    corredor: Optional[str] = None,
    proveedor: Optional[str] = None,
    search: Optional[str] = None,
    umbral_dias: int = Query(DEFAULT_UMBRAL_DIAS, ge=0, le=30),
    sort: str = Query("atraso_desc", pattern="^(atraso_desc|monto_desc|proveedor|sucursal)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: sqlite3.Connection = Depends(get_db),
):
    """Drill-down por proveedor/sucursal: días de atraso, monto en riesgo y tránsito ligado."""
    rows = _rows_con_estado(db, organizacion, canal, corredor, proveedor, search, umbral_dias)
    if estado:
        rows = [r for r in rows if r["estado"] == estado]

    if sort == "atraso_desc":
        rows.sort(key=lambda r: (-r["dias_atraso"], r["dias_para_vencer"]))
    elif sort == "monto_desc":
        rows.sort(key=lambda r: -r["monto_riesgo"])
    elif sort == "proveedor":
        rows.sort(key=lambda r: (r["proveedor"] or "", r["material_id"]))
    elif sort == "sucursal":
        rows.sort(key=lambda r: (r["nombre_sucursal"], r["material_id"]))

    total = len(rows)
    start = (page - 1) * page_size
    return {"total": total, "page": page, "page_size": page_size, "items": rows[start : start + page_size]}


@router.get("/proveedores")
def proveedores(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute(
        """SELECT DISTINCT p.proveedor
           FROM proveedores p
           JOIN inventarios i ON i.material_id = p.material_id AND i.pedidos_abiertos > 0
           WHERE p.proveedor IS NOT NULL
           ORDER BY p.proveedor"""
    ).fetchall()
    return [r["proveedor"] for r in rows]
