"""Tests para T25 (waykee 290123): torneo de pronósticos -- 5 algoritmos +
protocolo de backtest rolling-origin (backend/analysis/backtest_forecast.py).

Cubre las funciones puras del módulo (algoritmos, generación de orígenes,
agregación WAPE/sesgo, censura por desabasto, simulación de servicio,
estacionalidad por familia). NO ejercita `ejecutar_torneo`/`cargar_series`
contra el dataset real (data-real-car-v2, ~198MB en /private/tmp, no
versionado -- ver docstring del módulo) porque eso corresponde al run real
(Task #3), no a un test unitario reproducible en cualquier sandbox.

Ejecutar:
    cd backend && python3 -m unittest tests.test_backtest_forecast -v
"""

import sqlite3
import sys
import unittest
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from analysis.backtest_forecast import (  # noqa: E402
    agregar_wape_sesgo,
    analizar_estacionalidad_familia,
    backtest_serie,
    detectar_meses_desabasto,
    forecast_croston_sba,
    forecast_holt_winters,
    forecast_media_movil,
    forecast_seasonal_naive,
    forecast_tendencia_estacional,
    generar_origenes,
    meses_censurados_canal,
    simular_servicio_serie,
)


def _meses(n: int, inicio: str = "2023-01") -> list[str]:
    anio0, mes0 = int(inicio[:4]), int(inicio[5:7])
    out = []
    for i in range(n):
        total = anio0 * 12 + (mes0 - 1) + i
        out.append(f"{total // 12:04d}-{(total % 12) + 1:02d}")
    return out


# ---------------------------------------------------------------------------
# A1 · Seasonal-naive
# ---------------------------------------------------------------------------

class SeasonalNaiveTests(unittest.TestCase):
    def test_usa_mismo_mes_del_anio_anterior(self):
        # 24 meses: enero..diciembre repetido dos veces, con el segundo año
        # +10 respecto al primero. Pronóstico para los 3 meses tras el mes 24
        # (=ene/feb/mar del "año 3") debe tomar ene/feb/mar del año 2 (últimos
        # 12), es decir el segundo bloque.
        anio1 = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120]
        anio2 = [v + 10 for v in anio1]
        meses = _meses(24)
        y = np.array(anio1 + anio2, dtype=float)
        pred = forecast_seasonal_naive(meses, y, horizonte=3)
        self.assertEqual(pred, [anio2[0], anio2[1], anio2[2]])

    def test_fallback_promedio_3m_sin_historia_de_un_anio(self):
        meses = _meses(5)
        y = np.array([10.0, 12.0, 8.0, 11.0, 9.0])
        pred = forecast_seasonal_naive(meses, y, horizonte=2)
        fallback = float(np.mean(y[-3:]))
        self.assertEqual(pred, [fallback, fallback])

    def test_none_con_historia_insuficiente(self):
        self.assertIsNone(forecast_seasonal_naive(_meses(2), np.array([1.0, 2.0])))


# ---------------------------------------------------------------------------
# A2 · Media móvil 3 meses
# ---------------------------------------------------------------------------

