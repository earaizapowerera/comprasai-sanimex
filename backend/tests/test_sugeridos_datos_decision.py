"""Tests para T19 (waykee 290116): la explicación de cada sugerido en
engines/sugeridos.py dejó de mostrar pesos hardcodeados ("factores":
40/25/15/10/10 sin ningún cálculo detrás) y ahora expone `datos_decision`
con los inputs REALES de la fórmula (serie de demanda, desglose de
inventario, cobertura/objetivo/faltante, datos del proveedor y el motivo
real del redondeo MOQ/pallet).

Cubre:
  - calc_motivo_redondeo: texto determinista según qué redondeo se aplicó.
  - build_datos_decision: arma el payload completo a partir de inputs puros.
  - generar_sugeridos (integración, DB en memoria): el payload de /generar
    trae `datos_decision` (ya no `factores`) y detecta "sobrevendido" cuando
    disponible_neto < 0 (comprometido excede stock).
  - lista_sugeridos: lo persistido en sugeridos_generados se recupera vía
    datos_decision_json, no vía la columna muerta factores_json.

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
    build_datos_decision,
    calc_motivo_redondeo,
    generar_sugeridos,
    lista_sugeridos,
)

SCHEMA_PATH = BACKEND_DIR / "app" / "core" / "schema.sql"


class CalcMotivoRedondeoTests(unittest.TestCase):
    def test_sin_compra_por_transferencia(self):
        self.assertIn("transferencia", calc_motivo_redondeo(0, 0, 0, moq=20, cajas_por_pallet=40))

    def test_sube_a_moq(self):
        # G7 (casos golden T9): need=8, MOQ=20 -> 20.
        motivo = calc_motivo_redondeo(bruta=8, tras_moq=20, final=20, moq=20, cajas_por_pallet=40)
        self.assertIn("MOQ", motivo)
        self.assertIn("20", motivo)

    def test_sube_a_pallet(self):
        motivo = calc_motivo_redondeo(bruta=45, tras_moq=45, final=80, moq=20, cajas_por_pallet=40)
        self.assertIn("pallet", motivo)
        self.assertIn("80", motivo)

    def test_sin_ajuste(self):
        motivo = calc_motivo_redondeo(bruta=30, tras_moq=30, final=30, moq=20, cajas_por_pallet=40)
        self.assertIn("Sin ajuste", motivo)


class BuildDatosDecisionTests(unittest.TestCase):
    def _base_kwargs(self, **overrides):
        kwargs = dict(
            serie_pts=[("2026-06", 40.0), ("2026-07", 40.0), ("2026-08", 40.0)],
            demanda_promedio_3m=40.0,
            meses_con_venta=3,
            meses_historia=6,
            disponible=100.0,
            transito=0.0,
            comprometido=50.0,
            disponible_neto=50.0,
            cobertura_actual=1.25,
            meses_objetivo=2.0,
            faltante_bruto=30.0,
            proveedor="Proveedor Uno",
            moq_cajas=20,
            cajas_por_pallet=40,
            lead_time_dias=10,
            m2_por_caja=1.44,
            costo_unitario=15.0,
            cantidad_transferir=0.0,
            detalle_transferencias=[],
            cantidad_comprar_bruta=30.0,
            cantidad_tras_moq=30.0,
            cantidad_final=30.0,
        )
        kwargs.update(overrides)
        return kwargs

    def test_no_inventa_numeros_todo_es_trazable(self):
        dd = build_datos_decision(**self._base_kwargs())
        self.assertEqual(dd["demanda_promedio_3m"], 40.0)
        self.assertEqual(dd["inventario"]["disponible"], 100.0)
        self.assertEqual(dd["inventario"]["comprometido"], 50.0)
        self.assertEqual(dd["inventario"]["disponible_neto"], 50.0)
        self.assertFalse(dd["inventario"]["sobrevendido"])
        self.assertEqual(dd["proveedor"]["nombre"], "Proveedor Uno")
        self.assertEqual(dd["proveedor"]["lead_time_dias"], 10)
        self.assertEqual(len(dd["serie_demanda"]), 3)
        self.assertEqual(dd["serie_demanda"][0], {"anio_mes": "2026-06", "cajas": 40.0})

    def test_sobrevendido_cuando_disponible_neto_negativo(self):
        dd = build_datos_decision(**self._base_kwargs(
            disponible=10.0, comprometido=50.0, disponible_neto=-40.0,
        ))
        self.assertTrue(dd["inventario"]["sobrevendido"])
        self.assertEqual(dd["inventario"]["disponible_neto"], -40.0)

    def test_cobertura_none_se_preserva(self):
        dd = build_datos_decision(**self._base_kwargs(cobertura_actual=None))
        self.assertIsNone(dd["cobertura_actual"])

    def test_transferencia_y_redondeo_expuestos(self):
        detalle = [{"desde_plant": "P2", "cantidad": 15.0}]
        dd = build_datos_decision(**self._base_kwargs(
            cantidad_transferir=15.0, detalle_transferencias=detalle,
            cantidad_comprar_bruta=15.0, cantidad_tras_moq=20.0, cantidad_final=20.0,
        ))
        self.assertEqual(dd["transferencia"]["cantidad_transferir"], 15.0)
        self.assertEqual(dd["transferencia"]["detalle_transferencias"], detalle)
        self.assertEqual(dd["redondeo"]["cantidad_final"], 20.0)
        self.assertIn("MOQ", dd["redondeo"]["motivo"])


def _build_memory_db():
    """DB SQLite en memoria (esquema real) con dos pares material-plant:
    MAT-NORMAL (caso típico, disponible_neto positivo) y MAT-SOBREVENDIDO
    (comprometido > disponible + tránsito -> disponible_neto negativo, el
    hallazgo que T19 pide exponer como "Sobrevendido")."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = lambda cursor, row: dict(zip([c[0] for c in cursor.description], row))
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
    # MAT-NORMAL: demanda 40 cajas/mes x 3 meses -> disponible_neto(50)/40 = 1.25 < objetivo(2.0).
    # MAT-SOBREVENDIDO: demanda 20 cajas/mes x 3 meses -> disponible_neto=-40 (comprometido excede stock).
    conn.execute(
        "INSERT INTO ventas_mensuales (material_id, plant, canal, anio_mes, cantidad_m2, importe) VALUES "
        "('MAT-NORMAL', 'P1', 'Menudeo', '2026-06', 57.6, 0), "
        "('MAT-NORMAL', 'P1', 'Menudeo', '2026-07', 57.6, 0), "
        "('MAT-NORMAL', 'P1', 'Menudeo', '2026-08', 57.6, 0), "
        "('MAT-SOBREVENDIDO', 'P1', 'Menudeo', '2026-06', 28.8, 0), "
        "('MAT-SOBREVENDIDO', 'P1', 'Menudeo', '2026-07', 28.8, 0), "
        "('MAT-SOBREVENDIDO', 'P1', 'Menudeo', '2026-08', 28.8, 0)"
    )
    conn.commit()
    return conn


