"""Tests para T28 (waykee 291765): motor de 3 promedios en engines/sugeridos.py
-- reemplaza al promedio móvil corto (T19/T25) como base de cobertura,
faltante y compra sugerida, en paridad con la hoja Excel del área de compras.

Cubre:
  - Las funciones puras nuevas (calc_promedio_simple, calc_promedio_ultimos_n,
    calc_valor_mes_ajustado, calc_promedio_general, calc_compra_sugerida,
    calc_redondeo_pallets_completos, calc_motivo_redondeo_pallet, calc_mediana,
    calc_mad, calc_es_outlier_venta_dia), validadas contra los casos golden
    literales del mensaje puente (waykee 290066->291765).
  - build_datos_decision: arma el payload "historia"/"compra" a partir de
    inputs puros.
  - generar_sugeridos (integración, DB en memoria): el payload de /generar
    calcula PROMEDIO_GENERAL y compra sugerida con la fórmula del Excel, y
    detecta "sobrevendido" cuando disponible_neto < 0.
  - lista_sugeridos: lo persistido en sugeridos_generados se recupera vía
    datos_decision_json.
  - Promedio 3 en sus 3 modos (ventas_stats_mensuales / kardex_diario / sin
    datos), degradando con gracia según qué tablas existan.

Ejecutar (sin dependencias extra, solo stdlib):
    cd backend && python3 -m unittest tests.test_sugeridos_datos_decision -v
"""

import sqlite3
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.routers.engines.sugeridos import (  # noqa: E402
    RATIO_M2_POR_PIEZA_FALLBACK,
    _a_m2,
    _dias_calendario_mes,
    backorder_detalle,
    build_datos_decision,
    calc_compra_sugerida,
    calc_consumo_mes_referencia_corregido,
    calc_dias_sin_inventario_por_mes,
    calc_es_outlier_venta_dia,
    calc_factor_m2_por_pieza,
    calc_mad,
    calc_mediana,
    calc_motivo_redondeo_pallet,
    calc_promedio_general,
    calc_promedio_simple,
    calc_promedio_ultimos_n,
    calc_redondeo_pallets_completos,
    calc_valor_mes_ajustado,
    generar_sugeridos,
    lista_sugeridos,
    pedidos_detalle,
)

SCHEMA_PATH = BACKEND_DIR / "app" / "core" / "schema.sql"


class CalcPromedio3PromediosTests(unittest.TestCase):
    """Casos golden literales del mensaje puente (waykee 290066->291765,
    hoja Excel del área de compras): abril 30->28, junio 39->30, PROMEDIO
    504.67 = promedio de 482/438/594, Compra Sugerida 2019, Pallets 2032."""

    def test_calc_promedio_simple(self):
        self.assertAlmostEqual(calc_promedio_simple([10, 20, 30]), 20.0)
        self.assertEqual(calc_promedio_simple([]), 0.0)

    def test_calc_promedio_ultimos_n(self):
        self.assertAlmostEqual(calc_promedio_ultimos_n([10, 20, 30, 40, 50], 2), 45.0)
        self.assertEqual(calc_promedio_ultimos_n([10, 20], 0), 0.0)

    def test_calc_valor_mes_ajustado_abril(self):
        self.assertAlmostEqual(calc_valor_mes_ajustado(30, 2), 28.0)

    def test_calc_valor_mes_ajustado_junio(self):
        self.assertAlmostEqual(calc_valor_mes_ajustado(39, 9), 30.0)

    def test_calc_valor_mes_ajustado_nunca_negativo(self):
        self.assertEqual(calc_valor_mes_ajustado(5, 20), 0.0)

    def test_calc_promedio_general(self):
        self.assertAlmostEqual(calc_promedio_general(482, 438, 594), 504.6667, places=3)

    def test_calc_compra_sugerida_caso_golden(self):
        # 6 * 504.6667 - 536 - 473 = 2019.0 (comprometido era 0 en este caso,
        # así que el resultado no cambia con la fórmula T29 sin comprometido).
        self.assertAlmostEqual(
            calc_compra_sugerida(6, 504.6667, 536, 473), 2019.0, places=1
        )

    def test_calc_compra_sugerida_no_baja_de_cero(self):
        self.assertEqual(calc_compra_sugerida(2, 10, 1000, 0), 0.0)

    def test_calc_compra_sugerida_ignora_comprometido(self):
        # T29 (waykee 291788, punto 4): "Backorder venta (comprometido)" es en
        # realidad backorder TRASLADO (mercancía por salir de la sucursal, no
        # una venta pendiente de surtir) -- ya NO debe afectar el monto a
        # comprar. Mismo golden case que arriba, pero demostrando que un
        # comprometido>0 no cambia el resultado porque la función ya ni
        # siquiera acepta ese parámetro.
        self.assertAlmostEqual(
            calc_compra_sugerida(6, 504.6667, 536, 473), 2019.0, places=1
        )

    def test_calc_redondeo_pallets_completos_caso_golden(self):
        self.assertEqual(calc_redondeo_pallets_completos(2019, 16), 2032)

    def test_calc_redondeo_pallets_completos_cero(self):
        self.assertEqual(calc_redondeo_pallets_completos(0, 40), 0)

    def test_calc_redondeo_pallets_completos_fallback_sin_pallet(self):
        self.assertEqual(calc_redondeo_pallets_completos(10, None), 40)

    def test_calc_mediana_impar(self):
        self.assertEqual(calc_mediana([1, 5, 3]), 3)

    def test_calc_mediana_par(self):
        self.assertEqual(calc_mediana([1, 2, 3, 4]), 2.5)

    def test_calc_mad(self):
        self.assertEqual(calc_mad([1, 2, 3, 4, 5]), 1.0)

    def test_calc_es_outlier_venta_dia_detecta_pico(self):
        valores = [10, 11, 9, 10, 100]
        self.assertTrue(calc_es_outlier_venta_dia(valores, 100))
        self.assertFalse(calc_es_outlier_venta_dia(valores, 10))

    def test_calc_es_outlier_venta_dia_pocos_puntos_nunca_outlier(self):
        self.assertFalse(calc_es_outlier_venta_dia([10], 10))

    def test_calc_factor_m2_por_pieza_promedia_ratios_mes_a_mes(self):
        # (57.6/57.6, 28.8/28.8) = (1.0, 1.0) -> 1.0, no el ratio de sumas totales.
        self.assertAlmostEqual(calc_factor_m2_por_pieza([(57.6, 57.6), (28.8, 28.8)]), 1.0)

    def test_calc_factor_m2_por_pieza_sin_superposicion_usa_fallback_global(self):
        self.assertEqual(calc_factor_m2_por_pieza([]), RATIO_M2_POR_PIEZA_FALLBACK)
        self.assertEqual(calc_factor_m2_por_pieza([(57.6, 0)]), RATIO_M2_POR_PIEZA_FALLBACK)

    def test_calc_consumo_mes_referencia_corregido_convierte_piezas_a_cajas(self):
        # 100 piezas * factor 1.0 = 100 m2 / 1.44 m2_por_caja -> ceil(69.44) = 70 cajas.
        self.assertEqual(calc_consumo_mes_referencia_corregido(100, 1.44, 1.0), 70)


