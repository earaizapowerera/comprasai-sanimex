"""Tests del motor de triggers de Balanceos v2 (waykee 292187):
estado_semaforo_balanceo, evaluar_trigger, permite_transferencia_por_prioridad,
calc_cantidad_sugerida_balanceo, calc_cajas_a_m2, calc_dias_desde_pedido.

Mismo patrón que tests/test_sugeridos_cobertura.py: stdlib unittest, sin
fixtures externas.

Ejecutar:
    cd backend && python3 -m unittest tests.test_balanceos_triggers -v
"""

import sys
import unittest
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.routers.engines.balanceos import (  # noqa: E402
    calc_cajas_a_m2,
    calc_cantidad_sugerida_balanceo,
    calc_dias_desde_pedido,
    es_rojo,
    estado_semaforo_balanceo,
    evaluar_trigger,
    permite_transferencia_por_prioridad,
)


class EstadoSemaforoBalanceoTests(unittest.TestCase):
    def test_disponible_negativo_es_quiebre(self):
        self.assertEqual(estado_semaforo_balanceo(-5, 3.0, 2.0), "quiebre")

    def test_disponible_cero_es_quiebre(self):
        self.assertEqual(estado_semaforo_balanceo(0, 3.0, 2.0), "quiebre")

    def test_sin_cobertura_es_sin_dato(self):
        self.assertEqual(estado_semaforo_balanceo(100, None, 2.0), "sin_dato")

    def test_cobertura_bajo_mitad_objetivo_es_quiebre(self):
        # objetivo=2 -> mitad=1.0; cobertura=0.8 < 1.0
        self.assertEqual(estado_semaforo_balanceo(100, 0.8, 2.0), "quiebre")

    def test_cobertura_entre_mitad_y_objetivo_es_riesgo(self):
        # objetivo=2 -> mitad=1.0; cobertura=1.5 está en [1.0, 2.0)
        self.assertEqual(estado_semaforo_balanceo(100, 1.5, 2.0), "riesgo")

    def test_cobertura_igual_objetivo_es_ok(self):
        self.assertEqual(estado_semaforo_balanceo(100, 2.0, 2.0), "ok")

    def test_cobertura_sobre_objetivo_es_ok(self):
        self.assertEqual(estado_semaforo_balanceo(100, 3.0, 2.0), "ok")

    def test_cobertura_sobre_2_5x_objetivo_es_exceso(self):
        # objetivo=2 -> 2.5x=5.0; cobertura=6.0 > 5.0
        self.assertEqual(estado_semaforo_balanceo(100, 6.0, 2.0), "exceso")

    def test_es_rojo_solo_para_quiebre(self):
        self.assertTrue(es_rojo("quiebre"))
        self.assertFalse(es_rojo("riesgo"))
        self.assertFalse(es_rojo("ok"))
        self.assertFalse(es_rojo("exceso"))
        self.assertFalse(es_rojo("sin_dato"))


