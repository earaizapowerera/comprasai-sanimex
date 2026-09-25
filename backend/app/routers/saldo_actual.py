"""GET /api/inventarios/saldo-actual/{material_id}/{plant}

Saldo disponible AHORA de un par material-centro: intenta HANA CAR en vivo
(timeout corto) y, si no se puede, responde el del snapshot con su hora de
corte. `live` dice cuál de los dos es. Ver app.core.hana_live para por qué
esta ruta NO alimenta a los motores analíticos.
"""

import sqlite3

from fastapi import APIRouter, Depends

from app.core import hana_live
from app.core.articulo_vivo import ahora_utc, corte_snapshot
from app.core.db import get_db

router = APIRouter(prefix="/api/inventarios", tags=["inventarios"])


@router.get("/saldo-actual/{material_id}/{plant}")
def saldo_actual(material_id: str, plant: str, db: sqlite3.Connection = Depends(get_db)):
    snap = db.execute(
        "SELECT disponible FROM inventarios WHERE material_id = ? AND plant = ?",
        (material_id, plant),
    ).fetchone()
    disponible_snapshot = float(snap["disponible"]) if snap else None
    base = {
        "material_id": material_id,
        "plant": plant,
        "disponible_snapshot": disponible_snapshot,
        "corte_snapshot_utc": corte_snapshot(db),
    }
    try:
        vivo = hana_live.stock_actual(material_id, plant)
    except hana_live.HanaNoDisponible as exc:
        return {**base, "live": False, "fuente": "snapshot",
                "disponible": disponible_snapshot, "motivo_fallback": str(exc)}
    # Sin fila en HANA = sin stock libre en ese centro.
    return {**base, "live": True, "fuente": "hana_car", "consultado_utc": ahora_utc(),
            "disponible": vivo if vivo is not None else 0.0}
