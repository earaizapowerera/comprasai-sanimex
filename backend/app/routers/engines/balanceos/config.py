"""Config de Balanceos v2 (waykee 292187): umbral de días de pedido y
prioridad entre sucursales (default por material / excepción por plant)."""

from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import Body, Depends, Query

from app.core.db import get_db

from .constantes import UMBRAL_DIAS_PEDIDO_DEFAULT
from .persistencia import _ensure_tables, _umbral_dias_pedido


def get_umbral_dias(db: sqlite3.Connection = Depends(get_db)):
    _ensure_tables(db)
    return {"umbralDias": _umbral_dias_pedido(db), "default": UMBRAL_DIAS_PEDIDO_DEFAULT}


def put_umbral_dias(umbral_dias: int = Body(..., embed=True, gt=0), db: sqlite3.Connection = Depends(get_db)):
    _ensure_tables(db)
    db.execute(
        """INSERT INTO balanceo_umbral_dias_pedido (categoria, umbral_dias) VALUES ('__default__', ?)
           ON CONFLICT(categoria) DO UPDATE SET umbral_dias = excluded.umbral_dias""",
        (umbral_dias,),
    )
    db.commit()
    return get_umbral_dias(db)


def get_prioridad(db: sqlite3.Connection = Depends(get_db)):
    _ensure_tables(db)
    defaults = db.execute("SELECT material_id, prioridad FROM balanceo_prioridad_default").fetchall()
    excepciones = db.execute("SELECT material_id, plant, prioridad FROM balanceo_prioridad_excepcion").fetchall()
    return {"defaults": defaults, "excepciones": excepciones}


def put_prioridad(
    material_id: str = Body(...),
    prioridad: float = Body(...),
    plant: Optional[str] = Body(None),
    db: sqlite3.Connection = Depends(get_db),
):
    """Mismo patrón que PUT /objetivo en sugeridos.py: sin plant edita el
    DEFAULT (material_id); con plant crea/actualiza la EXCEPCIÓN
    (material_id+plant)."""
    _ensure_tables(db)
    if plant:
        db.execute(
            """INSERT INTO balanceo_prioridad_excepcion (material_id, plant, prioridad) VALUES (?, ?, ?)
               ON CONFLICT(material_id, plant) DO UPDATE SET prioridad = excluded.prioridad""",
            (material_id, plant, prioridad),
        )
    else:
        db.execute(
            """INSERT INTO balanceo_prioridad_default (material_id, prioridad) VALUES (?, ?)
               ON CONFLICT(material_id) DO UPDATE SET prioridad = excluded.prioridad""",
            (material_id, prioridad),
        )
    db.commit()
    return {"ok": True}


def delete_prioridad_excepcion(
    material_id: str = Query(...),
    plant: str = Query(...),
    db: sqlite3.Connection = Depends(get_db),
):
    db.execute(
        "DELETE FROM balanceo_prioridad_excepcion WHERE material_id = ? AND plant = ?", (material_id, plant)
    )
    db.commit()
    return {"ok": True}
