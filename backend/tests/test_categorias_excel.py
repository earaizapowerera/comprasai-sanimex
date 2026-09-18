"""Tests para T29 (punto 5, waykee 291788): categoría mensual por material.

Cubre:
  - serial_a_anio_mes / leer_categorias (data/load_categorias_excel.py): la
    conversión de serial de fecha de Excel y el parseo columna-por-mes.
  - insertar_fill_gaps: nunca pisa una pareja (material_id, anio_mes) que ya
    exista (p.ej. sembrada por la tabla oficial v7/HANA).
  - _cargar_categorias_tabla / _categoria_para_linea (engines/sugeridos.py):
    resolución exacta / <= mes_ref / fallback al último mes con dato.
  - generar_sugeridos: dd["categoria"] expuesto en el payload de /generar.

Ejecutar:
    cd backend && python3 -m unittest tests.test_categorias_excel -v
"""

import sqlite3
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from data.load_categorias_excel import insertar_fill_gaps, serial_a_anio_mes  # noqa: E402
from app.routers.engines.sugeridos import (  # noqa: E402
    _cargar_categorias_tabla,
    _categoria_para_linea,
    generar_sugeridos,
)

SCHEMA_PATH = BACKEND_DIR / "app" / "core" / "schema.sql"


class SerialAAnioMesTests(unittest.TestCase):
    def test_serial_ejemplo_puente_290066(self):
        # Valores literales del mensaje puente: col9=45658.0 -> 2025-01-01,
        # col28=46235.0 -> 2026-08-01.
        self.assertEqual(serial_a_anio_mes(45658.0), "2025-01")
        self.assertEqual(serial_a_anio_mes(46235.0), "2026-08")

    def test_serial_acepta_float_o_int(self):
        self.assertEqual(serial_a_anio_mes(45658), serial_a_anio_mes(45658.0))


class InsertarFillGapsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_inserta_en_tabla_vacia(self):
        antes, despues = insertar_fill_gaps(
            self.conn,
            [("G16-18-1-50", "2025-01", "PM3"), ("G16-18-1-50", "2025-02", "PM3")],
        )
        self.assertEqual((antes, despues), (0, 2))
        rows = self.conn.execute("SELECT * FROM categorias_mensuales ORDER BY anio_mes").fetchall()
        self.assertEqual(rows, [("G16-18-1-50", "2025-01", "PM3"), ("G16-18-1-50", "2025-02", "PM3")])

    def test_no_pisa_fila_v7_ya_existente(self):
        # Simula que la tabla oficial v7/HANA ya sembró 2026-01 con 'HANA-CAT'.
        self.conn.execute(
            "CREATE TABLE categorias_mensuales (material_id TEXT, anio_mes TEXT, categoria TEXT, "
            "PRIMARY KEY (material_id, anio_mes))"
        )
        self.conn.execute(
            "INSERT INTO categorias_mensuales VALUES ('G16-18-1-50', '2026-01', 'HANA-CAT')"
        )
        self.conn.commit()

        antes, despues = insertar_fill_gaps(
            self.conn,
            [("G16-18-1-50", "2026-01", "PM3"), ("G16-18-1-50", "2026-08", "PET53")],
        )
        self.assertEqual(antes, 1)
        self.assertEqual(despues, 2)  # solo se agregó 2026-08; 2026-01 se descartó
        valor_2026_01 = self.conn.execute(
            "SELECT categoria FROM categorias_mensuales WHERE material_id='G16-18-1-50' AND anio_mes='2026-01'"
        ).fetchone()[0]
        self.assertEqual(valor_2026_01, "HANA-CAT")  # nunca se pisó


class CategoriaParaLineaTests(unittest.TestCase):
    def test_match_exacto_en_mes_ref(self):
        tabla = {"MAT1": [("2026-07", "PM3"), ("2026-08", "PET53")]}
        self.assertEqual(
            _categoria_para_linea(tabla, "MAT1", "2026-08"),
            {"valor": "PET53", "anio_mes": "2026-08"},
        )

    def test_fallback_al_mes_anterior_mas_reciente(self):
        # No hay dato para 2026-08 -- usa el más reciente <= mes_ref (2026-06).
        tabla = {"MAT1": [("2026-05", "PM3"), ("2026-06", "PEM4")]}
        self.assertEqual(
            _categoria_para_linea(tabla, "MAT1", "2026-08"),
            {"valor": "PEM4", "anio_mes": "2026-06"},
        )

    def test_fallback_al_ultimo_mes_con_dato_si_no_hay_anteriores(self):
        # Todo el histórico es POSTERIOR al mes_ref -- fallback pedido por el
        # PM: usar el más reciente disponible aunque sea posterior.
        tabla = {"MAT1": [("2026-09", "PM3"), ("2026-10", "PET53")]}
        self.assertEqual(
            _categoria_para_linea(tabla, "MAT1", "2026-08"),
            {"valor": "PET53", "anio_mes": "2026-10"},
        )

    def test_sin_datos_regresa_none(self):
        self.assertIsNone(_categoria_para_linea({}, "MAT1", "2026-08"))
        self.assertIsNone(_categoria_para_linea({"OTRO": [("2026-08", "X")]}, "MAT1", "2026-08"))


class CargarCategoriasTablaTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            "CREATE TABLE categorias_mensuales (material_id TEXT, anio_mes TEXT, categoria TEXT, "
            "PRIMARY KEY (material_id, anio_mes))"
        )
        self.conn.execute(
            "INSERT INTO categorias_mensuales VALUES "
            "('MAT1', '2026-01', 'PM3'), ('MAT1', '2026-02', 'PEM4'), ('MAT2', '2026-01', 'NETOS21')"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_agrupa_por_material_ordenado(self):
        tabla = _cargar_categorias_tabla(self.conn, ["MAT1", "MAT2"], "?,?")
        self.assertEqual(tabla["MAT1"], [("2026-01", "PM3"), ("2026-02", "PEM4")])
        self.assertEqual(tabla["MAT2"], [("2026-01", "NETOS21")])

    def test_lista_vacia_no_consulta(self):
        self.assertEqual(_cargar_categorias_tabla(self.conn, [], ""), {})


class GenerarSugeridosCategoriaIntegrationTests(unittest.TestCase):
    """dd["categoria"] debe viajar end-to-end en /engines/sugeridos/generar."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_PATH.read_text())
        self.conn.execute(
            "INSERT INTO materiales (material_id, descripcion, familia, abc, m2_por_caja, costo) "
            "VALUES ('MAT-NORMAL', 'Normal', 'F1', 'A', 1.44, 15)"
        )
        self.conn.execute(
            "INSERT INTO sucursales (plant, nombre, organizacion, canal) VALUES "
            "('P1', 'Sucursal 1', 'GAM', 'Menudeo')"
        )
        self.conn.execute(
            "INSERT INTO inventarios (material_id, plant, disponible, transito, comprometido) VALUES "
            "('MAT-NORMAL', 'P1', 100, 0, 50)"
        )
        self.conn.execute(
            "INSERT INTO coberturas_objetivo (material_id, meses_objetivo) VALUES ('MAT-NORMAL', 2.0)"
        )
        self.conn.execute(
            "INSERT INTO proveedores (material_id, proveedor, lead_time_dias, moq_cajas, cajas_por_pallet) "
            "VALUES ('MAT-NORMAL', 'Proveedor Uno', 10, 20, 40)"
        )
        self.conn.execute(
            "INSERT INTO ventas_mensuales (material_id, plant, canal, anio_mes, cantidad_m2, importe) VALUES "
            "('MAT-NORMAL', 'P1', 'Menudeo', '2026-04', 57.6, 0), "
            "('MAT-NORMAL', 'P1', 'Menudeo', '2026-05', 57.6, 0), "
            "('MAT-NORMAL', 'P1', 'Menudeo', '2026-06', 57.6, 0), "
            "('MAT-NORMAL', 'P1', 'Menudeo', '2026-07', 57.6, 0), "
            "('MAT-NORMAL', 'P1', 'Menudeo', '2026-08', 57.6, 0)"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _generar(self):
        return generar_sugeridos(
            familia=None, proveedor=None, corredor=None, plant=None, abc=None,
            solo_criticos=False, page=1, page_size=50, db=self.conn,
        )

    def test_sin_categorias_mensuales_dd_categoria_es_none(self):
        it = self._generar()["items"][0]
        self.assertIsNone(it["datos_decision"]["categoria"])

    def test_con_categoria_exacta_en_mes_ref(self):
        # mes_ref = MAX(anio_mes) en ventas_mensuales = '2026-08' (ver setUp).
        # La tabla la crea normalmente _ensure_tables (IF NOT EXISTS); en el
        # test la creamos a mano ANTES de poblarla, igual que el patrón ya
        # usado para dias_sin_inventario_mensual en
        # test_sugeridos_datos_decision.py.
        self.conn.execute(
            "CREATE TABLE categorias_mensuales (material_id TEXT, anio_mes TEXT, categoria TEXT, "
            "PRIMARY KEY (material_id, anio_mes))"
        )
        self.conn.execute(
            "INSERT INTO categorias_mensuales (material_id, anio_mes, categoria) VALUES "
            "('MAT-NORMAL', '2026-07', 'PEM4'), ('MAT-NORMAL', '2026-08', 'PET53')"
        )
        self.conn.commit()
        it = self._generar()["items"][0]
        self.assertEqual(it["datos_decision"]["categoria"], {"valor": "PET53", "anio_mes": "2026-08"})

    def test_fallback_al_ultimo_mes_con_dato_cuando_no_hay_mes_ref(self):
        self.conn.execute(
            "CREATE TABLE categorias_mensuales (material_id TEXT, anio_mes TEXT, categoria TEXT, "
            "PRIMARY KEY (material_id, anio_mes))"
        )
        self.conn.execute(
            "INSERT INTO categorias_mensuales (material_id, anio_mes, categoria) VALUES "
            "('MAT-NORMAL', '2026-05', 'PM3')"
        )
        self.conn.commit()
        it = self._generar()["items"][0]
        self.assertEqual(it["datos_decision"]["categoria"], {"valor": "PM3", "anio_mes": "2026-05"})


if __name__ == "__main__":
    unittest.main()