class CalcMotivoRedondeoPalletTests(unittest.TestCase):
    def test_sin_compra_por_transferencia(self):
        self.assertIn("transferencia", calc_motivo_redondeo_pallet(0, 0, 40))

    def test_sube_a_pallet(self):
        motivo = calc_motivo_redondeo_pallet(bruta=2019, final=2032, cajas_por_pallet=16)
        self.assertIn("2032", motivo)
        self.assertIn("16", motivo)

    def test_sin_ajuste(self):
        motivo = calc_motivo_redondeo_pallet(bruta=40, final=40, cajas_por_pallet=40)
        self.assertIn("Sin ajuste", motivo)


class DiasSinInventarioTests(unittest.TestCase):
    """T29 (waykee 291788, punto 3): días sin inventario por mes, detrás de
    una única función (calc_dias_sin_inventario_por_mes) para poder
    reemplazar la fuente por HANA en v7 sin tocar al llamador."""

    def test_dias_calendario_mes_28_29_30_31(self):
        self.assertEqual(len(_dias_calendario_mes("2026-02")), 28)  # no bisiesto
        self.assertEqual(len(_dias_calendario_mes("2024-02")), 29)  # bisiesto
        self.assertEqual(len(_dias_calendario_mes("2026-04")), 30)
        self.assertEqual(len(_dias_calendario_mes("2026-01")), 31)
        self.assertEqual(_dias_calendario_mes("2026-01")[0], "2026-01-01")
        self.assertEqual(_dias_calendario_mes("2026-01")[-1], "2026-01-31")

    def test_dias_calendario_mes_diciembre_cruza_anio(self):
        dias = _dias_calendario_mes("2025-12")
        self.assertEqual(len(dias), 31)
        self.assertEqual(dias[-1], "2025-12-31")

    def test_sin_stockout_da_cero_dias(self):
        puntos = [("2026-07-01", 100.0), ("2026-08-01", 80.0)]
        res = calc_dias_sin_inventario_por_mes(puntos, ["2026-07", "2026-08"])
        self.assertEqual(res["2026-07"]["dias"], 0)
        self.assertEqual(res["2026-08"]["dias"], 0)
        self.assertFalse(res["2026-07"]["cobertura_parcial"])

    def test_arrastra_saldo_cero_hasta_el_proximo_movimiento(self):
        # Se queda en 0 desde el día 10 hasta fin de mes (21 días en un mes de 30).
        puntos = [("2026-04-01", 50.0), ("2026-04-10", 0.0), ("2026-05-05", 30.0)]
        res = calc_dias_sin_inventario_por_mes(puntos, ["2026-04", "2026-05"])
        self.assertEqual(res["2026-04"]["dias"], 21)
        self.assertEqual(res["2026-04"]["dias_con_dato"], 30)
        self.assertFalse(res["2026-04"]["cobertura_parcial"])

    def test_kardex_no_cubre_el_mes_marca_cobertura_parcial(self):
        # Primer movimiento a mitad de mes: los días previos quedan sin determinar.
        puntos = [("2026-06-15", 40.0)]
        res = calc_dias_sin_inventario_por_mes(puntos, ["2026-06"])
        self.assertEqual(res["2026-06"]["dias_con_dato"], 16)  # 15..30
        self.assertTrue(res["2026-06"]["cobertura_parcial"])

    def test_sin_ningun_movimiento_todo_sin_determinar(self):
        res = calc_dias_sin_inventario_por_mes([], ["2026-06"])
        self.assertEqual(res["2026-06"]["dias"], 0)
        self.assertEqual(res["2026-06"]["dias_con_dato"], 0)
        self.assertTrue(res["2026-06"]["cobertura_parcial"])

    def test_saldo_negativo_cuenta_como_sin_inventario(self):
        puntos = [("2026-06-01", -5.0)]
        res = calc_dias_sin_inventario_por_mes(puntos, ["2026-06"])
        self.assertEqual(res["2026-06"]["dias"], 30)


