"""GET /api/inventarios/saldo-actual/{material_id}/{plant}

Saldo disponible AHORA de un par material-centro: intenta HANA CAR en vivo
(timeout corto) y, si no se puede, responde el del snapshot con su hora de
corte. `live` dice cuál de los dos es. Ver app.core.hana_live para por qué
esta ruta NO alimenta a los motores analíticos.
"""

import os
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.core import hana_live, sqlserver
from app.core.config import DB_PATH
from app.core.db import get_db

router = APIRouter(prefix="/api/inventarios", tags=["inventarios"])


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _corte_snapshot(db) -> str | None:
    """Hora UTC de corte de los datos del snapshot vigente (la de extracción,
    no la de carga; corridas viejas sin ese dato caen a la hora de carga)."""
    if sqlserver.enabled():
        row = db.execute(
            "SELECT COALESCE(data_cutoff_utc, finished_utc) AS f FROM snapshot_runs "
            "WHERE status = 'ok' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        f = row["f"] if row else None
        if f is None:
            return None
        return (f if isinstance(f, str) else f.replace(tzinfo=timezone.utc).isoformat(timespec="seconds"))
    try:
        mtime = os.path.getmtime(DB_PATH)
    except OSError:
        return None
    return datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds")


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
        "corte_snapshot_utc": _corte_snapshot(db),
    }
    try:
        vivo = hana_live.stock_actual(material_id, plant)
    except hana_live.HanaNoDisponible as exc:
        return {**base, "live": False, "fuente": "snapshot",
                "disponible": disponible_snapshot, "motivo_fallback": str(exc)}
    # Sin fila en HANA = sin stock libre en ese centro.
    return {**base, "live": True, "fuente": "hana_car", "consultado_utc": _ahora(),
            "disponible": vivo if vivo is not None else 0.0}