class EvaluarTriggerTests(unittest.TestCase):
    def test_sin_pedido_siempre_dispara_si_hay_alternativa(self):
        # rojo (disponible_neto=0), sin pedido pendiente, con alternativa en zona
        r = evaluar_trigger(0, 0.0, 2.0, pedidos_abiertos=0, dias_desde_pedido=None,
                             umbral_dias=30, hay_alternativa_en_zona=True)
        self.assertIsNotNone(r)
        self.assertEqual(r["trigger"], "sin_pedido")

    def test_con_pedido_bajo_umbral_no_dispara(self):
        r = evaluar_trigger(0, 0.0, 2.0, pedidos_abiertos=50, dias_desde_pedido=10,
                             umbral_dias=30, hay_alternativa_en_zona=True)
        self.assertIsNone(r)

    def test_con_pedido_sobre_umbral_dispara(self):
        r = evaluar_trigger(0, 0.0, 2.0, pedidos_abiertos=50, dias_desde_pedido=45,
                             umbral_dias=30, hay_alternativa_en_zona=True)
        self.assertIsNotNone(r)
        self.assertEqual(r["trigger"], "con_pedido_vencido")
        self.assertEqual(r["diasDesdePedido"], 45)
        self.assertEqual(r["umbralDias"], 30)

    def test_con_pedido_justo_en_umbral_no_dispara(self):
        # dias_desde_pedido <= umbral_dias -> NO dispara (spec: "si <= umbral no sugerir")
        r = evaluar_trigger(0, 0.0, 2.0, pedidos_abiertos=50, dias_desde_pedido=30,
                             umbral_dias=30, hay_alternativa_en_zona=True)
        self.assertIsNone(r)

    def test_sin_alternativa_en_zona_nunca_dispara(self):
        r = evaluar_trigger(0, 0.0, 2.0, pedidos_abiertos=0, dias_desde_pedido=None,
                             umbral_dias=30, hay_alternativa_en_zona=False)
        self.assertIsNone(r)

    def test_no_rojo_nunca_dispara(self):
        # riesgo, no quiebre
        r = evaluar_trigger(100, 1.5, 2.0, pedidos_abiertos=0, dias_desde_pedido=None,
                             umbral_dias=30, hay_alternativa_en_zona=True)
        self.assertIsNone(r)

    def test_ok_nunca_dispara(self):
        r = evaluar_trigger(100, 3.0, 2.0, pedidos_abiertos=0, dias_desde_pedido=None,
                             umbral_dias=30, hay_alternativa_en_zona=True)
        self.assertIsNone(r)


class PermiteTransferenciaPorPrioridadTests(unittest.TestCase):
    def test_excedente_origen_ignora_prioridad_siempre(self):
        # origen tiene MENOS prioridad relativa pero SÍ tiene excedente -> permite
        self.assertTrue(permite_transferencia_por_prioridad(
            prioridad_origen=10, prioridad_destino=1, excedente_origen=50))

    def test_sin_excedente_prioridad_origen_mayor_bloquea(self):
        self.assertFalse(permite_transferencia_por_prioridad(
            prioridad_origen=10, prioridad_destino=1, excedente_origen=0))

    def test_sin_excedente_prioridad_destino_mayor_permite(self):
        self.assertTrue(permite_transferencia_por_prioridad(
            prioridad_origen=1, prioridad_destino=10, excedente_origen=0))

    def test_sin_excedente_prioridades_iguales_permite(self):
        self.assertTrue(permite_transferencia_por_prioridad(
            prioridad_origen=5, prioridad_destino=5, excedente_origen=0))