class MediaMovilTests(unittest.TestCase):
    def test_promedio_plano_ultimos_3_meses(self):
        meses = _meses(6)
        y = np.array([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
        pred = forecast_media_movil(meses, y, horizonte=3)
        self.assertEqual(pred, [50.0, 50.0, 50.0])  # mean(40,50,60), plano en los 3 horizontes

    def test_serie_corta_usa_lo_disponible(self):
        # Con menos meses que la ventana solicitada (pero >= MIN_PUNTOS_ABSOLUTO),
        # promedia lo que hay en vez de fallar.
        meses = _meses(3)
        y = np.array([10.0, 20.0, 30.0])
        pred = forecast_media_movil(meses, y, horizonte=1, ventana=5)
        self.assertEqual(pred, [20.0])


# ---------------------------------------------------------------------------
# A3 · Tendencia + estacionalidad (wrapper de motor C2 real)
# ---------------------------------------------------------------------------

class TendenciaEstacionalTests(unittest.TestCase):
    def test_reutiliza_construir_forecast_serie_del_motor_c2(self):
        # Serie con tendencia creciente clara y suficiente historia.
        meses = _meses(12)
        y = np.array([float(10 + 5 * i) for i in range(12)])
        pred = forecast_tendencia_estacional(meses, y, horizonte=3)
        self.assertIsNotNone(pred)
        self.assertEqual(len(pred), 3)
        # Debe seguir proyectando hacia arriba (tendencia creciente).
        self.assertGreater(pred[-1], y[-1])

    def test_none_con_historia_insuficiente(self):
        meses = _meses(4)
        y = np.array([1.0, 2.0, 3.0, 4.0])
        self.assertIsNone(forecast_tendencia_estacional(meses, y, horizonte=3))

    def test_none_si_horizonte_excede_el_del_motor_c2(self):
        meses = _meses(12)
        y = np.array([float(10 + i) for i in range(12)])
        self.assertIsNone(forecast_tendencia_estacional(meses, y, horizonte=4))


# ---------------------------------------------------------------------------
# A4 · Holt-Winters
# ---------------------------------------------------------------------------

class HoltWintersTests(unittest.TestCase):
    def test_captura_nivel_de_serie_estacional_de_2_anios(self):
        # Patrón estacional claro: pico en diciembre (mes 12), valle en
        # febrero (mes 2), repetido 2 años exactos, nivel constante.
        base = [50, 30, 40, 45, 48, 52, 55, 53, 50, 48, 60, 90]
        meses = _meses(24)
        y = np.array(base * 2, dtype=float)
        pred = forecast_holt_winters(meses, y, horizonte=3)
        self.assertIsNotNone(pred)
        self.assertEqual(len(pred), 3)
        # Próximos 3 meses tras el mes 24 (diciembre) son ene/feb/mar del
        # año 3: el pronóstico de febrero (valle, índice 1 del bloque) debe
        # quedar claramente por debajo del de enero si la estacionalidad se
        # está capturando razonablemente (no es una comparación exacta con
        # HW, solo un smoke test del patrón).
        self.assertLess(pred[1], pred[0] + 20)

    def test_degrada_a_holt_lineal_sin_estacionalidad_con_poca_historia(self):
        # <12 meses -> debe seguir devolviendo forecast (Holt lineal), no None.
        meses = _meses(6)
        y = np.array([10.0, 12.0, 14.0, 16.0, 18.0, 20.0])
        pred = forecast_holt_winters(meses, y, horizonte=3)
        self.assertIsNotNone(pred)
        self.assertEqual(len(pred), 3)

    def test_nunca_devuelve_negativos(self):
        meses = _meses(6)
        y = np.array([5.0, 4.0, 3.0, 2.0, 1.0, 0.5])
        pred = forecast_holt_winters(meses, y, horizonte=3)
        self.assertTrue(all(v >= 0 for v in pred))

    def test_none_con_historia_insuficiente(self):
        self.assertIsNone(forecast_holt_winters(_meses(2), np.array([1.0, 2.0])))


# ---------------------------------------------------------------------------
# A5 · Croston / SBA
# ---------------------------------------------------------------------------

class CrostonSbaTests(unittest.TestCase):
    def test_demanda_intermitente_devuelve_tasa_positiva_plana(self):
        # Muchos ceros, demanda esporádica -- caso típico de "muchos pares
        # material-sucursal tienen meses en cero" del ticket.
        meses = _meses(10)
        y = np.array([0, 0, 20, 0, 0, 0, 15, 0, 0, 25], dtype=float)
        pred = forecast_croston_sba(meses, y, horizonte=3)
        self.assertIsNotNone(pred)
        self.assertEqual(len(pred), 3)
        self.assertEqual(pred[0], pred[1])
        self.assertEqual(pred[1], pred[2])  # plano, sin tendencia/estacionalidad
        self.assertGreater(pred[0], 0.0)

    def test_serie_toda_en_cero_da_cero(self):
        meses = _meses(6)
        y = np.zeros(6)
        pred = forecast_croston_sba(meses, y, horizonte=2)
        self.assertEqual(pred, [0.0, 0.0])

    def test_none_con_historia_insuficiente(self):
        self.assertIsNone(forecast_croston_sba(_meses(2), np.array([0.0, 5.0])))


# ---------------------------------------------------------------------------
# Rolling-origin: generación de orígenes y backtest de una serie
# ---------------------------------------------------------------------------

class GenerarOrigenesTests(unittest.TestCase):
    def test_serie_larga_devuelve_n_origenes_solicitados(self):
        # 30 meses, horizonte 3 -> max_origen = 26 (0-based). Con n_origenes=12
        # debe devolver exactamente 12 índices, los últimos válidos.
        origenes = generar_origenes(n_meses=30, horizonte=3, n_origenes=12)
        self.assertEqual(len(origenes), 12)
        self.assertEqual(origenes[-1], 30 - 1 - 3)  # 26
        self.assertEqual(origenes[0], 26 - 12 + 1)  # 15

    def test_serie_corta_devuelve_todos_los_que_caben_sin_truncar_en_silencio(self):
        # 6 meses, horizonte 3 -> max_origen=2 -> origenes [0,1,2], solo 3
        # aunque se pidan 12 (nunca inventa datos ni lanza error).
        origenes = generar_origenes(n_meses=6, horizonte=3, n_origenes=12)
        self.assertEqual(origenes, [0, 1, 2])

    def test_serie_insuficiente_para_ningun_origen(self):
        # 3 meses, horizonte 3 -> max_origen = 3-1-3 = -1 -> sin orígenes.
        self.assertEqual(generar_origenes(n_meses=3, horizonte=3, n_origenes=12), [])


class BacktestSerieTests(unittest.TestCase):
    def test_genera_un_registro_por_algoritmo_x_origen_x_horizonte(self):
        meses = _meses(20)
        valores = [float(10 + i) for i in range(20)]
        registros = backtest_serie(meses, valores, horizonte=3, n_origenes=5)
        origenes_esperados = generar_origenes(20, 3, 5)
        # 5 algoritmos x 5 orígenes x 3 horizontes = 75 registros (todos con
        # horizonte completo disponible dentro de la serie).
        self.assertEqual(len(registros), 5 * len(origenes_esperados) * 3)
        for r in registros:
            self.assertIn(r["algoritmo"], {
                "A1_seasonal_naive", "A2_media_movil_3m", "A3_tendencia_estacional",
                "A4_holt_winters", "A5_croston_sba",
            })
            self.assertFalse(r["censurado"])

    def test_marca_censurado_segun_meses_censurados(self):
        meses = _meses(10)
        valores = [float(10 + i) for i in range(10)]
        mes_censurado = meses[8]  # cae dentro del rango evaluado
        registros = backtest_serie(meses, valores, horizonte=1, n_origenes=5, meses_censurados={mes_censurado})
        censurados = [r for r in registros if r["mes_evaluado"] == mes_censurado]
        self.assertTrue(censurados)
        self.assertTrue(all(r["censurado"] for r in censurados))

    def test_sin_prediccion_cuando_algoritmo_no_puede_pronosticar(self):
        # Origen mes_origen="2023-01-03" -> train de 3 meses (índice 2, el
        # mínimo para que A2 pueda pronosticar per MIN_PUNTOS_ABSOLUTO=3),
        # pero insuficiente para A3 (motor C2, exige MIN_PUNTOS_FORECAST=6):
        # A3 debe quedar sin predicción en ese origen, A2 sí debe poder.
        meses = _meses(10)
        valores = [float(i) for i in range(10)]
        registros = backtest_serie(meses, valores, horizonte=1, n_origenes=10)
        origen_temprano = meses[2]  # train = meses[:3], longitud 3
        a3_ese_origen = [r for r in registros if r["algoritmo"] == "A3_tendencia_estacional" and r["mes_origen"] == origen_temprano]
        a2_ese_origen = [r for r in registros if r["algoritmo"] == "A2_media_movil_3m" and r["mes_origen"] == origen_temprano]
        self.assertTrue(a3_ese_origen and a3_ese_origen[0]["sin_prediccion"])
        self.assertTrue(a2_ese_origen and not a2_ese_origen[0]["sin_prediccion"])


# ---------------------------------------------------------------------------
# Agregación WAPE / sesgo
# ---------------------------------------------------------------------------

class AgregarWapeSesgoTests(unittest.TestCase):
    def _reg(self, algoritmo, real, prediccion, censurado=False, sin_prediccion=False, horizonte=1):
        return {
            "algoritmo": algoritmo, "horizonte": horizonte, "real": real,
            "prediccion": prediccion, "censurado": censurado, "sin_prediccion": sin_prediccion,
        }

    def test_wape_y_sesgo_calculados_correctamente(self):
        # 2 observaciones del mismo algoritmo/horizonte: real=[100,200],
        # pred=[110,180] -> err=[10,-20], |err|=30, |real|=300.
        registros = [
            self._reg("A2_media_movil_3m", 100.0, 110.0),
            self._reg("A2_media_movil_3m", 200.0, 180.0),
        ]
        tabla, resumen = agregar_wape_sesgo(registros, ["algoritmo", "horizonte"])
        self.assertEqual(len(tabla), 1)
        fila = tabla[0]
        self.assertAlmostEqual(fila["wape_pct"], 30 / 300 * 100)
        self.assertAlmostEqual(fila["sesgo_pct"], -10 / 300 * 100, places=2)
        self.assertEqual(fila["n_observaciones"], 2)
        self.assertEqual(resumen["usados"], 2)
        self.assertEqual(resumen["excluidos_censura"], 0)
        self.assertEqual(resumen["excluidos_sin_prediccion"], 0)

    def test_excluye_censurados_y_sin_prediccion_y_lo_reporta(self):
        registros = [
            self._reg("A2_media_movil_3m", 100.0, 100.0),
            self._reg("A2_media_movil_3m", 100.0, 999.0, censurado=True),
            self._reg("A2_media_movil_3m", 100.0, None, sin_prediccion=True),
        ]
        tabla, resumen = agregar_wape_sesgo(registros, ["algoritmo", "horizonte"])
        self.assertEqual(tabla[0]["n_observaciones"], 1)
        self.assertEqual(tabla[0]["wape_pct"], 0.0)
        self.assertEqual(resumen["total_registros"], 3)
        self.assertEqual(resumen["excluidos_censura"], 1)
        self.assertEqual(resumen["excluidos_sin_prediccion"], 1)
        self.assertEqual(resumen["usados"], 1)

    def test_grupo_sin_observaciones_usables_da_none(self):
        registros = [self._reg("A2_media_movil_3m", 100.0, 999.0, censurado=True)]
        tabla, _ = agregar_wape_sesgo(registros, ["algoritmo"])
        self.assertEqual(tabla, [])  # el grupo nunca se crea si todo se excluye


# ---------------------------------------------------------------------------
# Censura por desabasto
# ---------------------------------------------------------------------------

class DetectarMesesDesabastoTests(unittest.TestCase):
    def test_devuelve_vacio_si_no_existe_tabla_kardex(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE materiales (material_id TEXT)")
        self.assertEqual(detectar_meses_desabasto(db), set())
        db.close()

    def test_marca_mes_con_saldo_en_cero(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE kardex_diario (
            material_id TEXT, plant TEXT, fecha TEXT, entradas REAL, salidas REAL, saldo_fin_dia REAL
        )""")
        filas = [
            ("M1", "P1", "2024-01-05", 0, 0, 0),   # desabasto en enero
            ("M1", "P1", "2024-01-06", 0, 0, 10),
            ("M1", "P1", "2024-02-01", 0, 0, 50),  # febrero sin desabasto
            ("M2", "P1", "2024-01-10", 0, 0, 5),
        ]
        db.executemany(
            "INSERT INTO kardex_diario VALUES (?,?,?,?,?,?)", filas
        )
        db.commit()
        resultado = detectar_meses_desabasto(db, umbral_dias=1)
        self.assertIn(("M1", "P1", "2024-01"), resultado)
        self.assertNotIn(("M1", "P1", "2024-02"), resultado)
        self.assertNotIn(("M2", "P1", "2024-01"), resultado)
        db.close()

    def test_meses_censurados_canal_agrega_por_cualquier_plant_del_canal(self):
        censurados_plant = {("M1", "P1", "2024-01"), ("M1", "P2", "2024-03")}
        plants_del_canal = {"Menudeo": {"P1", "P2", "P3"}}
        resultado = meses_censurados_canal(censurados_plant, "M1", "Menudeo", plants_del_canal)
        self.assertEqual(resultado, {"2024-01", "2024-03"})


# ---------------------------------------------------------------------------
# Simulación de servicio
# ---------------------------------------------------------------------------

class SimularServicioSerieTests(unittest.TestCase):
    def test_demanda_estable_bien_cubierta_no_genera_quiebres(self):
        # Demanda constante y política con objetivo de 2 meses -- ningún
        # algoritmo razonable debería generar quiebres en una serie tan lisa.
        meses = _meses(18)
        valores = [100.0] * 18
        resultado = simular_servicio_serie(
            meses, valores, m2_por_caja=1.0, moq_cajas=1, cajas_por_pallet=None,
            objetivo_meses=2.0, horizonte=3, n_origenes=6,
        )
        for nombre, r in resultado.items():
            self.assertEqual(r["quiebres"], 0, f"{nombre} no debería quebrar con demanda constante")
            self.assertGreater(r["meses_simulados"], 0)

    def test_serie_corta_devuelve_diccionario_vacio(self):
        resultado = simular_servicio_serie(
            _meses(2), [10.0, 20.0], m2_por_caja=1.0, moq_cajas=1, cajas_por_pallet=None,
        )
        self.assertEqual(resultado, {})

    def test_demanda_creciente_abrupta_puede_generar_quiebres(self):
        # Demanda plana y luego un salto fuerte y sostenido -- un algoritmo
        # que no reacciona (p.ej. seasonal-naive sin historia de ese salto)
        # debería registrar al menos algún quiebre.
        meses = _meses(18)
        valores = [10.0] * 12 + [200.0] * 6
        resultado = simular_servicio_serie(
            meses, valores, m2_por_caja=1.0, moq_cajas=1, cajas_por_pallet=None,
            objetivo_meses=1.0, horizonte=3, n_origenes=6,
        )
        total_quiebres = sum(r["quiebres"] for r in resultado.values())
        self.assertGreater(total_quiebres, 0)


# ---------------------------------------------------------------------------
# Estacionalidad por familia
# ---------------------------------------------------------------------------

class EstacionalidadFamiliaTests(unittest.TestCase):
    def test_detecta_pico_noviembre_significativo(self):
        # 2 años con pico consistente en noviembre (Buen Fin, como reporta el
        # ticket) y suficiente variación mes a mes para que el pico NO quede
        # aislado como z-score extremo (`detectar_atipicos` del motor C2 -- T22
        # -- excluiría un pico anual demasiado limpio/aislado como atípico
        # puntual, ya que la regla de rescate solo aplica a rachas
        # CONSECUTIVAS, no a picos que se repiten una vez al año).
        year1 = [90, 105, 96, 112, 88, 100, 95, 108, 92, 104, 118, 85]
        year2 = [93, 102, 99, 109, 91, 97, 103, 105, 89, 107, 121, 87]
        meses = _meses(24)
        r = analizar_estacionalidad_familia(meses, year1 + year2)
        self.assertIsNotNone(r)
        self.assertEqual(r["mes_pico"], "11")  # noviembre = mes calendario 11
        self.assertTrue(r["significativa"])

    def test_serie_plana_no_es_significativa(self):
        meses = _meses(24)
        valores = [100.0] * 24
        r = analizar_estacionalidad_familia(meses, valores)
        self.assertIsNotNone(r)
        self.assertFalse(r["significativa"])

    def test_none_con_historia_insuficiente(self):
        r = analizar_estacionalidad_familia(_meses(4), [10.0, 11.0, 9.0, 10.0])
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