class AM2Tests(unittest.TestCase):
    def test_convierte_cajas_a_m2(self):
        self.assertAlmostEqual(_a_m2(10, 1.44), 14.4, places=2)

    def test_sin_factor_regresa_none(self):
        self.assertIsNone(_a_m2(10, None))
        self.assertIsNone(_a_m2(10, 0))

    def test_valor_none_regresa_none(self):
        self.assertIsNone(_a_m2(None, 1.44))


class BuildDatosDecisionTests(unittest.TestCase):
    def _base_kwargs(self, **overrides):
        kwargs = dict(
            historia_meses=["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"],
            historia_consumo=[40.0, 40.0, 40.0, 40.0, 40.0],
            promedio_1=40.0,
            promedio_2=40.0,
            promedio_3=40.0,
            promedio_3_ajustes=[
                {"anio_mes": m, "valor_ajustado": 40.0, "ajuste_cajas": 0.0, "fuente": "sin_datos", "fecha_pico": None, "es_outlier": None}
                for m in ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
            ],
            promedio_general=40.0,
            meses_actual=2.5,
            meses_con_venta=5,
            meses_historia=6,
            disponible=100.0,
            transito=0.0,
            comprometido=50.0,
            disponible_neto=50.0,
            cobertura_actual=1.25,
            meses_objetivo=2.0,
            compra_sugerida=30.0,
            proveedor="Proveedor Uno",
            moq_cajas=20,
            cajas_por_pallet=40,
            lead_time_dias=10,
            m2_por_caja=1.44,
            costo_unitario=15.0,
            cantidad_transferir=0.0,
            detalle_transferencias=[],
            cantidad_comprar_bruta=30.0,
            cantidad_final=40,
            n_pallets=1,
        )
        kwargs.update(overrides)
        return kwargs

    def test_no_inventa_numeros_todo_es_trazable(self):
        dd = build_datos_decision(**self._base_kwargs())
        self.assertEqual(dd["promedio_general"], 40.0)
        self.assertEqual(dd["meses_actual"], 2.5)
        self.assertEqual(dd["inventario"]["disponible"], 100.0)
        self.assertEqual(dd["inventario"]["comprometido"], 50.0)
        self.assertEqual(dd["inventario"]["disponible_neto"], 50.0)
        self.assertFalse(dd["inventario"]["sobrevendido"])
        self.assertEqual(dd["proveedor"]["nombre"], "Proveedor Uno")
        self.assertEqual(dd["proveedor"]["lead_time_dias"], 10)
        self.assertEqual(len(dd["historia"]["meses"]), 5)
        self.assertEqual(dd["historia"]["promedio_1"]["valor"], 40.0)
        self.assertEqual(dd["historia"]["promedio_2"]["valor"], 40.0)
        self.assertEqual(dd["historia"]["promedio_3"]["valor"], 40.0)

    def test_promedio_2_marca_solo_los_ultimos_n_meses(self):
        dd = build_datos_decision(**self._base_kwargs())
        incluidos = [
            mes for mes, inc in zip(dd["historia"]["meses"], dd["historia"]["promedio_2"]["incluidos"]) if inc
        ]
        self.assertEqual(incluidos, ["2026-07", "2026-08"])

    def test_inventario_fin_mes_sin_kardex_queda_en_none(self):
        dd = build_datos_decision(**self._base_kwargs())
        self.assertFalse(dd["kardex_disponible"])
        self.assertTrue(all(p["saldo"] is None for p in dd["inventario_fin_mes"]))

    def test_inventario_fin_mes_con_kardex_expone_saldo_por_mes(self):
        dd = build_datos_decision(**self._base_kwargs(
            inventario_fin_mes={"2026-06": 120.0, "2026-07": 100.0, "2026-08": 80.0},
            kardex_disponible=True,
        ))
        self.assertTrue(dd["kardex_disponible"])
        por_mes = {p["anio_mes"]: p["saldo"] for p in dd["inventario_fin_mes"]}
        self.assertEqual(por_mes["2026-06"], 120.0)

    def test_sobrevendido_cuando_disponible_neto_negativo(self):
        dd = build_datos_decision(**self._base_kwargs(
            disponible=10.0, comprometido=50.0, disponible_neto=-40.0,
        ))
        self.assertTrue(dd["inventario"]["sobrevendido"])
        self.assertEqual(dd["inventario"]["disponible_neto"], -40.0)

    def test_cobertura_none_se_preserva(self):
        dd = build_datos_decision(**self._base_kwargs(cobertura_actual=None))
        self.assertIsNone(dd["cobertura_actual"])

    def test_transferencia_y_compra_expuestos(self):
        detalle = [{"desde_plant": "P2", "cantidad": 15.0}]
        dd = build_datos_decision(**self._base_kwargs(
            cantidad_transferir=15.0, detalle_transferencias=detalle,
            cantidad_comprar_bruta=15.0, cantidad_final=40, n_pallets=1,
        ))
        self.assertEqual(dd["transferencia"]["cantidad_transferir"], 15.0)
        self.assertEqual(dd["transferencia"]["detalle_transferencias"], detalle)
        self.assertEqual(dd["compra"]["cantidad_final_cajas"], 40)
        self.assertEqual(dd["compra"]["n_pallets"], 1)
        self.assertIn("pallet", dd["compra"]["motivo"])

    def test_compra_sugerida_m2_usa_m2_por_caja(self):
        dd = build_datos_decision(**self._base_kwargs(compra_sugerida=70.0, m2_por_caja=1.44))
        self.assertAlmostEqual(dd["compra"]["compra_sugerida_m2"], round(70.0 * 1.44, 2))


