from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
import sqlite3

from app.core.db import get_db

router = APIRouter(prefix="/api/ventas", tags=["ventas"])

GROUP_COLUMNS = {
    "material": "material_id",
    "plant": "plant",
    "canal": "canal",
}


@router.get("")
def list_ventas(
    material_id: Optional[str] = None,
    plant: Optional[str] = None,
    canal: Optional[str] = None,
    anio_mes_desde: Optional[str] = Query(None, description="YYYY-MM"),
    anio_mes_hasta: Optional[str] = Query(None, description="YYYY-MM"),
    group_by: Optional[str] = Query(
        None, description="material | plant | canal — agrupa la serie por esta clave y por mes"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=2000),
    db: sqlite3.Connection = Depends(get_db),
):
    where = []
    params: list = []
    if material_id:
        where.append("material_id = ?")
        params.append(material_id)
    if plant:
        where.append("plant = ?")
        params.append(plant)
    if canal:
        where.append("canal = ?")
        params.append(canal)
    if anio_mes_desde:
        where.append("anio_mes >= ?")
        params.append(anio_mes_desde)
    if anio_mes_hasta:
        where.append("anio_mes <= ?")
        params.append(anio_mes_hasta)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    if group_by:
        if group_by not in GROUP_COLUMNS:
            raise HTTPException(status_code=400, detail=f"group_by inválido. Usa: {list(GROUP_COLUMNS)}")
        col = GROUP_COLUMNS[group_by]
        rows = db.execute(
            f"""SELECT {col} AS clave, anio_mes,
                       ROUND(SUM(cantidad_m2), 2) AS cantidad_m2,
                       ROUND(SUM(importe), 2) AS importe
                FROM ventas_mensuales {where_sql}
                GROUP BY {col}, anio_mes
                ORDER BY {col}, anio_mes""",
            params,
        ).fetchall()
        return {"group_by": group_by, "items": rows}

    total = db.execute(f"SELECT COUNT(*) AS n FROM ventas_mensuales {where_sql}", params).fetchone()["n"]
    rows = db.execute(
        f"""SELECT material_id, plant, canal, anio_mes, cantidad_m2, importe
            FROM ventas_mensuales {where_sql}
            ORDER BY anio_mes DESC, material_id, plant
            LIMIT ? OFFSET ?""",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()
    return {"total": total, "page": page, "page_size": page_size, "items": rows}
