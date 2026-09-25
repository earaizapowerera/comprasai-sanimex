"""Funciones puras (C1) de unidades, cobertura, promedios y cantidad a comprar
— sin I/O, testeables 1:1 contra los casos golden."""

from __future__ import annotations

import math
from typing import Optional

from app.core.constants import EPS_DEMANDA

from .constantes import DEFAULT_PALLET, RATIO_M2_POR_PIEZA_FALLBACK


def calc_m2_a_cajas(m2: float, m2_por_caja: Optional[float]) -> float:
    """G8: need=100 m2, m2_por_caja=1.44 -> ceil(100/1.44) = 70 cajas.
    Redondea la división a 6 decimales antes del ceil: 43.2/1.44 da
    30.000000000000004 en punto flotante, y sin este guard eso subía a 31
    cajas por ruido de FP en vez del 30 exacto (detectado por
    test_kardex_con_salidas_activa_modo_pico_en_promedio_3)."""
    if not m2_por_caja or m2_por_caja <= 0:
        return round(m2, 2)
    return math.ceil(round(m2 / m2_por_caja, 6))


def calc_cobertura_meses(disponible_neto: float, demanda_mensual: Optional[float]) -> Optional[float]:
    """Cobertura en meses = inventario disponible / demanda mensual promedio.
    None cuando no hay demanda reciente (no hay base para decidir), o cuando
    la demanda es residual (~1e-15, ruido de origen del dataset REAL CAR):
    ver EPS_DEMANDA en app.core.constants -- mismo guard que kpis.py (T16,
    waykee 290112) e inventarios.py/COBERTURA_CTE (T18, waykee 290114). Sin
    este guard, disponible_neto / demanda_mensual con un denominador ínfimo
    produce coberturas absurdas (~1e+15 meses)."""
    if demanda_mensual is None or demanda_mensual < EPS_DEMANDA:
        return None
    return disponible_neto / demanda_mensual


def calc_redondeo_moq(need: float, moq: int, multiplo_empaque: int = 1) -> int:
    """RF-011/016. G6: need=37, multiplo=12, MOQ=20 -> max(20, ceil(37/12)*12) = 48.
    G7: need=8, MOQ=20 -> 20 (sube a MOQ)."""
    if need <= 0:
        return 0
    multiplo_empaque = max(1, multiplo_empaque)
    en_multiplo = math.ceil(need / multiplo_empaque) * multiplo_empaque
    return int(max(moq, en_multiplo))


def calc_redondeo_pallet(cantidad: int, cajas_por_pallet: Optional[int]) -> int:
    """Si la cantidad ya supera un pallet completo, sube al múltiplo de pallet
    más cercano (evita fracciones de pallet en compras grandes)."""
    if not cajas_por_pallet or cajas_por_pallet <= 0 or cantidad <= cajas_por_pallet:
        return cantidad
    return int(math.ceil(cantidad / cajas_por_pallet) * cajas_por_pallet)


def calc_promedio_simple(valores: list[float]) -> float:
    """Promedio 1: media simple de la ventana de meses calendario (con ceros
    incluidos para meses sin venta -- paridad con la hoja Excel, que no
    excluye meses en blanco del promedio)."""
    if not valores:
        return 0.0
    return sum(valores) / len(valores)


def calc_promedio_ultimos_n(valores: list[float], n: int) -> float:
    """Promedio 2: media de los últimos `n` meses de la misma ventana."""
    if n <= 0:
        return 0.0
    return calc_promedio_simple(valores[-n:])


def calc_factor_m2_por_pieza(pares_m2_piezas: list[tuple[float, float]]) -> float:
    """Factor piezas POS -> m2 de UN material, derivado de la superposición
    real (mismo material) entre ventas_mensuales y ventas_stats_mensuales en
    meses previos completos. `pares_m2_piezas` = [(m2_del_mes, piezas_del_mes), ...].
    Promedia el ratio mes a mes (no suma-total/suma-total) para no dejar que
    un solo mes de mucho volumen domine el factor. Cae al fallback global
    del dataset si no hay ningún mes con piezas > 0."""
    ratios = [m2 / piezas for m2, piezas in pares_m2_piezas if piezas and piezas > 0]
    if not ratios:
        return RATIO_M2_POR_PIEZA_FALLBACK
    return sum(ratios) / len(ratios)