class CalcCantidadSugeridaBalanceoTests(unittest.TestCase):
    def test_golden_case_1_cubre_deficit_completo(self):
        r = calc_cantidad_sugerida_balanceo(
            disponible_neto_origen=200, demanda_origen=20,
            disponible_neto_destino=10, demanda_destino=20,
            meses_objetivo_destino=2.0, es_cedis_origen=False,
            destino_tiene_mayor_prioridad=False,
        )
        self.assertAlmostEqual(r["cantidadParaObjetivo"], 30.0)
        self.assertAlmostEqual(r["tope"], 95.0)
        self.assertAlmostEqual(r["cantidadSugerida"], 30.0)
        self.assertEqual(r["fuenteTope"], "emparejar_meses_origen_destino")

    def test_golden_case_2_topado_por_emparejar_meses(self):
        r = calc_cantidad_sugerida_balanceo(
            disponible_neto_origen=40, demanda_origen=20,
            disponible_neto_destino=0, demanda_destino=10,
            meses_objetivo_destino=2.0, es_cedis_origen=False,
            destino_tiene_mayor_prioridad=False,
        )
        self.assertAlmostEqual(r["cantidadParaObjetivo"], 20.0)
        self.assertAlmostEqual(r["tope"], 13.33, places=2)
        self.assertAlmostEqual(r["cantidadSugerida"], 13.33, places=2)
        self.assertEqual(r["fuenteTope"], "emparejar_meses_origen_destino")

    def test_cedis_origen_no_topa_por_emparejar_meses(self):
        # mismo escenario del golden case 2, pero origen es CEDIS: tope = todo
        # lo disponible en CEDIS, no el emparejamiento de meses.
        r = calc_cantidad_sugerida_balanceo(
            disponible_neto_origen=40, demanda_origen=20,
            disponible_neto_destino=0, demanda_destino=10,
            meses_objetivo_destino=2.0, es_cedis_origen=True,
            destino_tiene_mayor_prioridad=False,
        )
        self.assertAlmostEqual(r["tope"], 40.0)
        self.assertAlmostEqual(r["cantidadSugerida"], 20.0)  # limitado por el déficit, no por el tope
        self.assertEqual(r["fuenteTope"], "solo_disponible_cedis")

    def test_prioridad_destino_mayor_levanta_tope_de_meses(self):
        r = calc_cantidad_sugerida_balanceo(
            disponible_neto_origen=40, demanda_origen=20,
            disponible_neto_destino=0, demanda_destino=10,
            meses_objetivo_destino=2.0, es_cedis_origen=False,
            destino_tiene_mayor_prioridad=True,
        )
        self.assertAlmostEqual(r["tope"], 40.0)
        self.assertEqual(r["fuenteTope"], "prioridad_destino_sin_tope_meses")

    def test_deficit_cero_no_sugiere_nada(self):
        r = calc_cantidad_sugerida_balanceo(
            disponible_neto_origen=200, demanda_origen=20,
            disponible_neto_destino=50, demanda_destino=20,
            meses_objetivo_destino=2.0, es_cedis_origen=False,
            destino_tiene_mayor_prioridad=False,
        )
        self.assertAlmostEqual(r["cantidadParaObjetivo"], 0.0)
        self.assertAlmostEqual(r["cantidadSugerida"], 0.0)


class CalcCajasAM2Tests(unittest.TestCase):
    def test_conversion_normal(self):
        self.assertAlmostEqual(calc_cajas_a_m2(70, 1.44), 100.8)

    def test_sin_m2_por_caja_retorna_cajas_tal_cual(self):
        self.assertAlmostEqual(calc_cajas_a_m2(70, None), 70.0)

    def test_m2_por_caja_cero_retorna_cajas_tal_cual(self):
        self.assertAlmostEqual(calc_cajas_a_m2(70, 0), 70.0)


class CalcDiasDesdePedidoTests(unittest.TestCase):
    def test_es_deterministico(self):
        hoy = date(2026, 9, 23)
        d1 = calc_dias_desde_pedido("SAN-PIS-0112", "P010", hoy)
        d2 = calc_dias_desde_pedido("SAN-PIS-0112", "P010", hoy)
        self.assertEqual(d1, d2)

    def test_esta_dentro_de_la_ventana_simulada(self):
        # _fecha_pedido_simulada en semaforo.py usa MAX_ANTIGUEDAD_DIAS=45
        hoy = date(2026, 9, 23)
        dias = calc_dias_desde_pedido("SAN-AZU-0087", "P021", hoy)
        self.assertGreaterEqual(dias, 0)
        self.assertLessEqual(dias, 45)

    def test_distintas_ubicaciones_pueden_dar_dias_distintos(self):
        hoy = date(2026, 9, 23)
        dias_por_plant = {
            plant: calc_dias_desde_pedido("SAN-PIS-0112", plant, hoy)
            for plant in ("P001", "P002", "P003", "P004", "P005")
        }
        # No es una garantía matemática (podría colisionar por azar del hash),
        # pero con 5 plants distintos y ventana de 46 valores posibles, ver al
        # menos 2 valores distintos confirma que la ubicación sí influye.
        self.assertGreater(len(set(dias_por_plant.values())), 1)


if __name__ == "__main__":
    unittest.main()
