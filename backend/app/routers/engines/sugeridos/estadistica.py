"""Estadística robusta e indicadores informativos (tendencia/confianza)."""

from __future__ import annotations

from typing import Optional


def calc_mediana(valores: list[float]) -> float:
    ordenados = sorted(valores)
    n = len(ordenados)
    if n == 0:
        return 0.0
    mitad = n // 2
    if n % 2 == 1:
        return ordenados[mitad]
    return (ordenados[mitad - 1] + ordenados[mitad]) / 2.0


def calc_mad(valores: list[float], mediana: Optional[float] = None) -> float:
    """Median Absolute Deviation -- estadístico robusto (no lo mueve un solo
    valor extremo, a diferencia de la desviación estándar)."""
    if not valores:
        return 0.0
    m = mediana if mediana is not None else calc_mediana(valores)
    return calc_mediana([abs(v - m) for v in valores])


def calc_es_outlier_venta_dia(valores_dia: list[float], valor: float, k: float = 3.0) -> bool:
    """Detección informativa (no altera la cantidad sugerida): venta atípica
    si |valor - mediana| > k*MAD. Con MAD=0 (todos los días iguales) se marca
    outlier solo si el valor evaluado supera esa mediana constante."""
    if len(valores_dia) < 2:
        return False
    mediana = calc_mediana(valores_dia)
    mad = calc_mad(valores_dia, mediana)
    if mad <= 0:
        return valor > mediana
    return abs(valor - mediana) > k * mad


def calc_tendencia(serie_mensual: list[float]) -> str:
    """Compara el último mes contra el promedio de los meses previos.
    +-10% se considera estable (evita ruido de series cortas/sintéticas)."""
    if len(serie_mensual) < 2:
        return "estable"
    *previos, ultimo = serie_mensual
    promedio_previo = sum(previos) / len(previos) if previos else 0
    if promedio_previo <= 0:
        return "estable"
    delta = (ultimo - promedio_previo) / promedio_previo
    if delta >= 0.10:
        return "alza"
    if delta <= -0.10:
        return "baja"
    return "estable"


def calc_confianza(meses_con_venta: int, meses_totales: int) -> int:
    """Score 50-95 determinista según qué tan completo está el historial de
    demanda usado — no es aleatorio: mismo input, mismo score siempre."""
    if meses_totales <= 0:
        return 50
    cobertura_historial = meses_con_venta / meses_totales
    return int(round(50 + cobertura_historial * 45))