def calc_consumo_mes_referencia_corregido(
    piezas_mes_ref: float,
    m2_por_caja: Optional[float],
    factor_m2_por_pieza: float,
) -> float:
    """T28 (mensaje puente waykee 290066->291765, 17-sep-2026): cajas del mes de
    REFERENCIA (hoy 2026-08) recalculadas desde ventas_stats_mensuales.suma_cantidad
    (piezas POS, mes completo) en vez de ventas_mensuales.cantidad_m2 (m2, mes
    PARCIAL -- se extrae a mitad de mes y subestima ~30%). `factor_m2_por_pieza`
    ya viene derivado por el llamador (ver calc_factor_m2_por_pieza) de la propia
    superposición histórica del material, NO del ratio global del dataset
    (1.0399, mezcla de todo el catálogo -- no es una constante válida por SKU)."""
    m2_estimado = (piezas_mes_ref or 0.0) * factor_m2_por_pieza
    return calc_m2_a_cajas(m2_estimado, m2_por_caja)


def calc_valor_mes_ajustado(valor_mes: float, ajuste: float) -> float:
    """Ejemplo del mensaje puente (waykee 291765): abril 30 con ajuste 2 -> 28;
    junio 39 con ajuste 9 -> 30. Nunca deja el mes en negativo."""
    return max(0.0, valor_mes - max(0.0, ajuste))


def calc_promedio_general(promedio_1: float, promedio_2: float, promedio_3: float) -> float:
    return (promedio_1 + promedio_2 + promedio_3) / 3.0


def calc_compra_sugerida(
    meses_objetivo: float,
    promedio_general: float,
    disponible: float,
    transito: float,
) -> float:
    """Fórmula del Excel de compras: MesesObjetivo x PROMEDIO - Disponible -
    BackorderCompra(tránsito), sin netear el disponible de antemano. Caso
    golden del mensaje puente: 6*504.6667-536-473 = 2019.0.

    T29 (waykee 291788, punto 4): el término '+ comprometido' se ELIMINA de
    esta fórmula -- lo que la pantalla mostraba como "Backorder venta
    (comprometido)" es en realidad BACKORDER TRASLADO (mercancía por SALIR de
    la sucursal, no una venta pendiente de surtir), así que sumarlo a la
    compra sugerida inflaba la cantidad a pedir por algo que no es demanda.
    `comprometido` se sigue mostrando en el popup (ver build_datos_decision,
    campo "backorder_traslado") y sigue afectando disponible_neto/cobertura
    (RN-01, decide SI sugerir), solo se saca del MONTO a comprar. Cuando
    exista backorder de VENTA real (cliente esperando surtido), ese término
    se reintroduce por separado -- ver mensaje puente waykee 290066->291788."""
    bruta = (
        meses_objetivo * promedio_general
        - (disponible or 0.0)
        - (transito or 0.0)
    )
    return round(max(0.0, bruta), 2)


def calc_redondeo_pallets_completos(cantidad: float, cajas_por_pallet: Optional[int]) -> int:
    """Redondeo a Pallets del Excel: SIEMPRE sube al múltiplo de pallet
    completo (a diferencia de calc_redondeo_pallet, que solo redondea si la
    cantidad ya supera un pallet -- esa se conserva intacta porque
    backtest_forecast.py la reusa). Caso golden: 2019 cajas, pallet=16 ->
    ceil(2019/16)*16 = 2032."""
    if cantidad <= 0:
        return 0
    pallet = cajas_por_pallet if cajas_por_pallet and cajas_por_pallet > 0 else DEFAULT_PALLET
    return int(math.ceil(cantidad / pallet) * pallet)


def calc_motivo_redondeo_pallet(bruta: float, final: int, cajas_por_pallet: int) -> str:
    """Texto determinista del redondeo a pallet (sin MOQ -- el motor de 3
    promedios no aplica MOQ, solo pallet completo)."""
    if bruta <= 0:
        return "Sin compra: el faltante quedó cubierto por transferencia o el objetivo ya está cumplido."
    if final > bruta:
        return f"Se redondea de {bruta:.0f} a {final} cajas para completar pallets de {cajas_por_pallet} cajas cada uno."
    return f"Sin ajuste: {bruta:.0f} cajas ya es múltiplo exacto de pallet ({cajas_por_pallet} cajas)."
