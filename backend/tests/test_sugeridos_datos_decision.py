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
    backorder_detalle,
    build_datos_decision,
    calc_motivo_redondeo,
    generar_sugeridos,
    lista_sugeridos,
    pedidos_detalle,
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
        # T25 (waykee 290148): con 3 puntos y meses_demanda=3 (default), TODOS
        # entran al promedio corto -> incluido_promedio_3m=True en los 3.
        self.assertEqual(
            dd["serie_demanda"][0],
            {"anio_mes": "2026-06", "cajas": 40.0, "incluido_promedio_3m": True},
        )
        self.assertTrue(all(p["incluido_promedio_3m"] for p in dd["serie_demanda"]))

    def test_incluido_promedio_3m_solo_marca_los_ultimos_n(self):
        # 5 meses de historia, meses_demanda=3 -> solo los últimos 3 marcados.
        dd = build_datos_decision(**self._base_kwargs(
            serie_pts=[
                ("2026-04", 10.0), ("2026-05", 20.0), ("2026-06", 40.0),
                ("2026-07", 40.0), ("2026-08", 40.0),
            ],
            meses_demanda=3,
        ))
        incluidos = [p["anio_mes"] for p in dd["serie_demanda"] if p["incluido_promedio_3m"]]
        self.assertEqual(incluidos, ["2026-06", "2026-07", "2026-08"])

    def test_meses_excluidos_desabasto_placeholder_vacio(self):
        # T21 (umbral de desabasto) todavía no aterriza -- el campo queda
        # reservado y vacío para no romper el contrato del frontend.
        dd = build_datos_decision(**self._base_kwargs())
        self.assertEqual(dd["meses_excluidos_desabasto"], [])

    def test_inventario_fin_mes_sin_kardex_queda_en_none(self):
        dd = build_datos_decision(**self._base_kwargs())
        self.assertFalse(dd["kardex_disponible"])
        self.assertEqual(
            dd["inventario_fin_mes"],
            [
                {"anio_mes": "2026-06", "saldo": None},
                {"anio_mes": "2026-07", "saldo": None},
                {"anio_mes": "2026-08", "saldo": None},
            ],
        )

    def test_inventario_fin_mes_con_kardex_expone_saldo_por_mes(self):
        dd = build_datos_decision(**self._base_kwargs(
            inventario_fin_mes={"2026-06": 120.0, "2026-07": 100.0, "2026-08": 80.0},
            kardex_disponible=True,
        ))
        self.assertTrue(dd["kardex_disponible"])
        por_mes = {p["anio_mes"]: p["saldo"] for p in dd["inventario_fin_mes"]}
        self.assertEqual(por_mes, {"2026-06": 120.0, "2026-07": 100.0, "2026-08": 80.0})

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


class KardexDiarioIntegrationTests(unittest.TestCase):
    """T25 (waykee 290148): kardex_diario NO existe en el dataset actual
    (verificado: la tabla solo vive en un script sin correr en la rama
    huérfana bot/290120-kardex) -- generar_sugeridos debe degradar con
    gracia (kardex_disponible=False, saldo None por mes) cuando falta, y usar
    el saldo real (arrastrado del último movimiento <= fin de mes) cuando sí
    está poblada."""

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

    def test_sin_tabla_kardex_diario_marca_no_disponible(self):
        dd = self._generar_datos_decision()
        self.assertFalse(dd["kardex_disponible"])
        self.assertEqual(len(dd["inventario_fin_mes"]), len(dd["serie_demanda"]))
        self.assertTrue(all(p["saldo"] is None for p in dd["inventario_fin_mes"]))

    def test_con_kardex_diario_poblado_arrastra_saldo_de_fin_de_mes(self):
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


class DrillDownEndpointsTests(unittest.TestCase):
    """T25 (waykee 290148): endpoints de detalle de backorder/pedidos por
    cumplir -- backorder_detalle/pedidos_compra_detalle (dataset v5, waykee
    290147) todavía las extrae el Data Expert; deben degradar con gracia."""

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
