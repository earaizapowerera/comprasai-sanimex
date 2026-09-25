"""Constantes del motor de Sugeridos (S8)."""

from __future__ import annotations

MESES_HISTORIA = 6  # ventana de meses usada para tendencia/confianza (informativo, C2)
MESES_SERIE_DISPLAY = 5  # T27 (waykee 291745): meses calendario contiguos para el popup de decisión
DEFAULT_MOQ = 20
DEFAULT_PALLET = 40
DEFAULT_OBJETIVO_MESES = 2.0

# T28 (waykee 291765): motor de 3 promedios -- paridad con la hoja Excel del
# área de compras. Promedio 1 = ventana completa de MESES_SERIE_DISPLAY (5)
# meses calendario; Promedio 2 = solo los últimos PROMEDIO2_MESES; Promedio 3
# = misma ventana de 5 meses con el pico de cada mes restado (ver
# _ajuste_pico_mes). PROMEDIO_GENERAL = promedio simple de los 3.
PROMEDIO2_MESES = 2
# Campo de ventas_stats_mensuales a restar en el modo 1 de Promedio 3 (dataset
# v6, ya desplegado -- ver mensaje puente waykee 290066->291765, confirmado
# en vivo 17-sep-2026: max_linea == max_ticket siempre en este POS, así que
# la duda de compras sobre cuál definición usa su Excel no cambia el
# resultado). Cambiar a "max_linea" es la única acción para encender esa
# variante si compras pide lo contrario.
PROMEDIO3_CAMPO_STATS = "max_ticket"

# T28 (mensaje puente waykee 290066->291765, 17-sep-2026): el mes de
# REFERENCIA de la ventana (el más reciente, hoy 2026-08) viene PARCIAL en
# ventas_mensuales por diseño -- se extrae a mitad de mes -- mientras que
# ventas_stats_mensuales (POS /POSDW/TLOGF) sí lo trae completo. Por eso el
# consumo de ESE mes específico se sustituye por
# ventas_stats_mensuales.suma_cantidad cuando la tabla existe (ver
# calc_consumo_mes_referencia_corregido y serie_pts_display), bloqueando el fallback silencioso a
# ventas_mensuales que subestimaba ese mes ~30%. suma_cantidad viene en
# PIEZAS POS (RETAILQUANTITY), NO en m2 como cantidad_m2 -- no son
# comparables 1:1 (ver comprasai_v6_reconciliacion.json). Como no hay un
# campo "piezas por caja" limpio en materiales (columna `formato` viene
# vacía en el dataset real), el factor de conversión piezas->m2 se deriva
# POR MATERIAL de su propia superposición real en los meses previos de la
# misma ventana (vm_m2 / stats_piezas) -- más preciso que el ratio global
# del dataset (~1.04, mezcla de todo el catálogo, NO constante por SKU). Ese
# ratio global queda solo como fallback para materiales sin superposición
# válida (SKU nuevo, o piezas=0 en los meses previos).
RATIO_M2_POR_PIEZA_FALLBACK = 1.0399
