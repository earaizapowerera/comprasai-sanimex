"""Tests para Lotes de Compra (waykee 292251).

Cubre:
  - clasificaciones_vigentes: unión de lotes activos que cubren la fecha;
    None (= no filtrar) si no hay lote vigente; bordes del rango inclusivos;
    lotes inactivos o fuera de vigencia no aplican.
  - init_tables: seed de UNA clasificación PET (la más frecuente del último
    mes) solo al crear la tabla.
  - generar_sugeridos: con lote activo filtra por la categoría del mes de la
    fecha; sin lote no cambia el resultado; lote fuera de vigencia no aplica.

Ejecutar:
    cd backend && python3 -m unittest tests.test_lotes_compra -v
"""

import sqlite3
import sys
import unittest
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.routers.engines import lotes_compra  # noqa: E402
from app.routers.engines.lotes_compra import (  # noqa: E402
    clasificaciones_vigentes,
    filtrar_por_lote,
    material_en_lote,
)
from app.routers.engines.sugeridos import generar_sugeridos  # noqa: E402

SCHEMA_PATH = BACKEND_DIR / "app" / "core" / "schema.sql"


def _lote(ini, fin, clasifs, activo=True):
    return {"fecha_inicio": ini, "fecha_fin": fin, "activo": activo, "clasificaciones": clasifs}


class ClasificacionesVigentesTests(unittest.TestCase):
    def test_sin_lotes_no_filtra(self):
        self.assertIsNone(clasificaciones_vigentes([], "2026-09-24"))

    def test_lote_activo_que_cubre_la_fecha(self):
        lotes = [_lote("2026-09-01", "2026-09-30", ["PET52"])]
        self.assertEqual(clasificaciones_vigentes(lotes, "2026-09-24"), {"PET52"})

    def test_bordes_inclusivos(self):
        lotes = [_lote("2026-09-01", "2026-09-30", ["PET52"])]
        self.assertEqual(clasificaciones_vigentes(lotes, "2026-09-01"), {"PET52"})
        self.assertEqual(clasificaciones_vigentes(lotes, "2026-09-30"), {"PET52"})

    def test_fuera_de_vigencia_no_aplica(self):
        lotes = [_lote("2026-08-01", "2026-08-31", ["PET52"])]
        self.assertIsNone(clasificaciones_vigentes(lotes, "2026-09-24"))

    def test_lote_inactivo_no_aplica(self):
        lotes = [_lote("2026-09-01", "2026-09-30", ["PET52"], activo=False)]
        self.assertIsNone(clasificaciones_vigentes(lotes, "2026-09-24"))

    def test_union_de_lotes_traslapados(self):
        lotes = [
            _lote("2026-09-01", "2026-09-30", ["PET52"]),
            _lote("2026-09-15", "2026-10-15", ["REM", "OUTLET01"]),
            _lote("2026-10-01", "2026-10-31", ["2DAS"]),
        ]
        self.assertEqual(clasificaciones_vigentes(lotes, "2026-09-20"), {"PET52", "REM", "OUTLET01"})

    def test_lote_vigente_sin_clasificaciones_excluye_todo(self):
        # Rango vigente pero vacío: el planeador dijo "este mes no se compra nada".
        lotes = [_lote("2026-09-01", "2026-09-30", [])]
        self.assertEqual(clasificaciones_vigentes(lotes, "2026-09-24"), set())
        self.assertFalse(material_en_lote("PET52", set()))


class FiltrarPorLoteTests(unittest.TestCase):
    def test_none_devuelve_todo(self):
        filas = [{"material_id": "A"}, {"material_id": "B"}]
        self.assertEqual(filtrar_por_lote(filas, None, lambda m: None), filas)

    def test_material_sin_categoria_queda_fuera(self):
        cats = {"A": "PET52", "B": None, "C": "REM"}
        filas = [{"material_id": m} for m in cats]
        out = filtrar_por_lote(filas, {"PET52"}, cats.get)
        self.assertEqual([f["material_id"] for f in out], ["A"])


class InitTablesSeedTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
        self.conn.execute("CREATE TABLE categorias_mensuales (material_id TEXT, anio_mes TEXT, categoria TEXT)")
        self.conn.executemany(
            "INSERT INTO categorias_mensuales VALUES (?, ?, ?)",
            # PET50 domina la historia, pero en el último mes (07) la vigente es PET52.
            [(f"M{i}", "2026-06", "PET50") for i in range(10)]
            + [(f"M{i}", "2026-07", "PET52") for i in range(3)]
            + [("X", "2026-07", "PET53"), ("Y", "2026-07", "REM"), ("Z", "2026-07", "REM"), ("W", "2026-07", "REM")],
        )

    def tearDown(self):
        self.conn.close()

    def test_seed_pet_mas_frecuente_del_ultimo_mes(self):
        lotes_compra.init_tables(self.conn)
        lotes = lotes_compra.cargar_lotes(self.conn)
        self.assertEqual(len(lotes), 1)
        self.assertEqual(lotes[0]["clasificaciones"], ["PET52"])
        hoy = date.today()
        self.assertEqual(lotes[0]["fecha_inicio"], hoy.replace(day=1).isoformat())
        self.assertTrue(lotes[0]["fecha_fin"].startswith(hoy.strftime("%Y-%m")))

    def test_seed_no_resucita_si_el_usuario_borro_todo(self):
        lotes_compra.init_tables(self.conn)
        self.conn.execute("DELETE FROM lotes_compra_clasificacion")
        self.conn.execute("DELETE FROM lotes_compra")
        lotes_compra.init_tables(self.conn)
        self.assertEqual(lotes_compra.cargar_lotes(self.conn), [])


