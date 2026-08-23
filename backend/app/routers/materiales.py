from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
import sqlite3

from app.core.db import get_db

router = APIRouter(prefix="/api/materiales", tags=["materiales"])


@router.get("")
def list_materiales(
    familia: Optional[str] = None,
    abc: Optional[str] = Query(None, pattern="^[ABC]$"),
    economico: Optional[int] = Query(None, ge=0, le=1),
    search: Optional[str] = Query(None, description="Filtra por material_id o descripción"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: sqlite3.Connection = Depends(get_db),
):
    where = []
    params: list = []
    if familia:
        where.append("familia = ?")
        params.append(familia)
    if abc:
        where.append("abc = ?")
        params.append(abc)
    if economico is not None:
        where.append("economico = ?")
        params.append(economico)
    if search:
        where.append("(material_id LIKE ? OR descripcion LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like])

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    total = db.execute(f"SELECT COUNT(*) AS n FROM materiales {where_sql}", params).fetchone()["n"]
    rows = db.execute(
        f"""SELECT material_id, descripcion, familia, formato, m2_por_caja, abc,
                   precio_venta, costo, economico
            FROM materiales {where_sql}
            ORDER BY material_id
            LIMIT ? OFFSET ?""",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()

    return {"total": total, "page": page, "page_size": page_size, "items": rows}


@router.get("/familias")
def list_familias(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("SELECT DISTINCT familia FROM materiales ORDER BY familia").fetchall()
    return [r["familia"] for r in rows]


@router.get("/{material_id}")
def get_material(material_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        """SELECT m.*, p.proveedor, p.lead_time_dias, p.moq_cajas, p.cajas_por_pallet,
                  c.meses_objetivo
           FROM materiales m
           LEFT JOIN proveedores p ON p.material_id = m.material_id
           LEFT JOIN coberturas_objetivo c ON c.material_id = m.material_id
           WHERE m.material_id = ?""",
        [material_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Material '{material_id}' no encontrado")
    return row
