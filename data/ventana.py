"""Ventana de meses común a todos los extractores (corrida diaria).

Antes cada extractor tenía sus fechas fijas (MES_FIN='202608', BUDAT>='20240801'...),
válidas solo para la corrida manual en que se escribieron. La corrida diaria las
necesita móviles y ALINEADAS entre sí, así que salen de aquí.

Mes de referencia = mes en curso (UTC), igual que la extracción original: v1
se corrió el 23-ago con MES_FIN=202608, es decir, el mes en curso va parcial.
Para reproducir una corrida vieja: COMPRASAI_MES_FIN=YYYYMM.
"""

import os
from datetime import datetime, timezone

MESES_HISTORIA = 24


def _sumar_meses(yyyymm: str, n: int) -> str:
    total = int(yyyymm[:4]) * 12 + int(yyyymm[4:]) - 1 + n
    return f"{total // 12:04d}{total % 12 + 1:02d}"


def mes_fin() -> str:
    """Último mes extraído (YYYYMM); el mes en curso, parcial."""
    return os.environ.get("COMPRASAI_MES_FIN") or datetime.now(timezone.utc).strftime("%Y%m")


def mes_inicio() -> str:
    """Primer mes de la historia de ventas (24 meses contando el de fin)."""
    return _sumar_meses(mes_fin(), -(MESES_HISTORIA - 1))


def mes_fin_cuadre() -> str:
    """Último mes COMPLETO: hasta aquí se exige cuadre 1:1 entre fuentes."""
    return _sumar_meses(mes_fin(), -1)


def fecha_desde_movimientos() -> str:
    """YYYYMMDD: primer día del mes anterior al inicio (kardex y lead times
    necesitan un mes extra de colchón para arrastrar saldos y pedidos)."""
    return _sumar_meses(mes_inicio(), -1) + "01"


def mes_validacion_cierre() -> str:
    """YYYY-MM de un cierre ya cargado en HISTORICO_INVENTARIO con seguridad
    (el del mes pasado puede no estar al día 1)."""
    m = _sumar_meses(mes_fin(), -2)
    return f"{m[:4]}-{m[4:]}"
