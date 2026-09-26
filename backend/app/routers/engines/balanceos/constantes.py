"""Constantes del motor de Balanceos."""

from __future__ import annotations

from datetime import datetime, timezone

DEFAULT_OBJETIVO_MESES = 2.0
COSTO_CAJA_TRASLADO_DEFAULT = 20.0

# --- Balanceos v2 (waykee 292187): motor de triggers + Grid pendientes -----
# Umbral de días desde el pedido de compra pendiente a partir del cual, aun
# con pedido en curso, sí se sugiere balanceo (Trigger 2). NO modela lead
# time real por proveedor -- Enrique lo descartó explícitamente ("muy
# indefinido"); es un umbral fijo, configurable en BD (balanceo_umbral_dias_pedido).
UMBRAL_DIAS_PEDIDO_DEFAULT = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