def _build_memory_db():
    """DB SQLite en memoria (esquema real) con dos pares material-plant:
    MAT-NORMAL (caso típico, disponible_neto positivo) y MAT-SOBREVENDIDO
    (comprometido > disponible + tránsito -> disponible_neto negativo)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())

    conn.execute(
        "INSERT INTO materiales (material_id, descripcion, familia, abc, m2_por_caja, costo) VALUES "
        "('MAT-NORMAL', 'Normal', 'F1', 'A', 1.44, 15), "
        "('MAT-SOBREVENDIDO', 'Sobrevendido', 'F1', 'A', 1.44, 15)"
    )
    conn.execute(
        "INSERT INTO sucursales (plant, nombre, organizacion, canal) VALUES "
        "('P1', 'Sucursal 1', 'GAM', 'Menudeo')"
    )
    conn.execute(
        "INSERT INTO inventarios (material_id, plant, disponible, transito, comprometido) VALUES "
        "('MAT-NORMAL', 'P1', 100, 0, 50), "
        "('MAT-SOBREVENDIDO', 'P1', 10, 0, 50)"
    )
    conn.execute(
        "INSERT INTO coberturas_objetivo (material_id, meses_objetivo) VALUES "
        "('MAT-NORMAL', 2.0), ('MAT-SOBREVENDIDO', 2.0)"
    )
    conn.execute(
        "INSERT INTO proveedores (material_id, proveedor, lead_time_dias, moq_cajas, cajas_por_pallet) VALUES "
        "('MAT-NORMAL', 'Proveedor Uno', 10, 20, 40), "
        "('MAT-SOBREVENDIDO', 'Proveedor Dos', 12, 20, 40)"
    )
    # MAT-NORMAL: 40 cajas/mes x 5 meses -> promedio_general=40, disponible_neto(50)/40=1.25 < objetivo(2.0).
    # MAT-SOBREVENDIDO: 20 cajas/mes x 5 meses -> disponible_neto=-40 (comprometido excede stock).
    conn.execute(
        "INSERT INTO ventas_mensuales (material_id, plant, canal, anio_mes, cantidad_m2, importe) VALUES "
        "('MAT-NORMAL', 'P1', 'Menudeo', '2026-04', 57.6, 0), "
        "('MAT-NORMAL', 'P1', 'Menudeo', '2026-05', 57.6, 0), "
        "('MAT-NORMAL', 'P1', 'Menudeo', '2026-06', 57.6, 0), "
        "('MAT-NORMAL', 'P1', 'Menudeo', '2026-07', 57.6, 0), "
        "('MAT-NORMAL', 'P1', 'Menudeo', '2026-08', 57.6, 0), "
        "('MAT-SOBREVENDIDO', 'P1', 'Menudeo', '2026-04', 28.8, 0), "
        "('MAT-SOBREVENDIDO', 'P1', 'Menudeo', '2026-05', 28.8, 0), "
        "('MAT-SOBREVENDIDO', 'P1', 'Menudeo', '2026-06', 28.8, 0), "
        "('MAT-SOBREVENDIDO', 'P1', 'Menudeo', '2026-07', 28.8, 0), "
        "('MAT-SOBREVENDIDO', 'P1', 'Menudeo', '2026-08', 28.8, 0)"
    )
    conn.commit()
    return conn


class GenerarSugeridosDatosDecisionIntegrationTests(unittest.TestCase):
    """/api/engines/sugeridos/generar debe traer 'datos_decision' con el
    motor de 3 promedios (historia/compra), no el promedio corto legado."""

    def setUp(self):
        self.conn = _build_memory_db()

    def tearDown(self):
        self.conn.close()

    def _generar(self):
        return generar_sugeridos(
            familia=None, proveedor=None, corredor=None, plant=None, abc=None,
            solo_criticos=False, page=1, page_size=50, db=self.conn,
        )

    def _items_by_material(self):
        return {it["material_id"]: it for it in self._generar()["items"]}

    def test_factores_ya_no_se_expone(self):
        items = self._items_by_material()
        for it in items.values():
            self.assertNotIn("factores", it)
            self.assertIn("datos_decision", it)

    def test_mat_normal_datos_decision_completos(self):
        it = self._items_by_material()["MAT-NORMAL"]
        dd = it["datos_decision"]
        # Sin ventas_stats_mensuales ni kardex_diario -> Promedio 3 == Promedio 1
        # (sin ajuste), así que PROMEDIO_GENERAL == 40 (los 5 meses son parejos).
        self.assertEqual(
            dd["historia"]["meses"],
            ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"],
        )
        self.assertAlmostEqual(dd["historia"]["promedio_1"]["valor"], 40.0, places=1)
        self.assertAlmostEqual(dd["historia"]["promedio_2"]["valor"], 40.0, places=1)
        self.assertAlmostEqual(dd["historia"]["promedio_3"]["valor"], 40.0, places=1)
        self.assertAlmostEqual(dd["promedio_general"], 40.0, places=1)
        self.assertEqual(dd["inventario"]["disponible"], 100)
        self.assertEqual(dd["inventario"]["comprometido"], 50)
        self.assertAlmostEqual(dd["inventario"]["disponible_neto"], 50.0, places=1)
        self.assertFalse(dd["inventario"]["sobrevendido"])
        self.assertEqual(dd["proveedor"]["nombre"], "Proveedor Uno")
        self.assertEqual(dd["proveedor"]["cajas_por_pallet"], 40)
        self.assertIsInstance(dd["compra"]["motivo"], str)
        self.assertGreater(len(dd["compra"]["motivo"]), 0)
        # T29 (punto 4): comprometido YA NO participa en el monto.
        # Compra sugerida: 2*40 - 100 - 0 = -20 -> clamp a 0.0 (sin compra).
        self.assertAlmostEqual(dd["compra"]["compra_sugerida_cajas"], 0.0, places=1)
        self.assertEqual(dd["compra"]["cantidad_final_cajas"], 0)
        self.assertEqual(dd["compra"]["n_pallets"], 0)

    def test_comprometido_no_afecta_compra_sugerida_pero_si_disponible_neto(self):
        # T29 (waykee 291788, punto 4), golden test explícito del PM: dos
        # escenarios idénticos salvo `comprometido` deben producir la MISMA
        # compra_sugerida_cajas (ya no es parte de esa fórmula), aunque
        # disponible_neto/sobrevendido (RN-01, decide SI sugerir) sí cambien.
        dd_bajo = self._items_by_material()["MAT-NORMAL"]["datos_decision"]
        self.conn.execute(
            "UPDATE inventarios SET comprometido = 500 "
            "WHERE material_id='MAT-NORMAL' AND plant='P1'"
        )
        dd_alto = self._items_by_material()["MAT-NORMAL"]["datos_decision"]
        self.assertEqual(
            dd_bajo["compra"]["compra_sugerida_cajas"],
            dd_alto["compra"]["compra_sugerida_cajas"],
        )
        self.assertNotEqual(
            dd_bajo["inventario"]["disponible_neto"],
            dd_alto["inventario"]["disponible_neto"],
        )

    def test_mat_sobrevendido_marca_disponible_neto_negativo(self):
        it = self._items_by_material()["MAT-SOBREVENDIDO"]
        dd = it["datos_decision"]
        self.assertTrue(dd["inventario"]["sobrevendido"])
        self.assertLess(dd["inventario"]["disponible_neto"], 0)
        self.assertAlmostEqual(dd["inventario"]["disponible_neto"], -40.0, places=1)


class ListaSugeridosDatosDecisionIntegrationTests(unittest.TestCase):
    """/api/engines/sugeridos/lista debe reconstruir datos_decision desde la
    columna persistida datos_decision_json."""

    def setUp(self):
        self.conn = _build_memory_db()
        generar_sugeridos(
            familia=None, proveedor=None, corredor=None, plant=None, abc=None,
            solo_criticos=False, page=1, page_size=50, db=self.conn,
        )

    def tearDown(self):
        self.conn.close()

    def test_lista_expone_datos_decision_persistido(self):
        items = lista_sugeridos(estado="propuesto", db=self.conn)["items"]
        self.assertGreater(len(items), 0)
        for it in items:
            self.assertNotIn("factores", it)
            self.assertNotIn("factores_json", it)
            self.assertNotIn("datos_decision_json", it)
            self.assertIn("datos_decision", it)
            self.assertIsInstance(it["datos_decision"], dict)
            self.assertIn("inventario", it["datos_decision"])

    def test_lista_sobrevendido_persiste_flag(self):
        items = {it["material_id"]: it for it in lista_sugeridos(estado="propuesto", db=self.conn)["items"]}
        self.assertTrue(items["MAT-SOBREVENDIDO"]["datos_decision"]["inventario"]["sobrevendido"])


class KardexDiarioIntegrationTests(unittest.TestCase):
    """kardex_diario sigue siendo opcional -- generar_sugeridos debe degradar
    con gracia (kardex_disponible=False, saldo None por mes) cuando falta, y
    usar el saldo real (arrastrado del último movimiento <= fin de mes) cuando
    sí está poblada. Poblarla también activa el modo 'kardex' de Promedio 3."""

    def setUp(self):
        self.conn = _build_memory_db()

    def tearDown(self):
        self.conn.close()

    def _generar_datos_decision(self, material_id="MAT-NORMAL"):
        items = generar_sugeridos(
            familia=None, proveedor=None, corredor=None, plant=None, abc=None,
            solo_criticos=False, page=1, page_size=50, db=self.conn,
        )["items"]
        return {i["material_id"]: i for i in items}[material_id]["datos_decision"]

    def _crear_kardex_diario(self):
        self.conn.execute(
            """CREATE TABLE kardex_diario (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id TEXT NOT NULL,
                plant TEXT NOT NULL,
                fecha TEXT NOT NULL,
                entradas REAL NOT NULL DEFAULT 0,
                salidas REAL NOT NULL DEFAULT 0,
                saldo_fin_dia REAL NOT NULL DEFAULT 0
            )"""
        )

    def test_sin_tabla_kardex_diario_marca_no_disponible(self):
        dd = self._generar_datos_decision()
        self.assertFalse(dd["kardex_disponible"])
        self.assertEqual(len(dd["inventario_fin_mes"]), len(dd["historia"]["meses"]))
        self.assertTrue(all(p["saldo"] is None for p in dd["inventario_fin_mes"]))
        # Sin kardex ni stats: Promedio 3 sin ajuste (fuente 'sin_datos').
        self.assertTrue(all(a["fuente"] == "sin_datos" for a in dd["historia"]["promedio_3"]["ajustes"]))

    def test_con_kardex_diario_poblado_arrastra_saldo_de_fin_de_mes(self):
        self._crear_kardex_diario()
        # Sin movimiento en julio a propósito: el saldo debe ARRASTRARSE del
        # último movimiento conocido (15-jun), igual que un kardex real.
        self.conn.execute(
            "INSERT INTO kardex_diario (material_id, plant, fecha, saldo_fin_dia) VALUES "
            "('MAT-NORMAL', 'P1', '2026-06-15', 120), "
            "('MAT-NORMAL', 'P1', '2026-08-10', 80)"
        )
        self.conn.commit()
        dd = self._generar_datos_decision()
        self.assertTrue(dd["kardex_disponible"])
        por_mes = {p["anio_mes"]: p["saldo"] for p in dd["inventario_fin_mes"]}
        self.assertEqual(por_mes["2026-06"], 120)
        self.assertEqual(por_mes["2026-07"], 120)  # arrastrado, sin movimiento propio
        self.assertEqual(por_mes["2026-08"], 80)

    def test_kardex_con_salidas_activa_modo_pico_en_promedio_3(self):
        self._crear_kardex_diario()
        # Julio: 3 días con salida, pico real de 30 cajas (30*1.44=43.2 m2) el
        # día 20 -- debe restarse del consumo de julio (40 cajas) en Promedio 3.
        self.conn.execute(
            "INSERT INTO kardex_diario (material_id, plant, fecha, salidas, saldo_fin_dia) VALUES "
            "('MAT-NORMAL', 'P1', '2026-07-05', 14.4, 100), "
            "('MAT-NORMAL', 'P1', '2026-07-20', 43.2, 60), "
            "('MAT-NORMAL', 'P1', '2026-07-25', 0.0, 60)"
        )
        self.conn.commit()
        dd = self._generar_datos_decision()
        ajuste_julio = next(a for a in dd["historia"]["promedio_3"]["ajustes"] if a["anio_mes"] == "2026-07")
        self.assertEqual(ajuste_julio["fuente"], "dia_pico_kardex")
        self.assertEqual(ajuste_julio["fecha_pico"], "2026-07-20")
        self.assertEqual(ajuste_julio["ajuste_cajas"], 30)
        self.assertEqual(ajuste_julio["valor_ajustado"], 10.0)  # 40 - 30

    def test_ventas_stats_mensuales_tiene_prioridad_sobre_kardex(self):
        self._crear_kardex_diario()
        self.conn.execute(
            "INSERT INTO kardex_diario (material_id, plant, fecha, salidas, saldo_fin_dia) VALUES "
            "('MAT-NORMAL', 'P1', '2026-07-20', 43.2, 60)"
        )
        self.conn.execute(
            """CREATE TABLE ventas_stats_mensuales (
                material_id TEXT, plant TEXT, anio_mes TEXT,
                suma_cantidad REAL, suma_importe_sin_iva REAL,
                num_tickets INTEGER, num_lineas INTEGER,
                max_linea REAL, max_ticket REAL, fecha_max_ticket TEXT
            )"""
        )
        # max_ticket=28.8 PIEZAS (no m2 -- ver comprasai_v6_reconciliacion.json)
        # el 2026-07-18 -- debe ganarle al pico de kardex (30 cajas) porque el
        # modo 'stats' tiene prioridad. suma_cantidad=57.6 iguala 1:1 el
        # cantidad_m2 de julio (57.6) para fijar el factor piezas->m2 de esta
        # línea en 1.0 y mantener el resultado en cajas redondas (20): así el
        # caso golden sigue probando la PRIORIDAD stats-vs-kardex sin mezclar
        # la conversión de unidades, que se prueba aparte.
        self.conn.execute(
            "INSERT INTO ventas_stats_mensuales "
            "(material_id, plant, anio_mes, suma_cantidad, max_ticket, fecha_max_ticket) VALUES "
            "('MAT-NORMAL', 'P1', '2026-07', 57.6, 28.8, '2026-07-18')"
        )
        self.conn.commit()
        dd = self._generar_datos_decision()
        ajuste_julio = next(a for a in dd["historia"]["promedio_3"]["ajustes"] if a["anio_mes"] == "2026-07")
        self.assertEqual(ajuste_julio["fuente"], "venta_mayor_transaccion")
        self.assertEqual(ajuste_julio["fecha_pico"], "2026-07-18")
        self.assertEqual(ajuste_julio["ajuste_cajas"], 20)
        self.assertEqual(ajuste_julio["valor_ajustado"], 20.0)  # 40 - 20

    def test_consumo_mes_referencia_se_corrige_con_stats_no_con_ventas_mensuales_parcial(self):
        # Mensaje puente 290066->291765 (17-sep-2026, decisión cerrada #2):
        # ventas_mensuales de 2026-08 (mes de referencia) viene PARCIAL --
        # aquí simulada en 14.4 m2 = 10 cajas, ~30% de las 40 cajas/mes reales
        # de MAT-NORMAL -- y debe descartarse a favor de
        # ventas_stats_mensuales.suma_cantidad, que sí trae el mes completo.
        self.conn.execute(
            "UPDATE ventas_mensuales SET cantidad_m2 = 14.4 "
            "WHERE material_id='MAT-NORMAL' AND anio_mes='2026-08'"
        )
        self.conn.execute(
            """CREATE TABLE ventas_stats_mensuales (
                material_id TEXT, plant TEXT, anio_mes TEXT,
                suma_cantidad REAL, suma_importe_sin_iva REAL,
                num_tickets INTEGER, num_lineas INTEGER,
                max_linea REAL, max_ticket REAL, fecha_max_ticket TEXT
            )"""
        )
        # Factor piezas->m2 de esta línea = 1.0 (meses previos: 57.6 m2 = 57.6
        # piezas). Agosto completo real = 57.6 piezas -> 57.6 m2 -> 40 cajas
        # (no las 10 que saldrían de la lectura parcial de ventas_mensuales).
        self.conn.execute(
            "INSERT INTO ventas_stats_mensuales "
            "(material_id, plant, anio_mes, suma_cantidad, num_tickets, num_lineas) VALUES "
            "('MAT-NORMAL', 'P1', '2026-04', 57.6, 1, 1), "
            "('MAT-NORMAL', 'P1', '2026-05', 57.6, 1, 1), "
            "('MAT-NORMAL', 'P1', '2026-06', 57.6, 1, 1), "
            "('MAT-NORMAL', 'P1', '2026-07', 57.6, 1, 1), "
            "('MAT-NORMAL', 'P1', '2026-08', 57.6, 1, 1)"
        )
        self.conn.commit()
        dd = self._generar_datos_decision()
        idx_agosto = dd["historia"]["meses"].index("2026-08")
        self.assertEqual(dd["historia"]["consumo"][idx_agosto], 40.0)
        self.assertNotEqual(dd["historia"]["consumo"][idx_agosto], 10.0)

    def test_mes_2026_09_nunca_entra_a_promedios(self):
        # Decisión cerrada #3 del mensaje puente: 2026-09 (mes en curso en
        # ventas_stats_mensuales) queda EXCLUIDO de todos los promedios --
        # el mes de referencia sigue siendo 2026-08 (MAX de ventas_mensuales).
        self.conn.execute(
            """CREATE TABLE ventas_stats_mensuales (
                material_id TEXT, plant TEXT, anio_mes TEXT,
                suma_cantidad REAL, suma_importe_sin_iva REAL,
                num_tickets INTEGER, num_lineas INTEGER,
                max_linea REAL, max_ticket REAL, fecha_max_ticket TEXT
            )"""
        )
        self.conn.execute(
            "INSERT INTO ventas_stats_mensuales (material_id, plant, anio_mes, suma_cantidad) VALUES "
            "('MAT-NORMAL', 'P1', '2026-09', 9999)"
        )
        self.conn.commit()
        dd = self._generar_datos_decision()
        self.assertNotIn("2026-09", dd["historia"]["meses"])
        self.assertEqual(dd["historia"]["meses"][-1], "2026-08")


class DrillDownEndpointsTests(unittest.TestCase):
    """backorder_detalle/pedidos_compra_detalle (dataset v5) deben degradar
    con gracia cuando la tabla opcional aún no existe."""

    def setUp(self):
        self.conn = _build_memory_db()

    def tearDown(self):
        self.conn.close()

    def test_backorder_detalle_sin_tabla_responde_no_disponible(self):
        resp = backorder_detalle(material_id="MAT-NORMAL", plant="P1", db=self.conn)
        self.assertFalse(resp["disponible"])
        self.assertEqual(resp["documentos"], [])

    def test_pedidos_detalle_sin_tabla_responde_no_disponible(self):
        resp = pedidos_detalle(material_id="MAT-NORMAL", plant="P1", db=self.conn)
        self.assertFalse(resp["disponible"])
        self.assertEqual(resp["pedidos"], [])

    def test_backorder_detalle_con_tabla_regresa_documentos(self):
        self.conn.execute(
            """CREATE TABLE backorder_detalle (
                material_id TEXT, plant TEXT, documento TEXT, posicion TEXT,
                cliente TEXT, cantidad_pendiente REAL,
                fecha_documento TEXT, fecha_entrega_comprometida TEXT
            )"""
        )
        self.conn.execute(
            "INSERT INTO backorder_detalle VALUES "
            "('MAT-NORMAL', 'P1', 'DOC1', '10', 'Cliente X', 30, '2026-08-01', '2026-08-15')"
        )
        self.conn.commit()
        resp = backorder_detalle(material_id="MAT-NORMAL", plant="P1", db=self.conn)
        self.assertTrue(resp["disponible"])
        self.assertEqual(len(resp["documentos"]), 1)
        self.assertEqual(resp["documentos"][0]["documento"], "DOC1")

    def test_pedidos_detalle_con_tabla_regresa_pedidos(self):
        self.conn.execute(
            """CREATE TABLE pedidos_compra_detalle (
                material_id TEXT, plant TEXT, po TEXT, posicion TEXT,
                proveedor TEXT, cantidad_pendiente REAL,
                fecha_po TEXT, fecha_entrega_estimada TEXT
            )"""
        )
        self.conn.execute(
            "INSERT INTO pedidos_compra_detalle VALUES "
            "('MAT-NORMAL', 'P1', 'PO1', '20', 'Proveedor Uno', 50, '2026-08-01', '2026-08-20')"
        )
        self.conn.commit()
        resp = pedidos_detalle(material_id="MAT-NORMAL", plant="P1", db=self.conn)
        self.assertTrue(resp["disponible"])
        self.assertEqual(len(resp["pedidos"]), 1)
        self.assertEqual(resp["pedidos"][0]["po"], "PO1")


if __name__ == "__main__":
    unittest.main()
