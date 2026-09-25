"""GET /api/articulos/{material_id}/vivo[?plant=]

Lo que se ve al ABRIR un artículo, traído de HANA en el instante (waykee
292300): posición por centro (disponible, tránsito, comprometido), pedidos de
compra pendientes, backorder de ventas y venta del mes en curso. Si HANA no
responde, el snapshot con `fuente.live = false` y el motivo. Ver
app.core.articulo_vivo.
"""

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core import articulo_vivo
from app.core.db import get_db

router = APIRouter(prefix="/api/articulos", tags=["articulos"])


def _sucursales(db) -> dict:
    return {r["plant"]: r["nombre"] for r in db.execute("SELECT plant, nombre FROM sucursales").fetchall()}


def _suma_por_plant(docs: list[dict]) -> dict:
    tot: dict = {}
    for d in docs:
        tot[d["plant"]] = tot.get(d["plant"], 0.0) + (d["cantidad_pendiente"] or 0)
    return tot


def _posiciones(datos: dict, sucursales: dict) -> list[dict]:
    """Una fila por centro del universo de la app con algo que mostrar."""
    pos, pedidos, backorder = datos["posicion"], _suma_por_plant(datos["pedidos"]), _suma_por_plant(datos["backorder"])
    venta = (datos["venta_mes"] or {}).get("m2_por_plant", {})
    filas = []
    for plant in sorted(set(pos) | set(pedidos) | set(backorder) | set(venta)):
        if plant not in sucursales:
            continue  # centros fuera del universo (CEDIS técnicos, etc.), igual que el snapshot
        p = pos.get(plant, {"disponible": 0.0, "transito": 0.0, "comprometido": 0.0})
        fila = {"plant": plant, "nombre": sucursales[plant], **p,
                "disponible_neto": round(p["disponible"] + p["transito"] - p["comprometido"], 3),
                "pedidos_compra_pendientes": round(pedidos.get(plant, 0.0), 3),
                "backorder_ventas": round(backorder.get(plant, 0.0), 3),
                "venta_mes_m2": venta.get(plant)}
        if any(fila[k] for k in ("disponible", "transito", "comprometido", "pedidos_compra_pendientes",
                                 "backorder_ventas", "venta_mes_m2")):
            filas.append(fila)
    return filas


@router.get("/{material_id}/vivo")
def articulo_en_vivo(material_id: str, plant: Optional[str] = Query(None), db: sqlite3.Connection = Depends(get_db)):
    datos = articulo_vivo.leer(db, material_id, plant)
    sucursales = _sucursales(db)
    return {
        "material_id": material_id,
        "plant": plant,
        "fuente": datos["fuente"],
        "posiciones": _posiciones(datos, sucursales),
        "pedidos_compra": [d for d in datos["pedidos"] if d["plant"] in sucursales],
        "backorder_ventas": [d for d in datos["backorder"] if d["plant"] in sucursales],
        "venta_mes": datos["venta_mes"],
    }