class GenerarSugeridosConLoteTests(unittest.TestCase):
    """Dos materiales iguales en demanda; solo cambia su categoría."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_PATH.read_text())
        self.conn.execute(
            "INSERT INTO sucursales (plant, nombre, organizacion, canal) VALUES ('P1', 'Sucursal 1', 'GAM', 'Menudeo')"
        )
        for mat in ("MAT-PET", "MAT-REM", "MAT-SINCAT"):
            self.conn.execute(
                "INSERT INTO materiales (material_id, descripcion, familia, abc, m2_por_caja, costo) "
                "VALUES (?, ?, 'F1', 'A', 1.44, 15)", [mat, mat]
            )
            self.conn.execute(
                "INSERT INTO inventarios (material_id, plant, disponible, transito, comprometido) "
                "VALUES (?, 'P1', 10, 0, 5)", [mat]
            )
            self.conn.execute(
                "INSERT INTO proveedores (material_id, proveedor, lead_time_dias, moq_cajas, cajas_por_pallet) "
                "VALUES (?, 'Proveedor Uno', 10, 20, 40)", [mat]
            )
            for mes in ("2026-04", "2026-05", "2026-06", "2026-07", "2026-08"):
                self.conn.execute(
                    "INSERT INTO ventas_mensuales (material_id, plant, canal, anio_mes, cantidad_m2, importe) "
                    "VALUES (?, 'P1', 'Menudeo', ?, 57.6, 0)", [mat, mes]
                )
        self.conn.execute(
            "CREATE TABLE categorias_mensuales (material_id TEXT, anio_mes TEXT, categoria TEXT, "
            "PRIMARY KEY (material_id, anio_mes))"
        )
        # MAT-PET cambia de clase: REM en 07 -> PET52 en 09. MAT-REM siempre REM.
        self.conn.executemany(
            "INSERT INTO categorias_mensuales VALUES (?, ?, ?)",
            [("MAT-PET", "2026-07", "REM"), ("MAT-PET", "2026-09", "PET52"), ("MAT-REM", "2026-07", "REM")],
        )
        self.conn.commit()
        lotes_compra.init_tables(self.conn)
        # init_tables siembra un lote PET del mes actual; lo quitamos para que
        # cada test controle exactamente sus lotes.
        self.conn.execute("DELETE FROM lotes_compra_clasificacion")
        self.conn.execute("DELETE FROM lotes_compra")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _generar(self, fecha):
        return generar_sugeridos(
            familia=None, proveedor=None, corredor=None, plant=None, abc=None,
            solo_criticos=False, page=1, page_size=50, fecha=fecha, db=self.conn,
        )

    def _crear_lote(self, ini, fin, clasifs, activo=True):
        lotes_compra._crear_lote(self.conn, "t", ini, fin, activo, clasifs, "test")
        self.conn.commit()

    @staticmethod
    def _mats(res):
        return sorted({it["material_id"] for it in res["items"]})

    def test_sin_lote_no_filtra(self):
        res = self._generar(date(2026, 9, 24))
        self.assertEqual(self._mats(res), ["MAT-PET", "MAT-REM", "MAT-SINCAT"])
        self.assertFalse(res["lote"]["aplicado"])

    def test_lote_activo_filtra_por_categoria_del_mes_de_la_fecha(self):
        self._crear_lote("2026-09-01", "2026-09-30", ["PET52"])
        res = self._generar(date(2026, 9, 24))
        self.assertEqual(self._mats(res), ["MAT-PET"])
        self.assertTrue(res["lote"]["aplicado"])
        self.assertEqual(res["lote"]["clasificaciones"], ["PET52"])
        self.assertEqual(res["lote"]["lineas_excluidas"], 2)

    def test_categoria_vigente_depende_del_mes(self):
        # En julio MAT-PET era REM: un lote REM de julio toma MAT-PET y MAT-REM.
        self._crear_lote("2026-07-01", "2026-07-31", ["REM"])
        res = self._generar(date(2026, 7, 15))
        self.assertEqual(self._mats(res), ["MAT-PET", "MAT-REM"])

    def test_lote_fuera_de_vigencia_no_aplica(self):
        self._crear_lote("2026-08-01", "2026-08-31", ["PET52"])
        res = self._generar(date(2026, 9, 24))
        self.assertEqual(self._mats(res), ["MAT-PET", "MAT-REM", "MAT-SINCAT"])
        self.assertFalse(res["lote"]["aplicado"])

    def test_lote_inactivo_no_aplica(self):
        self._crear_lote("2026-09-01", "2026-09-30", ["PET52"], activo=False)
        res = self._generar(date(2026, 9, 24))
        self.assertFalse(res["lote"]["aplicado"])
        self.assertEqual(len(self._mats(res)), 3)

    def test_lote_sin_coincidencias_devuelve_vacio(self):
        self._crear_lote("2026-09-01", "2026-09-30", ["OUTLET01"])
        res = self._generar(date(2026, 9, 24))
        self.assertEqual(res["total"], 0)
        self.assertTrue(res["lote"]["aplicado"])


if __name__ == "__main__":
    unittest.main()
