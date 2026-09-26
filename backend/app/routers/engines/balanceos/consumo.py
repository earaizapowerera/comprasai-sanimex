"""Consumo mensual de Balanceos con la fórmula de la vista de compras
(waykee 292247).

Paridad con _SYS_BIC."SAC/ZCV_SAC_COM_ANALISIS[_CONCENTRADO]" (el Excel de
compras), a nivel TIENDA/bodega -- Enrique decidió (opción B) NO cambiar la
granularidad a centro suministrador, así que en los CEDIS que surten a otras
tiendas el número no cuadra 1:1 contra la vista (conocido y aceptado).

Ventana: meses CALENDARIO, con ceros incluidos para meses sin venta. MES_1 es
el último mes completo; el mes en curso (MES_ACTUAL, parcial) no entra.
MES_5 tampoco entra en ningún promedio de la vista. Fórmula, verificada
contra las 89,523 filas de la vista (0 diferencias > 0.02):
  PROM1 = promedio de MES_1..MES_4
  PROM2 = promedio de MES_1..MES_4 quitando el mes más alto (entre 3)
  PROM3 = promedio de MES_1 y MES_2
  VENTA_ANALIZADA = promedio de PROM1, PROM2, PROM3

Antes (v1..v3) la demanda era el promedio de los últimos 3 meses CON venta
(saltando ceros, podía llegar meses atrás) y cada mes se redondeaba hacia
arriba a cajas -- eso inflaba y a la vez desfasaba la demanda.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

MESES_VENTANA_CONSUMO = 4


def meses_ventana(mes_actual: str, n: int = MESES_VENTANA_CONSUMO) -> list[str]:
    """Los `n` meses completos previos a `mes_actual` ('YYYY-MM'),
    ascendente: [MES_4, MES_3, MES_2, MES_1]."""
    year, month = (int(x) for x in mes_actual.split("-"))
    total = year * 12 + month - 1
    return [f"{(t // 12):04d}-{(t % 12) + 1:02d}" for t in range(total - n, total)]


def mes_actual_dataset(db: sqlite3.Connection) -> str:
    """Mes en curso del dataset = MAX(anio_mes) de ventas_mensuales: los
    extractores traen el mes en curso parcial (data/ventana.py), igual que
    METROS_MES_ACTUAL de la vista. Fallback: mes UTC actual."""
    row = db.execute("SELECT MAX(anio_mes) AS m FROM ventas_mensuales").fetchone()
    if row and row["m"]:
        return row["m"]
    return datetime.now(timezone.utc).strftime("%Y-%m")


def calc_consumo_vista(valores_m2: list[float]) -> dict:
    """`valores_m2` = [MES_4, MES_3, MES_2, MES_1] en m2 (ceros incluidos).
    Caso G06-59-1-132 / M423 de la vista: [0, 80.96, 0, 705.76] ->
    prom1=196.68, prom2=26.99, prom3=352.88, venta_analizada=192.18."""
    if len(valores_m2) != MESES_VENTANA_CONSUMO:
        raise ValueError(f"se esperan {MESES_VENTANA_CONSUMO} meses, llegaron {len(valores_m2)}")
    total = sum(valores_m2)
    prom1 = total / 4
    prom2 = (total - max(valores_m2)) / 3
    prom3 = (valores_m2[-1] + valores_m2[-2]) / 2
    return {
        "prom1": prom1,
        "prom2": prom2,
        "prom3": prom3,
        "ventaAnalizada": (prom1 + prom2 + prom3) / 3,
    }


def m2_a_cajas_demanda(m2: float, m2_por_caja: Optional[float]) -> float:
    """Demanda es una tasa: se divide sin redondear (a diferencia de
    calc_m2_a_cajas, que redondea hacia arriba cantidades a pedir)."""
    if not m2_por_caja or m2_por_caja <= 0:
        return m2
    return m2 / m2_por_caja


def consumo_linea(serie_m2: dict, key, meses: list[str], m2_por_caja: Optional[float]) -> dict:
    """Consumo de una (material, plant). `serie_m2[key]` = {anio_mes: m2}.
    Devuelve el desglose en m2 y la demanda mensual en cajas."""
    por_mes = serie_m2.get(key, {})
    valores = [float(por_mes.get(m) or 0.0) for m in meses]
    proms = calc_consumo_vista(valores)
    return {
        "meses": [{"anioMes": m, "m2": round(v, 2)} for m, v in zip(meses, valores)],
        **{k: round(v, 2) for k, v in proms.items()},
        "demandaCajas": m2_a_cajas_demanda(proms["ventaAnalizada"], m2_por_caja),
    }
