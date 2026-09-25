"""Endpoints de la navegación de propuestas (Zona -> Artículos), recálculo y
costo de traslado por corredor."""

from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import Body, Depends, Query

from app.core.db import get_db

from .constantes import COSTO_CAJA_TRASLADO_DEFAULT, _now
from .persistencia import _costo_traslado_por_corredor, _ensure_tables
from .propuestas import (
    _cache,
    _get_cached_propuestas,
    agrupar_por_articulo,
    agrupar_por_zona,
    recalcular_propuestas,
)


def zonas_balanceo(db: sqlite3.Connection = Depends(get_db)):
    todas = _get_cached_propuestas(db)
    return {"total": len(todas), "items": agrupar_por_zona(todas), "generado": _cache["generado"]}


def articulos_balanceo(corredor: str = Query(...), db: sqlite3.Connection = Depends(get_db)):
    items = agrupar_por_articulo(_get_cached_propuestas(db), corredor)
    return {"corredor": corredor, "total": len(items), "items": items, "generado": _cache["generado"]}


def recalcular_balanceo(db: sqlite3.Connection = Depends(get_db)):
    return recalcular_propuestas(db)


def propuestas_balanceo(
    corredor: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    db: sqlite3.Connection = Depends(get_db),
):
    todas = _get_cached_propuestas(db)
    filtradas = [p for p in todas if not corredor or p["corredor"] == corredor]
    return {"total": len(filtradas), "items": filtradas[:limit], "generado": _cache["generado"] or _now()}


def get_config(db: sqlite3.Connection = Depends(get_db)):
    return {"costoTrasladoPorCorredor": _costo_traslado_por_corredor(db), "costoDefault": COSTO_CAJA_TRASLADO_DEFAULT}


def put_config(costos: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    _ensure_tables(db)
    db.execute("DELETE FROM balanceo_costo_corredor")
    db.executemany(
        "INSERT INTO balanceo_costo_corredor (corredor, costo_caja_traslado) VALUES (?,?)",
        list(costos.items()),
    )
    db.commit()
    return get_config(db)