class GenerarSugeridosDatosDecisionIntegrationTests(unittest.TestCase):
    """/api/engines/sugeridos/generar ya no debe traer 'factores' (pesos
    inventados) y sí debe traer 'datos_decision' con los inputs reales."""

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
        self.assertEqual(len(dd["serie_demanda"]), 3)
        self.assertAlmostEqual(dd["demanda_promedio_3m"], 40.0, places=1)
        self.assertEqual(dd["inventario"]["disponible"], 100)
        self.assertEqual(dd["inventario"]["comprometido"], 50)
        self.assertAlmostEqual(dd["inventario"]["disponible_neto"], 50.0, places=1)
        self.assertFalse(dd["inventario"]["sobrevendido"])
        self.assertEqual(dd["proveedor"]["nombre"], "Proveedor Uno")
        self.assertEqual(dd["proveedor"]["moq_cajas"], 20)
        self.assertEqual(dd["proveedor"]["cajas_por_pallet"], 40)
        self.assertEqual(dd["proveedor"]["lead_time_dias"], 10)
        self.assertIsInstance(dd["redondeo"]["motivo"], str)
        self.assertGreater(len(dd["redondeo"]["motivo"]), 0)

    def test_mat_sobrevendido_marca_disponible_neto_negativo(self):
        it = self._items_by_material()["MAT-SOBREVENDIDO"]
        dd = it["datos_decision"]
        self.assertTrue(dd["inventario"]["sobrevendido"])
        self.assertLess(dd["inventario"]["disponible_neto"], 0)
        self.assertAlmostEqual(dd["inventario"]["disponible_neto"], -40.0, places=1)


class ListaSugeridosDatosDecisionIntegrationTests(unittest.TestCase):
    """/api/engines/sugeridos/lista debe reconstruir datos_decision desde la
    columna persistida datos_decision_json, no desde factores_json."""

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


if __name__ == "__main__":
    unittest.main()
