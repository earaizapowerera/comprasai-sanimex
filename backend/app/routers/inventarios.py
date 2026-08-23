from typing import Optional

from fastapi import APIRouter, Depends, Query
import sqlite3

from app.core.db import get_db

router = APIRouter(prefix="/api/inventarios", tags=["inventarios"])

# disponible_neto = existencia física + tránsito - comprometido
# (los pedidos_abiertos NO se suman: son compras aún no llegadas a tránsito
#  y se exponen aparte para que los motores de compra los consideren).
SELECT_BASE = """
    SELECT i.material_id, i.plant, m.descripcion, s.nombre AS nombre_sucursal,
           i.disponible, i.transito, i.comprometido, i.pedidos_abiertos, i.cajas_remanentes,
           ROUND(i.disponible + i.transito - i.comprometido, 2) AS disponible_neto,
           c.meses_objetivo
    FROM inventarios i
    JOIN materiales m ON m.material_id = i.material_id
    JOIN sucursales s ON s.plant = i.plant
    LEFT JOIN coberturas_objetivo c ON c.material_id = i.material_id
"""


@router.get("")
def list_inventarios(
    material_id: Optional[str] = None,
    plant: Optional[str] = None,
    organizacion: Optional[str] = None,
    canal: Optional[str] = None,
    solo_quiebre: bool = Query(False, description="Solo pares con disponible_neto <= 0"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: sqlite3.Connection = Depends(get_db),
):
    where = []
    params: list = []
    if material_id:
        where.append("i.material_id = ?")
        params.append(material_id)
    if plant:
        where.append("i.plant = ?")
        params.append(plant)
    if organizacion:
        where.append("s.organizacion = ?")
        params.append(organizacion)
    if canal:
        where.append("s.canal = ?")
        params.append(canal)
    if solo_quiebre:
        where.append("(i.disponible + i.transito - i.comprometido) <= 0")

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    count_sql = f"""SELECT COUNT(*) AS n FROM inventarios i
                     JOIN sucursales s ON s.plant = i.plant
                     {where_sql}"""
    total = db.execute(count_sql, params).fetchone()["n"]

    rows = db.execute(
        f"{SELECT_BASE} {where_sql} ORDER BY i.material_id, i.plant LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()

    return {"total": total, "page": page, "page_size": page_size, "items": rows}
