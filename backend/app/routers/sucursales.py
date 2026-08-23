from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
import sqlite3

from app.core.db import get_db

router = APIRouter(prefix="/api/sucursales", tags=["sucursales"])


@router.get("")
def list_sucursales(
    organizacion: Optional[str] = None,
    canal: Optional[str] = None,
    corredor: Optional[str] = None,
    es_cedis: Optional[int] = Query(None, ge=0, le=1),
    search: Optional[str] = Query(None, description="Filtra por plant o nombre"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: sqlite3.Connection = Depends(get_db),
):
    where = []
    params: list = []
    if organizacion:
        where.append("organizacion = ?")
        params.append(organizacion)
    if canal:
        where.append("canal = ?")
        params.append(canal)
    if corredor:
        where.append("corredor = ?")
        params.append(corredor)
    if es_cedis is not None:
        where.append("es_cedis = ?")
        params.append(es_cedis)
    if search:
        where.append("(plant LIKE ? OR nombre LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like])

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    total = db.execute(f"SELECT COUNT(*) AS n FROM sucursales {where_sql}", params).fetchone()["n"]
    rows = db.execute(
        f"""SELECT plant, nombre, organizacion, canal, corredor, es_cedis
            FROM sucursales {where_sql}
            ORDER BY plant
            LIMIT ? OFFSET ?""",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()

    return {"total": total, "page": page, "page_size": page_size, "items": rows}


@router.get("/corredores")
def list_corredores(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("SELECT DISTINCT corredor FROM sucursales WHERE corredor IS NOT NULL ORDER BY corredor").fetchall()
    return [r["corredor"] for r in rows]


@router.get("/{plant}")
def get_sucursal(plant: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM sucursales WHERE plant = ?", [plant]).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Sucursal '{plant}' no encontrada")
    return row
