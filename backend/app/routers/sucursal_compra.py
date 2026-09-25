"""API del catálogo sucursal_compra (waykee 292252). Lógica en app/core/sucursal_compra.py."""

import sqlite3
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.core import sucursal_compra as sc
from app.core.db import get_db, upsert

router = APIRouter(prefix="/api/sucursal-compra", tags=["sucursal-compra"])


@router.get("")
def listar(clase: Optional[str] = Query(None), db: sqlite3.Connection = Depends(get_db)):
    """Catálogo con la clase efectiva, la calculada y la evidencia de cada sucursal."""
    sc.init_tables(db)
    where, params = ("WHERE c.clase = ?", [clase]) if clase else ("", [])
    items = db.execute(
        f"""SELECT c.*, s.nombre, s.corredor, s.canal, o.motivo AS override_motivo,
                   o.usuario AS override_usuario, o.actualizado AS override_actualizado
            FROM sucursal_compra c
            LEFT JOIN sucursales s ON s.plant = c.plant
            LEFT JOIN sucursal_compra_override o ON UPPER(o.plant) = UPPER(c.plant)
            {where} ORDER BY c.clase, c.oc_ext_12m DESC, c.plant""",
        params,
    ).fetchall()
    return {"total": len(items), "umbral_oc_anual": sc.get_umbral(db), "conteo": sc.conteo(db), "items": items}


@router.post("/recalcular")
def recalcular(db: sqlite3.Connection = Depends(get_db)):
    return sc.recalcular(db)


@router.put("/config/umbral")
def put_umbral(umbral_oc_anual: int = Body(..., embed=True, ge=1, le=365), db: sqlite3.Connection = Depends(get_db)):
    """Cambia el umbral de OCs externas/año para COMPRA_DIRECTA y reclasifica."""
    sc.init_tables(db)
    sc.set_umbral(db, umbral_oc_anual)
    return sc.recalcular(db)


@router.put("/{plant}/override")
def put_override(
    plant: str,
    clase: str = Body(...),
    motivo: Optional[str] = Body(None),
    usuario: Optional[str] = Body(None),
    db: sqlite3.Connection = Depends(get_db),
):
    """El planeador fija la clase de una sucursal; manda sobre la calculada."""
    if clase not in sc.CLASES_OVERRIDE:
        raise HTTPException(400, f"clase inválida; permitidas: {', '.join(sc.CLASES_OVERRIDE)}")
    sc.init_tables(db)
    if not db.execute("SELECT 1 FROM sucursales WHERE plant = ?", (plant,)).fetchone():
        raise HTTPException(404, f"sucursal {plant} no existe")
    upsert(db, "sucursal_compra_override", {"plant": plant},
           {"clase": clase, "motivo": motivo, "usuario": usuario, "actualizado": sc._now()})
    db.commit()
    return sc.recalcular(db)


@router.delete("/{plant}/override")
def delete_override(plant: str, db: sqlite3.Connection = Depends(get_db)):
    """Quita el override: la sucursal vuelve a su clase calculada."""
    sc.init_tables(db)
    db.execute("DELETE FROM sucursal_compra_override WHERE UPPER(plant) = UPPER(?)", (plant,))
    db.commit()
    return sc.recalcular(db)
