"""Tests para T22 (waykee 290119): fix del Motor C2 (forecast/tendencias) en
engines/forecast.py -- porcentajes de crecimiento absurdos por 3 bugs
encadenados:

  1. `detectar_atipicos` corría Modified Z-Score sobre los VALORES CRUDOS.
     En series con cambio de RÉGIMEN (p.ej. una plaza que vendía 2-17 m2/mes
     y de un mes a otro empieza a vender 2,500-4,500 m2/mes) la mediana
     histórica queda dominada por el régimen viejo y los meses NUEVOS -- el
     nivel real actual -- se marcaban "atípicos". Fix: Modified Z-Score
     sobre los RESIDUALES de un ajuste Theil-Sen (robusto) + regla de
     persistencia (`_descartar_rachas_sostenidas`): un pico atípico (RN-14)
     es una anomalía puntual y transitoria, no un cambio de nivel sostenido.

  2. `crecimiento_pct` comparaba `y_limpio[-3:]` vs `y_limpio[-6:-3]` --
     posiciones de un arreglo YA FILTRADO de atípicos. Si se excluyó algún
     mes dentro de la ventana de comparación, esas posiciones dejan de
     corresponder a meses de calendario contiguos y el % sale inflado o sin
     sentido. Fix: comparar directamente `y[-3:]` vs `y[-6:-3]` (serie
     ORIGINAL, sin filtrar) -- siempre 6 meses de calendario contiguos, con
     su valor real aunque el mes haya quedado marcado atípico.

  3. El ranking de "ganadores" (RN-16) no exigía una base previa mínima:
     una serie que pasaba de vender 0.5 a 5 m2/mes "ganaba" con +900% sin
     ser una señal comercial real (puro efecto de base pequeña). Fix:
     `GANADOR_BASE_MINIMA_M2` -- exige `base_previa_m2 >= 10.0` además de
     tendencia creciente + crecimiento >= 10%.

Nota sobre validación con datos reales: el ticket pide usar los casos reales
G06-59-1-142/Menudeo y G06-33-1-52/Menudeo del dataset `data-real-car-v2`
(branch `data/real-car`) como regresión. Ese `comprasai.db` (198MB) está
gitignored -- no se sube al repo por tamaño (ver
`data/README_real_car.md`) -- y no estaba presente en este sandbox al
momento del fix (solo quedan `extract_real_car.py`/`build_dataset.py`, no el
.db generado). Los tests `CasosRealesReproducidosTests` de abajo son
reproducciones SINTÉTICAS del patrón exacto descrito en el reporte del bug
(mismo mecanismo, mismos rangos de valores) -- no los números reales
material por material. Si se dispone del `.db` real, se recomienda correr
además `forecast_material_canal` contra esos dos material_id/canal para
confirmar el mismo comportamiento sobre el dato real.

Ejecutar (sin dependencias extra más allá de fastapi/numpy del venv del
proyecto):
    cd backend && python3 -m unittest tests.test_forecast_tendencias -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.routers.engines.forecast import (  # noqa: E402
    GANADOR_BASE_MINIMA_M2,
    construir_forecast_serie,
    detectar_atipicos,
)


def _meses(n: int, inicio: str = "2024-01") -> list[str]:
    anio0, mes0 = int(inicio[:4]), int(inicio[5:7])
    out = []
    for i in range(n):
        total = anio0 * 12 + (mes0 - 1) + i
        out.append(f"{total // 12:04d}-{(total % 12) + 1:02d}")
    return out


class DetectarAtipicosCambioRegimenTests(unittest.TestCase):
    """Parte 1 del fix: residuales de tendencia robusta + rescate de rachas."""

    def test_regimen_sostenido_no_se_marca_atipico(self):
        # 18 meses "bajos" (2-17 m2/mes) + 6 meses "altos" (2,500-4,500),
        # el patrón exacto descrito para G06-59-1-142: cambio de régimen
        # sostenido, no un pico transitorio.
        bajos = [2, 5, 8, 3, 17, 6, 4, 9, 12, 7, 3, 15, 2, 6, 10, 4, 8, 5]
        altos = [2600, 3100, 2900, 4400, 3700, 4100]
        y = np.array(bajos + altos, dtype=float)
        t = np.arange(len(y), dtype=float)
        atipicos = detectar_atipicos(t, y)
        self.assertFalse(atipicos[-6:].any(), "los 6 meses del nuevo régimen no deben marcarse atípicos")

    def test_pico_aislado_si_se_marca(self):
        # Serie estable con UN mes de pico puntual (p.ej. una venta grande
        # de una sola vez) -- esto SÍ debe seguir detectándose (RN-14).
        y = np.array([100, 105, 98, 102, 99, 101, 600, 103, 97, 100, 104, 99, 101, 98, 103, 100, 102, 99], dtype=float)
        t = np.arange(len(y), dtype=float)
        atipicos = detectar_atipicos(t, y)
        self.assertEqual(int(atipicos.sum()), 1)
        self.assertTrue(atipicos[6])

    def test_racha_de_exactamente_dos_tambien_se_rescata(self):
        # La regla de persistencia rescata rachas de 2+ (no solo 6+): dos
        # meses consecutivos altos ya no cuentan como "pico puntual".
        y = np.array([10, 12, 9, 11, 10, 9, 500, 520, 11, 10, 9, 12], dtype=float)
        t = np.arange(len(y), dtype=float)
        atipicos = detectar_atipicos(t, y)
        self.assertFalse(atipicos[6])
        self.assertFalse(atipicos[7])


class CrecimientoPctMesesCalendarioTests(unittest.TestCase):
    """Parte 2 del fix: comparación sobre la serie ORIGINAL (meses de
    calendario reales), no sobre posiciones de un arreglo ya filtrado."""

    def test_usa_valores_reales_del_mes_aunque_sea_atipico(self):
        # Pico aislado DENTRO de la ventana de comparación (grupo "previos"
        # = posiciones -6:-3). Con el bug viejo, y_limpio excluía ese mes y
        # la ventana de comparación se desalineaba (dejaba de ser 6 meses
        # contiguos). Con el fix, el % se calcula sobre `y` cruda: siempre
        # los últimos 3 vs los 3 anteriores, meses de calendario reales.
        meses = _meses(10)
        valores = [80, 78, 82, 79, 45, 3000, 35, 30, 28, 26]
        r = construir_forecast_serie(meses, valores)
        recientes_esperado = np.mean(valores[-3:])  # [30, 28, 26]
        previos_esperado = np.mean(valores[-6:-3])  # [45, 3000, 35]
        esperado_pct = round(float((recientes_esperado - previos_esperado) / previos_esperado * 100), 2)
        self.assertAlmostEqual(r["crecimiento_pct"], esperado_pct)
        self.assertAlmostEqual(r["base_previa_m2"], round(float(previos_esperado), 2))

    def test_serie_insuficiente_no_calcula_crecimiento(self):
        # Con <6 meses de historia (total, no solo "limpios") no hay
        # ventana de 3-vs-3 posible.
        r = construir_forecast_serie(_meses(5), [10, 11, 9, 10, 12])
        self.assertIsNone(r["crecimiento_pct"])
        self.assertIsNone(r["base_previa_m2"])


class GanadorBaseMinimaTests(unittest.TestCase):
    """Parte 3 del fix: piso de demanda previa para el ranking RN-16."""

    def test_base_pequena_no_es_ganador_pese_a_tendencia_y_crecimiento(self):
        meses = _meses(12)
        valores = [0.5, 0.6, 0.4, 0.5, 0.6, 0.5, 1, 2, 3, 4, 5, 6]
        r = construir_forecast_serie(meses, valores)
        self.assertEqual(r["tendencia"]["clasificacion"], "creciente")
        self.assertGreater(r["crecimiento_pct"], 10.0)
        self.assertLess(r["base_previa_m2"], GANADOR_BASE_MINIMA_M2)
        self.assertFalse(r["producto_ganador"])

    def test_mismo_patron_escalado_arriba_del_piso_si_es_ganador(self):
        meses = _meses(12)
        valores = [v * 100 for v in (0.5, 0.6, 0.4, 0.5, 0.6, 0.5, 1, 2, 3, 4, 5, 6)]
        r = construir_forecast_serie(meses, valores)
        self.assertEqual(r["tendencia"]["clasificacion"], "creciente")
        self.assertGreaterEqual(r["base_previa_m2"], GANADOR_BASE_MINIMA_M2)
        self.assertTrue(r["producto_ganador"])


class CasosRealesReproducidosTests(unittest.TestCase):
    """Reproducciones sintéticas de los 2 casos reales del reporte del bug
    (ver nota del módulo: el .db real de data/real-car no está disponible
    en este sandbox). Mismo mecanismo y mismos órdenes de magnitud que
    G06-59-1-142 y G06-33-1-52 (Menudeo)."""

    def test_g06_59_1_142_like_cambio_de_regimen_da_crecimiento_razonable(self):
        # Vendía 2-17 m2/mes y desde hace 6 meses vende 2,500-4,500 m2/mes.
        # Antes del fix: comparación sobre posiciones filtradas -> +9,236%
        # (con solo un valor alto sobreviviendo el filtro atípicos y el
        # resto del "reciente" rellenado con meses viejos de régimen bajo).
        # Después del fix: régimen sostenido no se excluye, y el % sale de
        # comparar 3 meses reales contra los 3 anteriores (ambos ya en el
        # régimen nuevo) -> un crecimiento moderado y creíble.
        bajos = [2, 5, 8, 3, 17, 6, 4, 9, 12, 7, 3, 15, 2, 6, 10, 4, 8, 5]
        altos = [2600, 3100, 2900, 4400, 3700, 4100]
        meses = _meses(len(bajos) + len(altos))
        r = construir_forecast_serie(meses, bajos + altos)
        self.assertEqual(r["picos_excluidos"], 0)
        self.assertEqual(r["tendencia"]["clasificacion"], "creciente")
        self.assertTrue(r["producto_ganador"])
        # Nunca miles de % -- el bug reportado (+9,236%) queda descartado
        # por construcción: ambas ventanas de 3 meses viven en el régimen
        # nuevo, así que el % real es de decenas, no de miles.
        self.assertLess(abs(r["crecimiento_pct"]), 200.0)

    def test_g06_33_1_52_like_decrece_pese_a_pico_historico_no_es_ganador(self):
        # El "#1 del ranking" real (+14,887%) en realidad DECRECE en sus
        # últimos meses; el bug era enteramente de alineación posicional
        # (parte 2 del fix), no de la serie en sí -- una compra puntual
        # grande unos meses atrás no debe distorsionar el % de HOY.
        valores = [80, 78, 82, 79, 81, 77, 83, 80, 3200, 60, 55, 50, 46, 42, 40, 37, 35, 33, 31, 29, 28, 26, 25, 24]
        meses = _meses(len(valores))
        r = construir_forecast_serie(meses, valores)
        self.assertEqual(r["tendencia"]["clasificacion"], "decreciente")
        self.assertLess(r["crecimiento_pct"], 0.0)
        self.assertFalse(r["producto_ganador"])


if __name__ == "__main__":
    unittest.main()
