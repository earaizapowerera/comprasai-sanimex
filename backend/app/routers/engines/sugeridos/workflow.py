"""Endpoints del workflow Planeador -> Gerente: edición con justificación
(RN-08), meses objetivo default/excepción (T29) y aprobación en lote (RF-008)."""

from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import Body, Depends, HTTPException, Query

from app.core.db import get_db

from .persistencia import _ensure_tables, _now


def editar_sugerido(
    sugerido_id: str,
    cantidad_final: float = Body(..., embed=True),
    justificacion: str = Body(..., embed=True, min_length=5),
    db: sqlite3.Connection = Depends(get_db),
):
    """RN-08: toda edición manual de la cantidad requiere justificación."""
    _ensure_tables(db)
    row = db.execute("SELECT id, costo_unitario FROM sugeridos_generados WHERE id = ?", [sugerido_id]).fetchone()
    if not row:
        raise HTTPException(404, f"Sugerido '{sugerido_id}' no encontrado")
    costo_estimado = round(cantidad_final * (row["costo_unitario"] or 0), 2)
    db.execute(
        """UPDATE sugeridos_generados
           SET cantidad_final = ?, costo_estimado = ?, justificacion_edicion = ?, actualizado = ?
           WHERE id = ?""",
        [cantidad_final, costo_estimado, justificacion, _now(), sugerido_id],
    )
    db.commit()
    return {"ok": True, "id": sugerido_id, "cantidad_final": cantidad_final, "costo_estimado": costo_estimado}


def editar_meses_objetivo(
    material_id: str = Body(..., embed=True),
    meses: float = Body(..., embed=True, gt=0),
    plant: Optional[str] = Body(None, embed=True),
    db: sqlite3.Connection = Depends(get_db),
):
    """T29 (waykee 291788, punto 1): fija el objetivo de meses de cobertura.
    Sin `plant` -> edita el DEFAULT del material (aplica a toda sucursal sin
    excepción propia). Con `plant` -> crea/actualiza la EXCEPCIÓN de esa
    sucursal, que manda sobre el default la próxima vez que se genere."""
    _ensure_tables(db)
    if plant:
        db.execute(
            """INSERT INTO meses_objetivo_excepcion (material_id, plant, meses)
               VALUES (?, ?, ?)
               ON CONFLICT(material_id, plant) DO UPDATE SET meses = excluded.meses""",
            [material_id, plant, meses],
        )
    else:
        db.execute(
            """INSERT INTO meses_objetivo_default (material_id, meses) VALUES (?, ?)
               ON CONFLICT(material_id) DO UPDATE SET meses = excluded.meses""",
            [material_id, meses],
        )
    db.commit()
    return {"ok": True, "material_id": material_id, "plant": plant, "meses": meses,
            "nivel": "excepcion" if plant else "default"}


def borrar_excepcion_meses_objetivo(
    material_id: str = Query(...),
    plant: str = Query(...),
    db: sqlite3.Connection = Depends(get_db),
):
    """Quita la excepción de sucursal -- vuelve a aplicar el default del material."""
    _ensure_tables(db)
    db.execute(
        "DELETE FROM meses_objetivo_excepcion WHERE material_id = ? AND plant = ?",
        [material_id, plant],
    )
    db.commit()
    return {"ok": True, "material_id": material_id, "plant": plant}


def decidir_sugeridos(
    ids: list[str] = Body(..., embed=True),
    accion: str = Body(..., embed=True, pattern="^(aprobar|rechazar)$"),
    aprobado_por: str = Body("Gerente Demo", embed=True),
    db: sqlite3.Connection = Depends(get_db),
):
    """Clic 3: el Gerente aprueba o rechaza uno o varios sugeridos (bulk)."""
    _ensure_tables(db)
    if not ids:
        raise HTTPException(400, "ids vacío")
    nuevo_estado = "aprobado" if accion == "aprobar" else "rechazado"
    placeholders = ",".join("?" * len(ids))
    db.execute(
        f"""UPDATE sugeridos_generados
            SET estado = ?, aprobado_por = ?, actualizado = ?
            WHERE id IN ({placeholders})""",
        [nuevo_estado, aprobado_por, _now(), *ids],
    )
    db.commit()
    afectados = db.execute(
        f"SELECT id, material_id, plant, cantidad_final, costo_estimado FROM sugeridos_generados WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    return {
        "ok": True,
        "estado": nuevo_estado,
        "afectados": len(afectados),
        "monto_total": round(sum((a["costo_estimado"] or 0) for a in afectados), 2),
        "items": afectados,
    }
