"""T25 (waykee 290123) · Torneo de pronósticos: 5 algoritmos con backtest
rolling-origin mensual (h=1..3) y censura por desabasto.

Compara 5 algoritmos de forecast de demanda mensual (m2) con un protocolo de
backtest de origen rodante (rolling-origin), diseñado para responder: ¿qué
algoritmo predice mejor la demanda real, y qué tan seguido hubiera evitado
quiebres de inventario si se usara para sugerir compras?

LOS 5 ALGORITMOS (numpy puro, sin dependencias pesadas -- mismo criterio que
`engines/forecast.py`):
  A1 Seasonal-naive        -- `forecast_seasonal_naive`
  A2 Media móvil 3 meses   -- `forecast_media_movil` (lo que usa HOY motor C1)
  A3 Tendencia + estacional -- `forecast_tendencia_estacional` (motor C2 actual,
     post-fix T22: REUTILIZA `construir_forecast_serie` de
     `engines/forecast.py` en vez de reimplementar, para garantizar paridad
     exacta con producción -- ver ese módulo para el detalle del fix T22).
  A4 Holt-Winters aditivo  -- `forecast_holt_winters` (implementación propia)
  A5 Croston/SBA           -- `forecast_croston_sba` (demanda intermitente)

PROTOCOLO DE BACKTEST (rolling-origin):
  Para cada mes ORIGEN de los últimos `N_ORIGENES` (12 por defecto) con
  horizonte completo disponible: entrenar cada algoritmo SOLO con la
  historia <= origen, pronosticar h=1,2,3, y comparar contra el valor real
  observado. `generar_origenes` calcula estos índices y nunca trunca en
  silencio: si la serie no tiene suficiente historia para 12 orígenes,
  devuelve los que sí caben y el llamador reporta cuántos se usaron.

MÉTRICAS: WAPE (Weighted Absolute Percentage Error, agregado por
algoritmo x horizonte x segmento) y sesgo (sobre/sub-pronóstico, signado,
positivo = el algoritmo sobre-pronostica). Ambas excluyen registros
censurados y registros donde el algoritmo no pudo producir forecast (poca
historia) -- `agregar_wape_sesgo` reporta cuántos se excluyeron de cada tipo,
nunca en silencio.

CENSURA (T23/v3, kardex_diario): `detectar_meses_desabasto` marca
(material_id, plant, anio_mes) con desabasto si el saldo de inventario de
`kardex_diario` tocó <=0 en >= `umbral_dias` días de ese mes. Si la tabla
`kardex_diario` no existe en el .db (dataset `data-real-car-v2`, sin kardex)
devuelve un set() vacío: el run es entonces PRELIMINAR SIN CENSURA -- así lo
marca `ejecutar_torneo` en el reporte (`censura_disponible=False`), tal como
pide el ticket: correr primero con v2 sin censura, re-correr con v3 cuando
el kardex esté disponible (T23 en curso al momento de este análisis).

SIMULACIÓN DE SERVICIO (`simular_servicio_serie`): para cada serie
material×sucursal, simula -por algoritmo, en los mismos orígenes rolling- la
política de cobertura objetivo vigente (RN-01: comprar hasta cubrir
`meses_objetivo` de demanda, redondeando a MOQ/pallet del proveedor -- se
REUTILIZAN `calc_m2_a_cajas`/`calc_redondeo_moq`/`calc_redondeo_pallet` de
`engines/sugeridos.py` para consistencia con el motor C1 real). Cuenta
quiebres (demanda real del mes siguiente > stock disponible al inicio de ese
mes). LIMITACIÓN DOCUMENTADA: esta simulación es una versión SIMPLIFICADA de
la política real -- omite RN-02 (transferencias entre plants del mismo
corredor antes de comprar) porque requeriría simular la red completa de
sucursales en simultáneo; el efecto de omitir RN-02 es aproximadamente el
mismo para los 5 algoritmos (todos comparten la misma red), así que la
comparación RELATIVA entre algoritmos se mantiene válida aunque el conteo
ABSOLUTO de quiebres sea más alto que en la operación real. También asume
lead time <= 1 mes (el pedido colocado al cierre del mes origen llega antes
del mes siguiente) -- razonable dado que `lead_time_dias` típico en
`proveedores` es de 15 días, menor a la resolución mensual del backtest.

USO:
    cd backend
    python3 -m analysis.backtest_forecast --db-path /ruta/comprasai.db \
        --top-n-canal 300 --top-n-sucursal 300 --hasta-mes 2026-07 \
        --output-dir analysis/results

TESTS (funciones puras, sin I/O):
    cd backend && python3 -m unittest tests.test_backtest_forecast -v
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.constants import EPS_DEMANDA  # noqa: E402
from app.routers.engines.forecast import (  # noqa: E402
    GANADOR_BASE_MINIMA_M2,
    MIN_PUNTOS_ESTACIONALIDAD,
    construir_forecast_serie,
    _mes_calendario as mes_calendario,
    _siguiente_mes as siguiente_mes,
)
from app.routers.engines.sugeridos import (  # noqa: E402
    DEFAULT_MOQ,
    DEFAULT_OBJETIVO_MESES,
    DEFAULT_PALLET,
    calc_m2_a_cajas,
    calc_redondeo_moq,
    calc_redondeo_pallet,
)

# ---------------------------------------------------------------------------
# Parámetros generales del torneo
# ---------------------------------------------------------------------------

HORIZONTE_MAX = 3            # h=1,2,3 (igual que motor C2 -- HORIZONTE_FORECAST)
N_ORIGENES = 12              # últimos 12 meses-origen del rolling-origin
PERIODO_ESTACIONAL = 12      # meses en un ciclo anual

MIN_PUNTOS_ABSOLUTO = 3       # bajo esto, ningún algoritmo intenta pronosticar
MIN_PUNTOS_ESTACIONAL_HW = 12  # Holt-Winters degrada a Holt lineal (sin estacional) bajo esto

DEFAULT_ALPHA_HW = 0.3
DEFAULT_BETA_HW = 0.1
DEFAULT_GAMMA_HW = 0.3
DEFAULT_ALPHA_CROSTON = 0.1

CANALES_EXCLUIDOS = ("Outlet", "Remates")  # RN-04, igual que engines/forecast.py

NOMBRES_ALGORITMOS = (
    "A1_seasonal_naive",
    "A2_media_movil_3m",
    "A3_tendencia_estacional",
    "A4_holt_winters",
    "A5_croston_sba",
)

BASELINE_ALGORITMO = "A2_media_movil_3m"  # "lo que usa HOY el motor C1" (ver docstring del módulo)


# ---------------------------------------------------------------------------
# A1 · Seasonal-naive
# ---------------------------------------------------------------------------

def forecast_seasonal_naive(meses: list[str], y: np.ndarray, horizonte: int = HORIZONTE_MAX) -> Optional[list[float]]:
    """Pronóstico = valor observado en el mismo mes-calendario del año
    anterior. Si ese mes no existe en la historia (serie con <13 meses, o con
    huecos), cae a un fallback: promedio de los últimos 3 meses disponibles."""
    n = len(y)
    if n < MIN_PUNTOS_ABSOLUTO:
        return None
    idx_por_mes = {m: i for i, m in enumerate(meses)}
    fallback = float(np.mean(y[-min(3, n):]))
    ultimo_mes = meses[-1]
    salida = []
    for h in range(1, horizonte + 1):
        mes_fut = siguiente_mes(ultimo_mes, h)
        anio, mes = int(mes_fut[:4]), int(mes_fut[5:7])
        mes_hace_un_anio = f"{anio - 1:04d}-{mes:02d}"
        if mes_hace_un_anio in idx_por_mes:
            salida.append(float(y[idx_por_mes[mes_hace_un_anio]]))
        else:
            salida.append(fallback)
    return salida


# ---------------------------------------------------------------------------
# A2 · Media móvil 3 meses
# ---------------------------------------------------------------------------

def forecast_media_movil(meses: list[str], y: np.ndarray, horizonte: int = HORIZONTE_MAX, ventana: int = 3) -> Optional[list[float]]:
    """Pronóstico PLANO (mismo valor para h=1,2,3) = promedio de los últimos
    `ventana` meses. Es exactamente `demanda_mensual()` de
    `engines/sugeridos.py` (motor C1 vigente hoy), extendida a un horizonte
    de 3 para poder competir en el mismo protocolo de backtest."""
    n = len(y)
    if n < MIN_PUNTOS_ABSOLUTO:
        return None
    media = float(np.mean(y[-min(ventana, n):]))
    return [media] * horizonte


# ---------------------------------------------------------------------------
# A3 · Tendencia lineal + estacionalidad aditiva (motor C2, post-fix T22)
# ---------------------------------------------------------------------------

def forecast_tendencia_estacional(meses: list[str], y: np.ndarray, horizonte: int = HORIZONTE_MAX) -> Optional[list[float]]:
    """REUTILIZA `construir_forecast_serie` de `engines/forecast.py` tal
    cual corre en producción (incluye el fix T22: atípicos sobre residuales
    de Theil-Sen + rescate de rachas sostenidas + `crecimiento_pct` sobre la
    serie original). No se reimplementa para evitar que este módulo y el
    motor real diverjan con el tiempo."""
    if horizonte > HORIZONTE_MAX:
        return None  # construir_forecast_serie siempre proyecta HORIZONTE_FORECAST=3
    resultado = construir_forecast_serie(list(meses), [float(v) for v in y])
    if not resultado["suficiente_historia"]:
        return None
    forecast = resultado["forecast"]
    if len(forecast) < horizonte:
        return None
    return [p["valor_estimado_m2"] for p in forecast[:horizonte]]


# ---------------------------------------------------------------------------
# A4 · Holt-Winters aditivo (triple suavizado exponencial)
# ---------------------------------------------------------------------------

def forecast_holt_winters(
    meses: list[str],
    y: np.ndarray,
    horizonte: int = HORIZONTE_MAX,
    alpha: float = DEFAULT_ALPHA_HW,
    beta: float = DEFAULT_BETA_HW,
    gamma: float = DEFAULT_GAMMA_HW,
    periodo: int = PERIODO_ESTACIONAL,
) -> Optional[list[float]]:
    """Holt-Winters aditivo (nivel + tendencia + estacionalidad) con pesos
    fijos (sin grid-search por serie -- con miles de series x 12 orígenes
    optimizar alpha/beta/gamma por ajuste sería costoso; se documenta como
    mejora futura en los hallazgos). Con <`MIN_PUNTOS_ESTACIONAL_HW` (12)
    meses de historia degrada a Holt lineal (nivel+tendencia, sin
    estacionalidad) -- mismo criterio de "sin ciclo anual completo" que
    `MIN_PUNTOS_ESTACIONALIDAD` en `engines/forecast.py`."""
    n = len(y)
    if n < MIN_PUNTOS_ABSOLUTO:
        return None
    y = np.asarray(y, dtype=float)
    usar_estacional = n >= MIN_PUNTOS_ESTACIONAL_HW
    idx_mes_cal = [mes_calendario(m) - 1 for m in meses]  # 0-based, para indexar estac[0..periodo-1]

    if usar_estacional:
        n_ciclos = n // periodo
        base = y[: n_ciclos * periodo]
        prom_general = float(base.mean())
        estac = np.zeros(periodo)
        conteo = np.zeros(periodo)
        for i in range(len(base)):
            estac[idx_mes_cal[i]] += base[i] - prom_general
            conteo[idx_mes_cal[i]] += 1
        estac = np.divide(estac, np.maximum(conteo, 1))
        estac -= estac.mean()  # normaliza a suma ~0 (forma aditiva)
        nivel_t = float(y[:periodo].mean())
        tendencia_t = float((y[periodo:2 * periodo].mean() - y[:periodo].mean()) / periodo) if n >= 2 * periodo else 0.0
        inicio = periodo
    else:
        estac = np.zeros(periodo)
        nivel_t = float(y[0])
        tendencia_t = float(y[1] - y[0])
        inicio = 2

    for i in range(inicio, n):
        mes_idx = idx_mes_cal[i]
        s_prev = estac[mes_idx] if usar_estacional else 0.0
        nivel_prev, tendencia_prev = nivel_t, tendencia_t
        nivel_t = alpha * (y[i] - s_prev) + (1 - alpha) * (nivel_prev + tendencia_prev)
        tendencia_t = beta * (nivel_t - nivel_prev) + (1 - beta) * tendencia_prev
        if usar_estacional:
            estac[mes_idx] = gamma * (y[i] - nivel_t) + (1 - gamma) * s_prev

    ultimo_mes = meses[-1]
    salida = []
    for h in range(1, horizonte + 1):
        mes_fut = siguiente_mes(ultimo_mes, h)
        mes_idx = mes_calendario(mes_fut) - 1
        valor = nivel_t + h * tendencia_t + (estac[mes_idx] if usar_estacional else 0.0)
        salida.append(max(float(valor), 0.0))
    return salida


# ---------------------------------------------------------------------------
# A5 · Croston / SBA (demanda intermitente)
# ---------------------------------------------------------------------------

def forecast_croston_sba(
    meses: list[str],
    y: np.ndarray,
    horizonte: int = HORIZONTE_MAX,
    alpha: float = DEFAULT_ALPHA_CROSTON,
) -> Optional[list[float]]:
    """Croston clásico + corrección de sesgo SBA (Syntetos-Boylan
    Approximation): suaviza por separado el TAMAÑO de la demanda no-cero (z)
    y el INTERVALO entre demandas no-cero (p) con SES(alpha); tasa = z/p,
    corregida por (1 - alpha/2) para eliminar el sesgo positivo conocido de
    Croston puro. Pronóstico PLANO (igual para h=1,2,3): es una tasa
    promedio, no tiene componente de tendencia/estacionalidad."""
    n = len(y)
    if n < MIN_PUNTOS_ABSOLUTO:
        return None
    y = np.asarray(y, dtype=float)
    idx_no_cero = np.nonzero(np.abs(y) > EPS_DEMANDA)[0]
    if len(idx_no_cero) == 0:
        return [0.0] * horizonte  # nunca hubo demanda observada

    z = float(y[idx_no_cero[0]])
    p = float(idx_no_cero[0] + 1)  # periodos transcurridos hasta la primera demanda no-cero
    ultimo_no_cero = int(idx_no_cero[0])
    for i in idx_no_cero[1:]:
        i = int(i)
        q = float(i - ultimo_no_cero)
        z = alpha * y[i] + (1 - alpha) * z
        p = alpha * q + (1 - alpha) * p
        ultimo_no_cero = i

    tasa = z / p if p > EPS_DEMANDA else 0.0
    tasa_sba = tasa * (1 - alpha / 2)
    return [max(float(tasa_sba), 0.0)] * horizonte


FUNCIONES_ALGORITMOS = {
    "A1_seasonal_naive": forecast_seasonal_naive,
    "A2_media_movil_3m": forecast_media_movil,
    "A3_tendencia_estacional": forecast_tendencia_estacional,
    "A4_holt_winters": forecast_holt_winters,
    "A5_croston_sba": forecast_croston_sba,
}


# ---------------------------------------------------------------------------
# Rolling-origin: generación de orígenes y ejecución del backtest por serie
# ---------------------------------------------------------------------------

def generar_origenes(n_meses: int, horizonte: int = HORIZONTE_MAX, n_origenes: int = N_ORIGENES) -> list[int]:
    """Índices [0-based] de los meses ORIGEN válidos para rolling-origin:
    'entrenar con historia <= origen, pronosticar origen+1..origen+horizonte'.
    Un origen es válido si deja horizonte completo de meses reales para
    evaluar (origen + horizonte < n_meses). Devuelve los últimos
    `n_origenes` orígenes válidos: si la serie no tiene suficiente longitud,
    devuelve TODOS los que sí caben (nunca truncar en silencio -- el
    llamador compara len(resultado) contra n_origenes solicitado)."""
    max_origen = n_meses - 1 - horizonte
    if max_origen < 0:
        return []
    primero = max(0, max_origen - n_origenes + 1)
    return list(range(primero, max_origen + 1))


def backtest_serie(
    meses: list[str],
    valores: list[float],
    horizonte: int = HORIZONTE_MAX,
    n_origenes: int = N_ORIGENES,
    meses_censurados: Optional[set] = None,
) -> list[dict]:
    """Corre los 5 algoritmos sobre todos los orígenes rolling válidos de UNA
    serie (ya agregada a nivel material×canal o material×sucursal). Cada
    registro de salida es una observación (algoritmo, origen, horizonte)
    lista para agregar. `meses_censurados`: set de anio_mes (strings) de esa
    MISMA serie marcados con desabasto -- ver `detectar_meses_desabasto`."""
    meses_censurados = meses_censurados or set()
    n = len(meses)
    origenes = generar_origenes(n, horizonte, n_origenes)
    registros = []
    for origen in origenes:
        meses_train = meses[: origen + 1]
        y_train = np.asarray(valores[: origen + 1], dtype=float)
        for nombre, fn in FUNCIONES_ALGORITMOS.items():
            pred = fn(meses_train, y_train, horizonte)
            for h in range(1, horizonte + 1):
                idx_real = origen + h
                if idx_real >= n:
                    continue
                mes_evaluado = meses[idx_real]
                registros.append({
                    "algoritmo": nombre,
                    "mes_origen": meses[origen],
                    "horizonte": h,
                    "mes_evaluado": mes_evaluado,
                    "real": float(valores[idx_real]),
                    "prediccion": (pred[h - 1] if pred is not None else None),
                    "sin_prediccion": pred is None,
                    "censurado": mes_evaluado in meses_censurados,
                })
    return registros


# ---------------------------------------------------------------------------
# Agregación de métricas (WAPE, sesgo)
# ---------------------------------------------------------------------------

def agregar_wape_sesgo(registros: list[dict], group_keys: list[str]) -> tuple[list[dict], dict]:
    """WAPE = sum(|pred-real|) / sum(|real|) * 100 (agregado, no promedio de
    porcentajes por serie -- evita que series de bajo volumen con MAPE
    ruidoso dominen el resultado). sesgo = sum(pred-real) / sum(|real|) * 100
    (signado: >0 sobre-pronóstico, <0 sub-pronóstico). Excluye registros
    censurados y `sin_prediccion`; devuelve también un resumen de cuántos se
    excluyeron de cada tipo (nunca en silencio)."""
    grupos: dict[tuple, dict] = defaultdict(lambda: {"sum_abs_err": 0.0, "sum_err": 0.0, "sum_abs_real": 0.0, "n": 0})
    excluidos_censura = 0
    excluidos_sin_prediccion = 0
    for r in registros:
        if r["censurado"]:
            excluidos_censura += 1
            continue
        if r["sin_prediccion"]:
            excluidos_sin_prediccion += 1
            continue
        key = tuple(r[k] for k in group_keys)
        g = grupos[key]
        err = r["prediccion"] - r["real"]
        g["sum_abs_err"] += abs(err)
        g["sum_err"] += err
        g["sum_abs_real"] += abs(r["real"])
        g["n"] += 1

    salida = []
    for key, g in grupos.items():
        tiene_base = g["sum_abs_real"] > EPS_DEMANDA
        wape = (g["sum_abs_err"] / g["sum_abs_real"] * 100) if tiene_base else None
        sesgo = (g["sum_err"] / g["sum_abs_real"] * 100) if tiene_base else None
        fila = dict(zip(group_keys, key))
        fila.update({
            "wape_pct": round(wape, 2) if wape is not None else None,
            "sesgo_pct": round(sesgo, 2) if sesgo is not None else None,
            "n_observaciones": g["n"],
        })
        salida.append(fila)

    resumen_exclusiones = {
        "total_registros": len(registros),
        "excluidos_censura": excluidos_censura,
        "excluidos_sin_prediccion": excluidos_sin_prediccion,
        "usados": len(registros) - excluidos_censura - excluidos_sin_prediccion,
    }
    return salida, resumen_exclusiones


# ---------------------------------------------------------------------------
# Censura por desabasto (T23/v3 · kardex_diario)
# ---------------------------------------------------------------------------

def detectar_meses_desabasto(db: sqlite3.Connection, umbral_dias: int = 1) -> set[tuple[str, str, str]]:
    """Lee `kardex_diario` (si existe) y marca (material_id, plant, anio_mes)
    como desabasto si `saldo_fin_dia` <= 0 en >= `umbral_dias` días de ese
    mes. Si la tabla no existe -- dataset `data-real-car-v2`, sin kardex --
    devuelve set() vacío: el llamador DEBE reportar el run como preliminar
    sin censura (no hay forma de distinguir "sin desabasto" de "sin dato")."""
    existe = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='kardex_diario'"
    ).fetchone()
    if not existe:
        return set()
    filas = db.execute(
        """SELECT material_id, plant, substr(fecha, 1, 7) AS anio_mes, COUNT(*) AS dias_en_cero
           FROM kardex_diario
           WHERE saldo_fin_dia <= 0
           GROUP BY material_id, plant, anio_mes
           HAVING dias_en_cero >= ?""",
        (umbral_dias,),
    ).fetchall()
    return {(f["material_id"], f["plant"], f["anio_mes"]) for f in filas}


def meses_censurados_canal(meses_censurados_plant: set[tuple[str, str, str]], material_id: str, canal: str, plants_del_canal: dict[str, set[str]]) -> set[str]:
    """Un mes CANAL (agregado de varias sucursales) se marca censurado si
    CUALQUIERA de las sucursales de ese canal tuvo desabasto ese mes para ese
    material -- criterio conservador: preferible excluir de más que evaluar
    contra una demanda observada que en realidad está recortada por
    quiebre."""
    plants = plants_del_canal.get(canal, set())
    return {
        anio_mes for (mid, plant, anio_mes) in meses_censurados_plant
        if mid == material_id and plant in plants
    }


# ---------------------------------------------------------------------------
# Simulación de servicio (política de cobertura objetivo)
# ---------------------------------------------------------------------------

def simular_servicio_serie(
    meses: list[str],
    valores_m2: list[float],
    m2_por_caja: Optional[float],
    moq_cajas: int,
    cajas_por_pallet: Optional[int],
    objetivo_meses: float = DEFAULT_OBJETIVO_MESES,
    horizonte: int = HORIZONTE_MAX,
    n_origenes: int = N_ORIGENES,
) -> dict[str, dict]:
    """Simula, por algoritmo, la política de cobertura objetivo (RN-01
    simplificada -- ver limitaciones en el docstring del módulo) sobre los
    mismos orígenes rolling de `backtest_serie`. El pedido sugerido en cada
    origen usa `forecast(h=1)` de ESE algoritmo como demanda estimada;
    "quiebre" = la demanda real del mes siguiente superó el stock disponible
    al inicio de ese mes (lost sales, sin backorder acumulado -- se
    documenta como simplificación)."""
    n = len(meses)
    origenes = generar_origenes(n, horizonte, n_origenes)
    if not origenes:
        return {}

    valores_m2 = [float(v) for v in valores_m2]
    resultados: dict[str, dict] = {}
    for nombre, fn in FUNCIONES_ALGORITMOS.items():
        primer_origen = origenes[0]
        ventana_inicial = valores_m2[max(0, primer_origen - 2): primer_origen + 1]
        base_inicial_m2 = float(np.mean(ventana_inicial)) if ventana_inicial else 0.0
        stock_cajas = objetivo_meses * calc_m2_a_cajas(max(base_inicial_m2, 0.0), m2_por_caja)

        quiebres = 0
        meses_simulados = 0
        pedidos_totales_cajas = 0.0
        for origen in origenes:
            idx_siguiente = origen + 1
            if idx_siguiente >= n:
                continue
            meses_train = meses[: origen + 1]
            y_train = np.asarray(valores_m2[: origen + 1], dtype=float)
            pred = fn(meses_train, y_train, horizonte)
            forecast_h1_m2 = pred[0] if pred is not None else base_inicial_m2
            forecast_h1_cajas = calc_m2_a_cajas(max(forecast_h1_m2, 0.0), m2_por_caja)

            if forecast_h1_cajas <= EPS_DEMANDA:
                cobertura_actual = None
            else:
                cobertura_actual = stock_cajas / forecast_h1_cajas

            if cobertura_actual is None or cobertura_actual >= objetivo_meses:
                pedido_cajas = 0
            else:
                faltante = (objetivo_meses - cobertura_actual) * forecast_h1_cajas
                pedido_cajas = calc_redondeo_pallet(calc_redondeo_moq(faltante, moq_cajas), cajas_por_pallet)

            pedidos_totales_cajas += pedido_cajas
            stock_inicio = stock_cajas + pedido_cajas  # lead time <= 1 mes (simplificación, ver docstring)
            demanda_real_cajas = calc_m2_a_cajas(max(valores_m2[idx_siguiente], 0.0), m2_por_caja)

            if demanda_real_cajas > stock_inicio:
                quiebres += 1
            stock_cajas = max(stock_inicio - demanda_real_cajas, 0.0)
            meses_simulados += 1

        resultados[nombre] = {
            "quiebres": quiebres,
            "meses_simulados": meses_simulados,
            "tasa_quiebre_pct": round(quiebres / meses_simulados * 100, 1) if meses_simulados else None,
            "pedidos_totales_cajas": round(pedidos_totales_cajas, 1),
        }
    return resultados


# ---------------------------------------------------------------------------
# Estacionalidad por familia (agregado, sobre el universo completo)
# ---------------------------------------------------------------------------

UMBRAL_ESTACIONALIDAD_SIGNIFICATIVA_PCT = 8.0  # swing estacional / nivel medio >= 8% -> "significativa"


def analizar_estacionalidad_familia(meses: list[str], valores: list[float]) -> Optional[dict]:
    """Corre tendencia+estacionalidad (misma lógica de `engines/forecast.py`,
    vía `construir_forecast_serie`) sobre la serie AGREGADA de una familia
    completa (suma de todos sus material×canal). Con series agregadas el
    ruido individual se cancela, así que esto SÍ es una lectura confiable de
    si la familia tiene un patrón estacional real -- a diferencia de la señal
    por SKU-sucursal individual, que el ticket advierte que puede ser puro
    ruido."""
    resultado = construir_forecast_serie(list(meses), [float(v) for v in valores])
    if not resultado["suficiente_historia"] or not resultado["estacionalidad"]:
        return None
    estac = resultado["estacionalidad"]  # {mes_calendario(str): efecto_promedio}
    nivel_medio = float(np.mean(valores))
    if nivel_medio <= EPS_DEMANDA:
        return None
    mes_pico = max(estac, key=lambda m: estac[m])
    mes_valle = min(estac, key=lambda m: estac[m])
    swing_pct = (estac[mes_pico] - estac[mes_valle]) / nivel_medio * 100
    return {
        "nivel_medio_m2": round(nivel_medio, 1),
        "mes_pico": mes_pico,
        "efecto_pico_pct": round(estac[mes_pico] / nivel_medio * 100, 1),
        "mes_valle": mes_valle,
        "efecto_valle_pct": round(estac[mes_valle] / nivel_medio * 100, 1),
        "swing_pct": round(swing_pct, 1),
        "significativa": bool(swing_pct >= UMBRAL_ESTACIONALIDAD_SIGNIFICATIVA_PCT),
        # Mismo piso que RN-16 (GANADOR_BASE_MINIMA_M2, motor C2): con nivel
        # medio de familia por debajo de este umbral, un swing_pct grande es
        # más probable que sea efecto de base pequeña (ruido) que un patrón
        # comercial estacional real -- no descartar la familia, pero marcarla.
        "volumen_robusto": bool(nivel_medio >= GANADOR_BASE_MINIMA_M2),
        "tendencia": resultado["tendencia"]["clasificacion"] if resultado["tendencia"] else None,
    }


# ---------------------------------------------------------------------------
# Acceso a datos (I/O) -- SQLite standalone, sin depender de app.core.db /
# variables de entorno del server, para poder apuntar a cualquier .db (p.ej.
# data-real-car-v2 en /private/tmp, demasiado grande para versionarse).
# ---------------------------------------------------------------------------

def abrir_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def cargar_series(
    db: sqlite3.Connection,
    nivel: str,
    top_n: int,
    hasta_mes: Optional[str] = None,
    excluir_canales: tuple[str, ...] = CANALES_EXCLUIDOS,
) -> tuple[dict[tuple[str, str], tuple[list[str], list[float]]], dict]:
    """Carga TODAS las series material×canal (nivel='canal') o
    material×sucursal (nivel='sucursal') con una sola query agregada, y
    recorta a las `top_n` de mayor valor total. Devuelve también metadata de
    cobertura (nunca trunca en silencio: siempre se puede ver qué % del
    valor total del universo quedó representado en la muestra)."""
    if nivel not in ("canal", "sucursal"):
        raise ValueError("nivel debe ser 'canal' o 'sucursal'")
    campo = "canal" if nivel == "canal" else "plant"

    placeholders = ",".join("?" * len(excluir_canales))
    where = [f"canal NOT IN ({placeholders})"]
    params: list = list(excluir_canales)
    if hasta_mes:
        where.append("anio_mes <= ?")
        params.append(hasta_mes)
    where_sql = " AND ".join(where)

    filas = db.execute(
        f"""SELECT material_id, {campo} AS clave, anio_mes, SUM(cantidad_m2) AS valor
            FROM ventas_mensuales
            WHERE {where_sql}
            GROUP BY material_id, {campo}, anio_mes
            ORDER BY material_id, {campo}, anio_mes ASC""",
        params,
    ).fetchall()

    series: dict[tuple[str, str], tuple[list[str], list[float]]] = defaultdict(lambda: ([], []))
    totales: dict[tuple[str, str], float] = defaultdict(float)
    for f in filas:
        key = (f["material_id"], f["clave"])
        meses_k, valores_k = series[key]
        meses_k.append(f["anio_mes"])
        valores_k.append(float(f["valor"]))
        totales[key] += float(f["valor"])

    total_universo = len(series)
    total_valor = sum(totales.values())
    top_keys = sorted(totales, key=lambda k: -totales[k])[:top_n]
    valor_top = sum(totales[k] for k in top_keys)
    seleccion = {k: series[k] for k in top_keys}

    meta = {
        "nivel": nivel,
        "total_universo_pares": total_universo,
        "top_n_solicitado": top_n,
        "top_n_efectivo": len(seleccion),
        "valor_total_universo_m2": round(total_valor, 1),
        "valor_top_n_m2": round(valor_top, 1),
        "cobertura_valor_pct": round(valor_top / total_valor * 100, 1) if total_valor > EPS_DEMANDA else None,
    }
    return seleccion, meta


def cargar_materiales(db: sqlite3.Connection) -> dict[str, dict]:
    filas = db.execute(
        "SELECT material_id, descripcion, familia, abc, m2_por_caja FROM materiales"
    ).fetchall()
    return {f["material_id"]: dict(f) for f in filas}


def cargar_politica_material(db: sqlite3.Connection) -> dict[str, dict]:
    """moq/pallet/objetivo por material, con los mismos defaults que el motor
    C1 real (`engines/sugeridos.py`) cuando el material no tiene fila."""
    filas = db.execute(
        """SELECT m.material_id,
                  COALESCE(pr.moq_cajas, ?) AS moq_cajas,
                  COALESCE(pr.cajas_por_pallet, ?) AS cajas_por_pallet,
                  COALESCE(c.meses_objetivo, ?) AS meses_objetivo
           FROM materiales m
           LEFT JOIN proveedores pr ON pr.material_id = m.material_id
           LEFT JOIN coberturas_objetivo c ON c.material_id = m.material_id""",
        (DEFAULT_MOQ, DEFAULT_PALLET, DEFAULT_OBJETIVO_MESES),
    ).fetchall()
    return {f["material_id"]: dict(f) for f in filas}


def cargar_plants_por_canal(db: sqlite3.Connection) -> dict[str, set[str]]:
    filas = db.execute("SELECT plant, canal FROM sucursales").fetchall()
    salida: dict[str, set[str]] = defaultdict(set)
    for f in filas:
        salida[f["canal"]].add(f["plant"])
    return salida


def cargar_familia_agregada(
    db: sqlite3.Connection,
    hasta_mes: Optional[str] = None,
    excluir_canales: tuple[str, ...] = CANALES_EXCLUIDOS,
) -> dict[str, tuple[list[str], list[float]]]:
    """Serie mensual agregada por familia (TODO el universo material×plant,
    sin recorte top-N -- para estacionalidad se quiere la lectura más limpia
    posible del ciclo anual real). Excluye Outlet/Remates (RN-04, mismo
    criterio que el resto del módulo): son liquidación de excedente, no
    demanda regular, y meterlos distorsionaría el patrón estacional real."""
    placeholders = ",".join("?" * len(excluir_canales))
    where = [f"v.canal NOT IN ({placeholders})"]
    params: list = list(excluir_canales)
    if hasta_mes:
        where.append("v.anio_mes <= ?")
        params.append(hasta_mes)
    filas = db.execute(
        f"""SELECT m.familia AS familia, v.anio_mes AS anio_mes, SUM(v.cantidad_m2) AS valor
            FROM ventas_mensuales v
            JOIN materiales m ON m.material_id = v.material_id
            WHERE {" AND ".join(where)}
            GROUP BY m.familia, v.anio_mes
            ORDER BY m.familia, v.anio_mes ASC""",
        params,
    ).fetchall()
    series: dict[str, tuple[list[str], list[float]]] = defaultdict(lambda: ([], []))
    for f in filas:
        meses_k, valores_k = series[f["familia"]]
        meses_k.append(f["anio_mes"])
        valores_k.append(float(f["valor"]))
    return series


# ---------------------------------------------------------------------------
# Orquestación del torneo completo
# ---------------------------------------------------------------------------

def _etiquetar_registros(registros: list[dict], material_id: str, clave: str, nivel: str, materiales: dict[str, dict]) -> None:
    info = materiales.get(material_id, {})
    for r in registros:
        r["material_id"] = material_id
        r["clave"] = clave  # canal o plant, según `nivel`
        r["nivel"] = nivel
        r["abc"] = info.get("abc")
        r["familia"] = info.get("familia")


def ejecutar_torneo(
    db_path: str,
    top_n_canal: int = 300,
    top_n_sucursal: int = 300,
    hasta_mes: Optional[str] = None,
    n_origenes: int = N_ORIGENES,
    horizonte: int = HORIZONTE_MAX,
) -> dict:
    """Corre el torneo completo: carga datos, backtest rolling-origin a nivel
    canal y a nivel sucursal, agregación WAPE/sesgo (global, por ABC, por
    familia), simulación de servicio a nivel sucursal, y estacionalidad por
    familia sobre el universo completo. Devuelve un dict serializable a JSON."""
    db = abrir_db(db_path)
    try:
        materiales = cargar_materiales(db)
        meses_desabasto_plant = detectar_meses_desabasto(db)
        censura_disponible = len(meses_desabasto_plant) > 0 or _tabla_existe(db, "kardex_diario")
        plants_por_canal = cargar_plants_por_canal(db)

        series_canal, meta_canal = cargar_series(db, "canal", top_n_canal, hasta_mes)
        series_sucursal, meta_sucursal = cargar_series(db, "sucursal", top_n_sucursal, hasta_mes)

        registros_canal: list[dict] = []
        for (material_id, canal), (meses, valores) in series_canal.items():
            censurados = meses_censurados_canal(meses_desabasto_plant, material_id, canal, plants_por_canal)
            regs = backtest_serie(meses, valores, horizonte, n_origenes, censurados)
            _etiquetar_registros(regs, material_id, canal, "canal", materiales)
            registros_canal.extend(regs)

        registros_sucursal: list[dict] = []
        for (material_id, plant), (meses, valores) in series_sucursal.items():
            censurados = {
                anio_mes for (mid, pl, anio_mes) in meses_desabasto_plant
                if mid == material_id and pl == plant
            }
            regs = backtest_serie(meses, valores, horizonte, n_origenes, censurados)
            _etiquetar_registros(regs, material_id, plant, "sucursal", materiales)
            registros_sucursal.extend(regs)

        # --- Agregaciones WAPE/sesgo -----------------------------------
        agregaciones = {}
        for nivel, registros in (("canal", registros_canal), ("sucursal", registros_sucursal)):
            tabla_global, resumen_global = agregar_wape_sesgo(registros, ["algoritmo", "horizonte"])
            tabla_abc, _ = agregar_wape_sesgo(registros, ["algoritmo", "horizonte", "abc"])
            tabla_familia, _ = agregar_wape_sesgo(registros, ["algoritmo", "familia"])
            agregaciones[nivel] = {
                "global": sorted(tabla_global, key=lambda r: (r["horizonte"], r["algoritmo"])),
                "por_abc": sorted(tabla_abc, key=lambda r: (r["horizonte"], r["abc"] or "", r["algoritmo"])),
                "por_familia": sorted(tabla_familia, key=lambda r: (r["familia"] or "", r["algoritmo"])),
                "resumen_exclusiones": resumen_global,
            }

        # --- Simulación de servicio (solo nivel sucursal -- MOQ/pallet
        #     operan por material×plant, no tiene sentido a nivel canal) ---
        politica = cargar_politica_material(db)
        servicio_por_algoritmo: dict[str, dict] = {n: {"quiebres": 0, "meses_simulados": 0, "pedidos_totales_cajas": 0.0} for n in NOMBRES_ALGORITMOS}
        series_simuladas = 0
        for (material_id, plant), (meses, valores) in series_sucursal.items():
            info_mat = materiales.get(material_id, {})
            pol = politica.get(material_id, {"moq_cajas": DEFAULT_MOQ, "cajas_por_pallet": DEFAULT_PALLET, "meses_objetivo": DEFAULT_OBJETIVO_MESES})
            resultado_sim = simular_servicio_serie(
                meses, valores,
                m2_por_caja=info_mat.get("m2_por_caja"),
                moq_cajas=int(pol["moq_cajas"]),
                cajas_por_pallet=int(pol["cajas_por_pallet"]) if pol["cajas_por_pallet"] else None,
                objetivo_meses=float(pol["meses_objetivo"]),
                horizonte=horizonte,
                n_origenes=n_origenes,
            )
            if resultado_sim:
                series_simuladas += 1
            for nombre, r in resultado_sim.items():
                acc = servicio_por_algoritmo[nombre]
                acc["quiebres"] += r["quiebres"]
                acc["meses_simulados"] += r["meses_simulados"]
                acc["pedidos_totales_cajas"] += r["pedidos_totales_cajas"]

        quiebres_baseline = servicio_por_algoritmo[BASELINE_ALGORITMO]["quiebres"]
        for nombre, acc in servicio_por_algoritmo.items():
            acc["pedidos_totales_cajas"] = round(acc["pedidos_totales_cajas"], 1)
            acc["tasa_quiebre_pct"] = round(acc["quiebres"] / acc["meses_simulados"] * 100, 2) if acc["meses_simulados"] else None
            acc["quiebres_vs_baseline"] = acc["quiebres"] - quiebres_baseline  # negativo = mejora vs. A2 (motor C1 hoy)
        servicio = {
            "baseline": BASELINE_ALGORITMO,
            "series_simuladas": series_simuladas,
            "por_algoritmo": servicio_por_algoritmo,
        }

        # --- Estacionalidad por familia ---------------------------------
        familias_series = cargar_familia_agregada(db, hasta_mes)
        estacionalidad_familias = {}
        familias_sin_historia_suficiente = []
        for familia, (meses, valores) in familias_series.items():
            r = analizar_estacionalidad_familia(meses, valores)
            if r is not None:
                estacionalidad_familias[familia] = r
            else:
                familias_sin_historia_suficiente.append(familia)

        return {
            "generado_por": "T25 (waykee 290123) -- backend/analysis/backtest_forecast.py",
            "db_path": db_path,
            "hasta_mes": hasta_mes,
            "horizonte_max": horizonte,
            "n_origenes_solicitados": n_origenes,
            "censura_disponible": censura_disponible,
            "meses_desabasto_detectados": len(meses_desabasto_plant),
            "meta_canal": meta_canal,
            "meta_sucursal": meta_sucursal,
            "agregaciones": agregaciones,
            "servicio": servicio,
            "estacionalidad_por_familia": estacionalidad_familias,
            "estacionalidad_familias_total_universo": len(familias_series),
            "estacionalidad_familias_sin_historia_suficiente": sorted(familias_sin_historia_suficiente),
        }
    finally:
        db.close()


def _tabla_existe(db: sqlite3.Connection, nombre: str) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nombre,)
    ).fetchone() is not None


# ---------------------------------------------------------------------------
# Reporte Markdown
# ---------------------------------------------------------------------------

def _tabla_md(filas: list[dict], columnas: list[str]) -> str:
    if not filas:
        return "_(sin datos)_\n"
    out = ["| " + " | ".join(columnas) + " |", "| " + " | ".join("---" for _ in columnas) + " |"]
    for f in filas:
        out.append("| " + " | ".join(str(f.get(c, "")) for c in columnas) + " |")
    return "\n".join(out) + "\n"


def _ganador_por_segmento(tabla_global: list[dict], min_observaciones: int = 30) -> dict[int, dict]:
    """Para cada horizonte, el algoritmo con menor WAPE (solo entre los que
    tienen al menos `min_observaciones` -- evita que un grupo con pocos datos
    "gane" por ruido)."""
    por_horizonte: dict[int, list[dict]] = defaultdict(list)
    for f in tabla_global:
        if f["wape_pct"] is not None and f["n_observaciones"] >= min_observaciones:
            por_horizonte[f["horizonte"]].append(f)
    return {h: min(filas, key=lambda f: f["wape_pct"]) for h, filas in por_horizonte.items()}


def generar_markdown(reporte: dict) -> str:
    lineas = []
    lineas.append("# T25 · Torneo de pronósticos -- 5 algoritmos, backtest rolling-origin (h=1..3)\n")
    lineas.append(f"Waykee 290123. DB: `{reporte['db_path']}`. Corte de datos: hasta `{reporte['hasta_mes']}`.\n")
    if reporte["censura_disponible"]:
        lineas.append(f"**Censura por desabasto ACTIVA** ({reporte['meses_desabasto_detectados']} pares material-plant-mes excluidos).\n")
    else:
        lineas.append(
            "**PRELIMINAR -- SIN CENSURA.** El dataset usado (`data-real-car-v2`) no trae `kardex_diario` todavía "
            "(release `data-real-car-v3`, T23 en curso). Ningún mes fue excluido por desabasto: la demanda observada "
            "en meses con quiebre real (si los hubo) se está tratando como demanda verdadera, lo que puede sesgar "
            "el WAPE hacia abajo en materiales con historial de quiebres. Re-correr este mismo script contra v3 en "
            "cuanto el kardex esté disponible.\n"
        )

    for nivel, meta_key in (("canal", "meta_canal"), ("sucursal", "meta_sucursal")):
        meta = reporte[meta_key]
        lineas.append(
            f"\n## Nivel `{nivel}`\n\nUniverso: {meta['total_universo_pares']} pares material×{nivel}. "
            f"Se evaluaron los top **{meta['top_n_efectivo']}** por valor "
            f"({meta['cobertura_valor_pct']}% del valor total de ese universo).\n"
        )
        agg = reporte["agregaciones"][nivel]
        exc = agg["resumen_exclusiones"]
        lineas.append(
            f"Observaciones: {exc['total_registros']} generadas, {exc['excluidos_sin_prediccion']} sin predicción "
            f"(historia insuficiente para ese algoritmo), {exc['excluidos_censura']} censuradas por desabasto, "
            f"**{exc['usados']} usadas** para las métricas de abajo.\n"
        )
        lineas.append("\n### WAPE / sesgo por algoritmo x horizonte\n")
        lineas.append(_tabla_md(agg["global"], ["algoritmo", "horizonte", "wape_pct", "sesgo_pct", "n_observaciones"]))

        ganadores = _ganador_por_segmento(agg["global"])
        if ganadores:
            lineas.append("\n**Ganador por horizonte (menor WAPE, min. 30 observaciones):**\n")
            for h in sorted(ganadores):
                g = ganadores[h]
                lineas.append(f"- h={h}: `{g['algoritmo']}` (WAPE {g['wape_pct']}%, sesgo {g['sesgo_pct']}%, n={g['n_observaciones']})\n")

        lineas.append("\n### WAPE por algoritmo x horizonte x ABC\n")
        lineas.append(_tabla_md(agg["por_abc"], ["algoritmo", "horizonte", "abc", "wape_pct", "sesgo_pct", "n_observaciones"]))

        top_familias = sorted(
            {f["familia"] for f in agg["por_familia"] if f["familia"]},
            key=lambda fam: -sum(f["n_observaciones"] for f in agg["por_familia"] if f["familia"] == fam),
        )[:8]
        filas_top_familias = [f for f in agg["por_familia"] if f["familia"] in top_familias]
        lineas.append(f"\n### WAPE por algoritmo x familia (top 8 familias por volumen de observaciones -- tabla completa en el JSON)\n")
        lineas.append(_tabla_md(filas_top_familias, ["algoritmo", "familia", "wape_pct", "sesgo_pct", "n_observaciones"]))

    lineas.append("\n## Simulación de servicio (cobertura objetivo, nivel sucursal)\n")
    lineas.append(
        f"Simulación SIMPLIFICADA (sin RN-02/transferencias, lead time <= 1 mes -- ver limitaciones en el docstring "
        f"del módulo). {reporte['servicio']['series_simuladas']} series material×sucursal simuladas. "
        f"Baseline = `{reporte['servicio']['baseline']}` (motor C1 vigente hoy).\n"
    )
    filas_servicio = [{"algoritmo": k, **v} for k, v in reporte["servicio"]["por_algoritmo"].items()]
    lineas.append(_tabla_md(
        sorted(filas_servicio, key=lambda f: f["algoritmo"]),
        ["algoritmo", "quiebres", "meses_simulados", "tasa_quiebre_pct", "quiebres_vs_baseline", "pedidos_totales_cajas"],
    ))

    lineas.append("\n## Estacionalidad por familia (agregado, universo completo)\n")
    total_universo = reporte.get("estacionalidad_familias_total_universo", len(reporte["estacionalidad_por_familia"]))
    sin_historia = reporte.get("estacionalidad_familias_sin_historia_suficiente", [])
    significativas = {k: v for k, v in reporte["estacionalidad_por_familia"].items() if v["significativa"]}
    no_significativas = {k: v for k, v in reporte["estacionalidad_por_familia"].items() if not v["significativa"]}
    lineas.append(
        f"Universo: {total_universo} familias con ventas en el periodo. {len(sin_historia)} NO se pudieron evaluar "
        f"(< {MIN_PUNTOS_ESTACIONALIDAD} meses distintos con venta o historia insuficiente para ajustar "
        f"tendencia+estacionalidad) -- quedan excluidas del análisis, no contadas como 'no significativas'.\n"
    )
    lineas.append(
        f"De las {len(reporte['estacionalidad_por_familia'])} familias SÍ evaluadas: {len(significativas)} "
        f"(swing pico-valle >= {UMBRAL_ESTACIONALIDAD_SIGNIFICATIVA_PCT}% del nivel medio) muestran estacionalidad "
        f"SIGNIFICATIVA; {len(no_significativas)} no la muestran.\n"
    )
    robustas = {k: v for k, v in significativas.items() if v["volumen_robusto"]}
    ruido_base_chica = {k: v for k, v in significativas.items() if not v["volumen_robusto"]}
    lineas.append(
        f"De esas {len(significativas)} significativas, {len(robustas)} tienen volumen robusto "
        f"(nivel medio >= {GANADOR_BASE_MINIMA_M2:g} m2/mes, mismo piso que RN-16/GANADOR_BASE_MINIMA_M2 del motor C2) "
        f"y son lectura confiable; las {len(ruido_base_chica)} restantes tienen nivel medio por debajo de ese piso -- "
        f"swings de cientos de % ahí son más probablemente efecto de base pequeña (ruido) que un patrón comercial real, "
        f"y se listan aparte para no confundirlas con las señales fuertes (p.ej. PORCELANATO, FIREN, AZUVI, GREDA).\n"
    )
    lineas.append("\n**Familias con volumen robusto (lectura confiable), ordenadas por swing:**\n")
    filas_robustas = sorted([{"familia": k, **v} for k, v in robustas.items()], key=lambda f: -f["swing_pct"])[:15]
    lineas.append(_tabla_md(filas_robustas, ["familia", "nivel_medio_m2", "mes_pico", "efecto_pico_pct", "mes_valle", "efecto_valle_pct", "swing_pct", "tendencia"]))
    if ruido_base_chica:
        lineas.append("\n**Familias de base pequeña (swings grandes probablemente ruido, NO tratar como señal comercial fuerte):**\n")
        filas_ruido = sorted([{"familia": k, **v} for k, v in ruido_base_chica.items()], key=lambda f: -f["swing_pct"])[:15]
        lineas.append(_tabla_md(filas_ruido, ["familia", "nivel_medio_m2", "mes_pico", "efecto_pico_pct", "mes_valle", "efecto_valle_pct", "swing_pct", "tendencia"]))

    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--db-path", required=True, help="Ruta al .db (p.ej. data-real-car-v2, no versionado en git por tamaño)")
    parser.add_argument("--top-n-canal", type=int, default=300)
    parser.add_argument("--top-n-sucursal", type=int, default=300)
    parser.add_argument("--hasta-mes", default=None, help="YYYY-MM del último mes COMPLETO a incluir (excluye el mes en curso, parcial)")
    parser.add_argument("--n-origenes", type=int, default=N_ORIGENES)
    parser.add_argument("--output-dir", default=str(BACKEND_DIR / "analysis" / "results"))
    parser.add_argument("--tag", default=None, help="Sufijo del nombre de archivo de salida (default: timestamp UTC)")
    args = parser.parse_args(argv)

    reporte = ejecutar_torneo(
        db_path=args.db_path,
        top_n_canal=args.top_n_canal,
        top_n_sucursal=args.top_n_sucursal,
        hasta_mes=args.hasta_mes,
        n_origenes=args.n_origenes,
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = args.tag or datetime.now(timezone.utc).strftime("%Y%m%d")
    json_path = out_dir / f"T25_backtest_forecast_{tag}.json"
    md_path = out_dir / f"T25_backtest_forecast_{tag}.md"

    json_path.write_text(json.dumps(reporte, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(generar_markdown(reporte), encoding="utf-8")

    print(f"JSON  -> {json_path}")
    print(f"MD    -> {md_path}")
    for nivel in ("canal", "sucursal"):
        meta = reporte[f"meta_{nivel}"]
        print(f"[{nivel}] top {meta['top_n_efectivo']}/{meta['total_universo_pares']} pares, cobertura {meta['cobertura_valor_pct']}% del valor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
