"""Motor C2 · Forecast por canal (ML clásico, sin dependencias pesadas).

Implementa el contrato descrito en README_MOTORES.py para el motor de
Machine Learning tradicional (capa C2):

  - Forecast mensual por CANAL independiente (Menudeo/Mayoreo/eCommerce).
    Outlet y Remates quedan siempre excluidos del forecast (RN-04): no son
    demanda regular, son liquidación de excedente y meterlos en la serie
    distorsiona tendencia y estacionalidad.
  - Descomposición simple tendencia + estacionalidad (OLS + promedio de
    residuales por mes-calendario), implementada con numpy puro — sin
    statsmodels/pandas, para mantener el contenedor Docker ligero.
  - Detección de picos atípicos (RN-14) con Modified Z-Score (mediana + MAD)
    sobre los RESIDUALES de un ajuste de tendencia robusto (Theil-Sen), no
    sobre los valores crudos (T22 fix — ver `detectar_atipicos`), con
    fallback a IQR cuando la dispersión de residuales es casi nula (MAD=0).
    Además, cualquier racha de 2+ meses CONSECUTIVOS marcados en la misma
    dirección se "rescata" (no se excluye): un pico atípico es por
    definición una anomalía puntual y transitoria, no un cambio de nivel
    sostenido (p.ej. una plaza que empieza a vender 100x más y lo
    mantiene). Los picos que sí quedan se MARCAN en la serie devuelta pero
    se EXCLUYEN del ajuste de tendencia/estacionalidad — no se borran del
    histórico, solo no contaminan el fit.
  - Clasificación de tendencia (creciente/estable/decreciente) usando el
    t-stat de la pendiente OLS, y flag `producto_ganador` (RN-16) cuando la
    tendencia es creciente y significativa Y el crecimiento reciente supera
    un umbral mínimo.
  - MAPE de backtest sobre el último trimestre (re-ajusta el modelo con los
    datos previos al trimestre y compara la predicción contra lo real) para
    mostrar credibilidad del forecast en la UI.

Endpoints:
  GET /api/engines/forecast/{material_id}/{plant_o_canal}
      Forecast + tendencia + backtest de un material. `plant_o_canal` acepta
      un canal directo (Menudeo/Mayoreo/eCommerce) o un código de plant, que
      se resuelve a su canal vía `sucursales`. El forecast SIEMPRE se calcula
      a nivel canal (agregando todas las plants de ese canal) porque una
      sola sucursal suele tener demasiado ruido mes a mes para un fit
      confiable; si se pasó un plant, se agrega igual a nivel canal y se
      informa explícitamente en la respuesta (`nivel_agregacion`).
  GET /api/engines/forecast/tendencias/ganadores
      Lista de productos ganadores (RN-16) evaluando TODOS los pares
      material×canal vigentes (excluye Outlet/Remates). Cacheado 10 min
      porque con el dataset real (1,800 SKU) evaluar todo el universo en
      cada request es costoso y esta lista no cambia mes a mes.
  GET /api/engines/forecast/precision
      MAPE de backtest: detalle de un material+canal puntual, o resumen
      global sobre una MUESTRA explícita (nunca trunca en silencio: siempre
      informa cuántas series se evaluaron sobre cuántas totales).

Alias de compatibilidad con el ticket original (T5): se registran también
bajo /api/forecast/... y /api/tendencias/ganadores en app/main.py, apuntando
a los mismos handlers.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
import sqlite3

from app.core.db import get_db

router = APIRouter(prefix="/api/engines/forecast", tags=["engines:forecast"])

# ---------------------------------------------------------------------------
# Parámetros del motor
# ---------------------------------------------------------------------------

CANALES_VALIDOS = {"Menudeo", "Mayoreo", "eCommerce", "Outlet", "Remates"}
CANALES_EXCLUIDOS = {"Outlet", "Remates"}  # RN-04: liquidación de excedente, no demanda regular

MIN_PUNTOS_FORECAST = 6          # mínimo de meses (no atípicos) para intentar un fit
MIN_PUNTOS_ESTACIONALIDAD = 12   # bajo esto no hay ciclo anual completo -> estacionalidad plana
Z_SCORE_THRESHOLD = 3.5          # umbral estándar de Modified Z-Score (Iglewicz & Hoaglin)
HORIZONTE_FORECAST = 3           # meses a proyectar hacia adelante
MESES_BACKTEST = 3               # último trimestre, retenido para el MAPE
TREND_TSTAT_SIGNIFICATIVO = 2.0  # |t| > 2 ~ p < 0.05 aprox para muestras chicas
GANADOR_CRECIMIENTO_MIN = 0.10   # RN-16: >=10% crecimiento reciente vs previo
GANADOR_BASE_MINIMA_M2 = 10.0    # RN-16 (T22): piso de demanda previa -- evita "ganadores"
                                  # que en realidad son ruido/efecto base pequeña (p.ej. 0.5 -> 5
                                  # m2/mes ya es +900% y no es una señal comercial real)

_CACHE_GANADORES: dict[str, tuple[float, dict]] = {}
CACHE_TTL_SEGUNDOS = 600  # 10 min


# ---------------------------------------------------------------------------
# Funciones puras (sin I/O) — testeables 1:1
# ---------------------------------------------------------------------------

def _pendiente_theil_sen(t: np.ndarray, y: np.ndarray) -> float:
    """Estimador Theil-Sen: mediana de las pendientes de TODOS los pares de
    puntos. Robusto a atípicos (a diferencia de OLS, que un solo pico puede
    arrastrar). Con el horizonte de este motor (típicamente <=24 meses) el
    costo O(n²) de las pendientes por pares es trivial (<=276 pares)."""
    n = len(t)
    if n < 2:
        return 0.0
    pendientes = [
        (y[j] - y[i]) / (t[j] - t[i])
        for i in range(n) for j in range(i + 1, n)
        if (t[j] - t[i]) > 1e-9
    ]
    return float(np.median(pendientes)) if pendientes else 0.0


def _descartar_rachas_sostenidas(candidatos: np.ndarray, residuales: np.ndarray) -> np.ndarray:
    """Un PICO atípico (RN-14) es por definición una anomalía puntual y
    transitoria. Si 2+ meses CONSECUTIVOS quedan marcados como candidatos en
    la MISMA dirección (incluso en la cola de la serie), ya no es un pico:
    es un cambio de nivel sostenido y legítimo (p.ej. una plaza que empieza
    a vender 100x más y lo mantiene) -- se rescata para que sí alimente
    tendencia/estacionalidad/crecimiento. Solo sobreviven como atípicos los
    meses verdaderamente aislados."""
    n = len(candidatos)
    resultado = candidatos.copy()
    i = 0
    while i < n:
        if not candidatos[i]:
            i += 1
            continue
        signo = np.sign(residuales[i])
        j = i + 1
        while j < n and candidatos[j] and np.sign(residuales[j]) == signo:
            j += 1
        if (j - i) >= 2:
            resultado[i:j] = False
        i = j
    return resultado


def detectar_atipicos(t: np.ndarray, valores: np.ndarray) -> np.ndarray:
    """Modified Z-Score (mediana + MAD) sobre los RESIDUALES de un ajuste de
    tendencia robusto (Theil-Sen), NO sobre los valores crudos (T22 fix).

    Motivo: con mediana+MAD de los valores crudos, un cambio de RÉGIMEN
    legítimo y sostenido (p.ej. una serie que vendía 2-17 m2/mes y de un mes
    a otro empieza a vender 2,500-4,500 m2/mes) hace que la mediana
    histórica sea minúscula y los meses NUEVOS -- el nivel real actual --
    queden marcados "atípicos", justo lo opuesto de lo que se busca. Mirar
    el residual contra una tendencia robusta, más la regla de persistencia
    en `_descartar_rachas_sostenidas`, evita ese falso positivo: solo los
    picos/valles puntuales que rompen la racha siguen marcándose.

    Fallback a IQR si MAD de los residuales es 0 (dispersión casi nula,
    donde MAD colapsaría el umbral y marcaría todo como atípico)."""
    n = len(valores)
    if n < 4:
        return np.zeros(n, dtype=bool)

    pendiente = _pendiente_theil_sen(t, valores)
    intercepto = float(np.median(valores - pendiente * t))
    residuales = valores - (intercepto + pendiente * t)

    mediana = np.median(residuales)
    mad = np.median(np.abs(residuales - mediana))
    if mad > 1e-9:
        mz = 0.6745 * (residuales - mediana) / mad
        candidatos = np.abs(mz) > Z_SCORE_THRESHOLD
    else:
        q1, q3 = np.percentile(residuales, [25, 75])
        iqr = q3 - q1
        if iqr <= 1e-9:
            candidatos = np.zeros(n, dtype=bool)
        else:
            lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            candidatos = (residuales < lower) | (residuales > upper)

    return _descartar_rachas_sostenidas(candidatos, residuales)


def ajustar_tendencia(t: np.ndarray, y: np.ndarray) -> dict:
    """OLS simple y = a + b*t sobre los puntos ya limpios de atípicos.
    Devuelve pendiente, intercepto, t-stat de la pendiente y clasificación."""
    n = len(t)
    if n == 0:
        return {"pendiente": 0.0, "intercepto": 0.0, "t_stat": 0.0, "clasificacion": "sin_datos"}
    if n == 1:
        return {"pendiente": 0.0, "intercepto": float(y[0]), "t_stat": 0.0, "clasificacion": "insuficiente"}

    t_mean, y_mean = float(t.mean()), float(y.mean())
    ss_t = float(np.sum((t - t_mean) ** 2))
    pendiente = float(np.sum((t - t_mean) * (y - y_mean)) / ss_t) if ss_t > 1e-9 else 0.0
    intercepto = y_mean - pendiente * t_mean

    t_stat = 0.0
    if n > 2 and ss_t > 1e-9:
        residuales = y - (intercepto + pendiente * t)
        s2 = float(np.sum(residuales ** 2) / (n - 2))
        se_pendiente = math.sqrt(s2 / ss_t) if s2 > 1e-9 else 0.0
        t_stat = pendiente / se_pendiente if se_pendiente > 1e-9 else 0.0

    if n < 4:
        clasificacion = "insuficiente"
    elif t_stat > TREND_TSTAT_SIGNIFICATIVO:
        clasificacion = "creciente"
    elif t_stat < -TREND_TSTAT_SIGNIFICATIVO:
        clasificacion = "decreciente"
    else:
        clasificacion = "estable"

    return {"pendiente": pendiente, "intercepto": intercepto, "t_stat": t_stat, "clasificacion": clasificacion}


def calc_estacionalidad(meses_calendario: list[int], residuales: np.ndarray) -> dict[int, float]:
    """Promedio de residuales (tras quitar tendencia) agrupado por mes del
    año (1-12). Con <12 meses de historia limpia no hay ciclo completo:
    se devuelve un diccionario vacío (estacionalidad plana)."""
    if len(meses_calendario) < MIN_PUNTOS_ESTACIONALIDAD:
        return {}
    agrupado: dict[int, list[float]] = defaultdict(list)
    for mes, r in zip(meses_calendario, residuales):
        agrupado[mes].append(float(r))
    return {mes: float(np.mean(vals)) for mes, vals in agrupado.items()}


def calc_mape(actual: np.ndarray, pred: np.ndarray) -> Optional[float]:
    """MAPE en %. Ignora meses con actual=0 (división indefinida) — si TODOS
    son cero, devuelve None en vez de fingir precisión perfecta."""
    mask = np.abs(actual) > 1e-9
    if not mask.any():
        return None
    return float(np.mean(np.abs((actual[mask] - pred[mask]) / actual[mask])) * 100)


def _siguiente_mes(anio_mes: str, offset: int) -> str:
    anio, mes = int(anio_mes[:4]), int(anio_mes[5:7])
    total = (anio * 12 + (mes - 1)) + offset
    return f"{total // 12:04d}-{(total % 12) + 1:02d}"


def _mes_calendario(anio_mes: str) -> int:
    return int(anio_mes[5:7])


def construir_forecast_serie(meses: list[str], valores: list[float]) -> dict:
    """Núcleo del motor: dado un histórico mensual ordenado cronológicamente,
    detecta atípicos, ajusta tendencia+estacionalidad SOLO con puntos limpios,
    clasifica tendencia, evalúa producto_ganador, corre backtest del último
    trimestre y proyecta HORIZONTE_FORECAST meses hacia adelante."""
    n = len(meses)
    y = np.array(valores, dtype=float)
    t = np.arange(n, dtype=float)
    atipicos = detectar_atipicos(t, y) if n > 0 else np.zeros(0, dtype=bool)

    serie_historica = [
        {"anio_mes": meses[i], "valor_m2": round(float(y[i]), 2), "es_atipico": bool(atipicos[i])}
        for i in range(n)
    ]

    limpio = ~atipicos
    n_limpio = int(limpio.sum())
    if n_limpio < MIN_PUNTOS_FORECAST:
        return {
            "suficiente_historia": False,
            "meses_disponibles": n,
            "meses_usados": n_limpio,
            "minimo_requerido": MIN_PUNTOS_FORECAST,
            "serie_historica": serie_historica,
            "tendencia": None,
            "estacionalidad": {},
            "forecast": [],
            "backtest": None,
            "producto_ganador": False,
            "crecimiento_pct": None,
            "base_previa_m2": None,
        }

    t_limpio, y_limpio = t[limpio], y[limpio]
    meses_limpio = [meses[i] for i in range(n) if limpio[i]]
    tendencia = ajustar_tendencia(t_limpio, y_limpio)

    residuales_limpio = y_limpio - (tendencia["intercepto"] + tendencia["pendiente"] * t_limpio)
    calendario_limpio = [_mes_calendario(m) for m in meses_limpio]
    estacionalidad = calc_estacionalidad(calendario_limpio, residuales_limpio)

    # Crecimiento reciente (T22 fix): últimos 3 MESES CALENDARIO reales vs
    # los 3 anteriores, tomados directamente de la serie ORIGINAL (y, no
    # y_limpio) -- así siempre son 6 meses contiguos del calendario, con su
    # valor real aunque el mes haya quedado marcado atípico. El bug previo
    # comparaba y_limpio[-3:] vs y_limpio[-6:-3], que son posiciones de un
    # arreglo YA FILTRADO: si se excluyeron atípicos en medio del histórico,
    # esas posiciones dejan de corresponder a meses contiguos y el % de
    # crecimiento sale inflado o directamente sin sentido.
    crecimiento_pct = None
    base_previa_m2 = None
    if n >= 6:
        recientes = float(y[-3:].mean())
        base_previa_m2 = float(y[-6:-3].mean())
        if base_previa_m2 > 1e-9:
            crecimiento_pct = float((recientes - base_previa_m2) / base_previa_m2 * 100)

    # RN-16 (T22): además de tendencia creciente + crecimiento mínimo, se
    # exige un piso de demanda previa (GANADOR_BASE_MINIMA_M2) para entrar al
    # ranking de ganadores -- sin esto, una serie que pasó de vender 0.5 a 5
    # m2/mes "gana" con +900% sin ser una señal comercial real (efecto base
    # pequeña).
    producto_ganador = bool(
        tendencia["clasificacion"] == "creciente"
        and crecimiento_pct is not None
        and crecimiento_pct >= GANADOR_CRECIMIENTO_MIN * 100
        and base_previa_m2 is not None
        and base_previa_m2 >= GANADOR_BASE_MINIMA_M2
    )

    # Forecast hacia adelante, sobre el modelo ajustado con TODA la historia limpia.
    ultimo_mes = meses[-1]
    forecast = []
    for h in range(1, HORIZONTE_FORECAST + 1):
        mes_futuro = _siguiente_mes(ultimo_mes, h)
        t_futuro = float(n - 1 + h)  # continúa el índice temporal original (con huecos de atípicos incluidos)
        valor = tendencia["intercepto"] + tendencia["pendiente"] * t_futuro
        valor += estacionalidad.get(_mes_calendario(mes_futuro), 0.0)
        forecast.append({"anio_mes": mes_futuro, "valor_estimado_m2": round(max(valor, 0.0), 2)})

    # Backtest: reajusta con todo MENOS el último trimestre y compara contra lo real.
    backtest = None
    if n_limpio >= MIN_PUNTOS_FORECAST + MESES_BACKTEST:
        corte = meses[-MESES_BACKTEST]
        idx_holdout = [i for i in range(n) if meses[i] >= corte]
        idx_train_limpio = [i for i in range(n) if limpio[i] and meses[i] < corte]
        if len(idx_train_limpio) >= MIN_PUNTOS_FORECAST and idx_holdout:
            t_train = t[idx_train_limpio]
            y_train = y[idx_train_limpio]
            tend_bt = ajustar_tendencia(t_train, y_train)
            resid_train = y_train - (tend_bt["intercepto"] + tend_bt["pendiente"] * t_train)
            cal_train = [_mes_calendario(meses[i]) for i in idx_train_limpio]
            estac_bt = calc_estacionalidad(cal_train, resid_train)

            # Solo se evalúa contra meses reales NO atípicos del holdout (un
            # pico atípico no es "error de forecast", es una anomalía marcada).
            idx_eval = [i for i in idx_holdout if not atipicos[i]]
            if idx_eval:
                pred = np.array([
                    tend_bt["intercepto"] + tend_bt["pendiente"] * t[i] + estac_bt.get(_mes_calendario(meses[i]), 0.0)
                    for i in idx_eval
                ])
                pred = np.clip(pred, 0.0, None)
                real = y[idx_eval]
                mape = calc_mape(real, pred)
                backtest = {
                    "meses_evaluados": [meses[i] for i in idx_eval],
                    "meses_excluidos_atipicos": [meses[i] for i in idx_holdout if atipicos[i]],
                    "mape_pct": round(mape, 2) if mape is not None else None,
                    "detalle": [
                        {"anio_mes": meses[i], "real_m2": round(float(y[i]), 2), "prediccion_m2": round(float(p), 2)}
                        for i, p in zip(idx_eval, pred)
                    ],
                }

    return {
        "suficiente_historia": True,
        "meses_disponibles": n,
        "meses_usados": n_limpio,
        "picos_excluidos": int(atipicos.sum()),
        "serie_historica": serie_historica,
        "tendencia": {
            "pendiente_m2_mes": round(tendencia["pendiente"], 3),
            "t_stat": round(tendencia["t_stat"], 2),
            "clasificacion": tendencia["clasificacion"],
        },
        "estacionalidad": {str(k): round(v, 2) for k, v in sorted(estacionalidad.items())},
        "forecast": forecast,
        "backtest": backtest,
        "producto_ganador": producto_ganador,
        "crecimiento_pct": round(crecimiento_pct, 2) if crecimiento_pct is not None else None,
        "base_previa_m2": round(base_previa_m2, 2) if base_previa_m2 is not None else None,
    }


# ---------------------------------------------------------------------------
# Acceso a datos
# ---------------------------------------------------------------------------

def _resolver_canal(db: sqlite3.Connection, plant_o_canal: str) -> str:
    """Acepta un canal literal o un código de plant; devuelve el canal."""
    if plant_o_canal in CANALES_VALIDOS:
        return plant_o_canal
    fila = db.execute("SELECT canal FROM sucursales WHERE plant = ?", (plant_o_canal,)).fetchone()
    if not fila:
        raise HTTPException(
            status_code=404,
            detail=f"'{plant_o_canal}' no es un canal válido ({sorted(CANALES_VALIDOS)}) ni un plant existente en sucursales.",
        )
    return fila["canal"]


def _validar_material(db: sqlite3.Connection, material_id: str) -> None:
    fila = db.execute("SELECT 1 FROM materiales WHERE material_id = ?", (material_id,)).fetchone()
    if not fila:
        raise HTTPException(status_code=404, detail=f"material_id '{material_id}' no existe.")


def _serie_material_canal(db: sqlite3.Connection, material_id: str, canal: str) -> tuple[list[str], list[float]]:
    filas = db.execute(
        """SELECT anio_mes, SUM(cantidad_m2) AS valor
           FROM ventas_mensuales
           WHERE material_id = ? AND canal = ?
           GROUP BY anio_mes
           ORDER BY anio_mes ASC""",
        (material_id, canal),
    ).fetchall()
    return [f["anio_mes"] for f in filas], [float(f["valor"]) for f in filas]


def _todas_las_series(db: sqlite3.Connection, canal_filtro: Optional[str]) -> dict[tuple[str, str], tuple[list[str], list[float]]]:
    """Una sola query agregada para TODO el universo material×canal (excluye
    Outlet/Remates por RN-04). Evita N+1 queries contra 1,800 SKU x 3 canales."""
    where = "canal NOT IN ('Outlet', 'Remates')"
    params: list = []
    if canal_filtro:
        where += " AND canal = ?"
        params.append(canal_filtro)
    filas = db.execute(
        f"""SELECT material_id, canal, anio_mes, SUM(cantidad_m2) AS valor
            FROM ventas_mensuales
            WHERE {where}
            GROUP BY material_id, canal, anio_mes
            ORDER BY material_id, canal, anio_mes ASC""",
        params,
    ).fetchall()
    series: dict[tuple[str, str], tuple[list[str], list[float]]] = defaultdict(lambda: ([], []))
    for f in filas:
        key = (f["material_id"], f["canal"])
        meses, valores = series[key]
        meses.append(f["anio_mes"])
        valores.append(float(f["valor"]))
    return series


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/tendencias/ganadores")
def tendencias_ganadores(
    canal: Optional[str] = Query(None, description="Filtra a un solo canal (Menudeo/Mayoreo/eCommerce)"),
    limit: int = Query(50, ge=1, le=500),
    db: sqlite3.Connection = Depends(get_db),
):
    """Productos ganadores (RN-16): tendencia creciente y estadísticamente
    significativa + crecimiento reciente >= 10%. Evalúa TODO el universo
    material×canal (excluyendo Outlet/Remates) y cachea 10 min — recorrer
    miles de series en cada request no se justifica para una lista que no
    cambia mes a mes."""
    if canal is not None and canal not in (CANALES_VALIDOS - CANALES_EXCLUIDOS):
        raise HTTPException(status_code=400, detail=f"canal debe ser uno de {sorted(CANALES_VALIDOS - CANALES_EXCLUIDOS)}")

    cache_key = canal or "__todos__"
    ahora = time.time()
    cacheado = _CACHE_GANADORES.get(cache_key)
    if cacheado and (ahora - cacheado[0]) < CACHE_TTL_SEGUNDOS:
        payload = cacheado[1]
    else:
        series = _todas_las_series(db, canal)
        descripciones = {
            f["material_id"]: {"descripcion": f["descripcion"], "familia": f["familia"]}
            for f in db.execute("SELECT material_id, descripcion, familia FROM materiales").fetchall()
        }
        evaluados = 0
        ganadores = []
        for (material_id, canal_serie), (meses, valores) in series.items():
            evaluados += 1
            resultado = construir_forecast_serie(meses, valores)
            if resultado["producto_ganador"]:
                info = descripciones.get(material_id, {})
                ganadores.append({
                    "material_id": material_id,
                    "descripcion": info.get("descripcion"),
                    "familia": info.get("familia"),
                    "canal": canal_serie,
                    "crecimiento_pct": resultado["crecimiento_pct"],
                    "base_previa_m2": resultado["base_previa_m2"],
                    "tendencia": resultado["tendencia"],
                    "meses_usados": resultado["meses_usados"],
                })
        ganadores.sort(key=lambda g: g["crecimiento_pct"] or 0.0, reverse=True)
        payload = {
            "total_series_evaluadas": evaluados,
            "total_ganadores": len(ganadores),
            "generado_hace_segundos": 0,
            "canal_filtro": canal,
            "ganadores": ganadores,
        }
        _CACHE_GANADORES[cache_key] = (ahora, payload)

    edad = round(ahora - _CACHE_GANADORES[cache_key][0], 1)
    respuesta = {**payload, "generado_hace_segundos": edad, "cache_ttl_segundos": CACHE_TTL_SEGUNDOS}
    respuesta["ganadores"] = respuesta["ganadores"][:limit]
    respuesta["mostrados"] = len(respuesta["ganadores"])
    return respuesta


@router.get("/precision")
def precision_forecast(
    material_id: Optional[str] = Query(None),
    plant_o_canal: Optional[str] = Query(None),
    sample_size: int = Query(100, ge=1, le=1000, description="Tamaño de muestra para el resumen global"),
    db: sqlite3.Connection = Depends(get_db),
):
    """MAPE de backtest del último trimestre. Con material_id+plant_o_canal
    devuelve el detalle puntual; sin ellos, un resumen global sobre una
    MUESTRA explícita (nunca trunca en silencio: siempre informa cuántas
    series se evaluaron sobre cuántas totales)."""
    if material_id and plant_o_canal:
        _validar_material(db, material_id)
        canal = _resolver_canal(db, plant_o_canal)
        if canal in CANALES_EXCLUIDOS:
            raise HTTPException(status_code=400, detail=f"Canal '{canal}' excluido del forecast por RN-04.")
        meses, valores = _serie_material_canal(db, material_id, canal)
        if not meses:
            raise HTTPException(status_code=404, detail=f"Sin historial para material '{material_id}' en canal '{canal}'.")
        resultado = construir_forecast_serie(meses, valores)
        return {
            "material_id": material_id,
            "canal": canal,
            "mape_pct": resultado["backtest"]["mape_pct"] if resultado["backtest"] else None,
            "backtest": resultado["backtest"],
            "suficiente_historia": resultado["suficiente_historia"],
        }

    if bool(material_id) != bool(plant_o_canal):
        raise HTTPException(status_code=400, detail="Para detalle puntual se requieren AMBOS material_id y plant_o_canal.")

    # Resumen global sobre muestra determinística (cada K-ésimo material×canal,
    # así el resultado es reproducible entre requests con el mismo sample_size).
    series = _todas_las_series(db, None)
    todas = list(series.items())
    total_universo = len(todas)
    paso = max(1, total_universo // sample_size) if total_universo > sample_size else 1
    muestra = todas[::paso][:sample_size]

    mapes: list[float] = []
    sin_suficiente_historia = 0
    for (_material_id, _canal), (meses, valores) in muestra:
        resultado = construir_forecast_serie(meses, valores)
        if not resultado["suficiente_historia"] or not resultado["backtest"] or resultado["backtest"]["mape_pct"] is None:
            sin_suficiente_historia += 1
            continue
        mapes.append(resultado["backtest"]["mape_pct"])

    if mapes:
        arr = np.array(mapes)
        resumen = {
            "mape_promedio_pct": round(float(arr.mean()), 2),
            "mape_mediana_pct": round(float(np.median(arr)), 2),
            "pct_series_con_mape_bajo_15": round(float(np.mean(arr < 15) * 100), 1),
            "pct_series_con_mape_bajo_30": round(float(np.mean(arr < 30) * 100), 1),
        }
    else:
        resumen = None

    return {
        "muestra_evaluada": len(muestra),
        "total_universo_material_canal": total_universo,
        "series_sin_suficiente_historia": sin_suficiente_historia,
        "series_con_mape": len(mapes),
        "resumen": resumen,
        "nota": "Resumen sobre una muestra determinística (no es silencioso: 'muestra_evaluada' de 'total_universo_material_canal'). Usa material_id+plant_o_canal para el detalle de una serie puntual.",
    }


# NOTA: esta ruta catch-all va DELIBERADAMENTE al final del archivo (después
# de /tendencias/ganadores y /precision). FastAPI matchea rutas en el orden
# de registro; si `/{material_id}/{plant_o_canal}` se registrara antes,
# capturaría peticiones a /tendencias/ganadores (material_id="tendencias",
# plant_o_canal="ganadores") y /precision con un 404 falso "material no
# existe" en vez de llegar al handler correcto. Bug real detectado en smoke
# test manual antes de integrar — no reordenar sin volver a probar ambos
# endpoints literales.
@router.get("/{material_id}/{plant_o_canal}")
def forecast_material_canal(material_id: str, plant_o_canal: str, db: sqlite3.Connection = Depends(get_db)):
    """Forecast + tendencia + backtest de un material. `plant_o_canal` puede
    ser un canal (Menudeo/Mayoreo/eCommerce) o un plant (se resuelve a su
    canal). El cálculo SIEMPRE se agrega a nivel canal (RN: forecast por
    canal independiente, no por sucursal individual)."""
    _validar_material(db, material_id)
    canal = _resolver_canal(db, plant_o_canal)
    if canal in CANALES_EXCLUIDOS:
        raise HTTPException(
            status_code=400,
            detail=f"Canal '{canal}' excluido del forecast por RN-04 (Outlet/Remates son liquidación de excedente, no demanda regular).",
        )

    meses, valores = _serie_material_canal(db, material_id, canal)
    if not meses:
        raise HTTPException(status_code=404, detail=f"Sin historial de ventas para material '{material_id}' en canal '{canal}'.")

    resultado = construir_forecast_serie(meses, valores)
    return {
        "material_id": material_id,
        "canal": canal,
        "plant_solicitado": plant_o_canal if plant_o_canal != canal else None,
        "nivel_agregacion": "canal (todas las sucursales de ese canal)",
        **resultado,
    }
