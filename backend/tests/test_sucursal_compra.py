"""Tests del catálogo sucursal_compra (waykee 292252).

Cubre:
  - clasificar: bordes del umbral, 0 OCs con/sin inventario, sin evidencia.
  - recalcular: evidencia vacía -> todo SIN_EVIDENCIA (sin filtro); override
    manda sobre la calculada; cambiar el umbral reclasifica.
  - generar_sugeridos: solo sucursales COMPRA_DIRECTA generan líneas.
  - Balanceos: SIN_OPERACION sale del universo; NO_COMPRA se queda.

Ejecutar:
    cd backend && python3 -m unittest tests.test_sucursal_compra -v
"""

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core import sucursal_compra as sc  # noqa: E402
from app.routers.engines import balanceos, lotes_compra  # noqa: E402
from app.routers.engines.sugeridos import generar_sugeridos  # noqa: E402

SCHEMA_PATH = BACKEND_DIR / "app" / "core" / "schema.sql"
PLANTAS = ("DIR", "ESP", "NOC", "SOP")


def _evidencia(plant, oc12):
    return {"plant": plant, "oc_ext_12m": oc12, "lineas_12m": oc12, "proveedores_12m": 1, "ult_oc_ext": None,
            "oc_ext_24m": oc12, "traslados_12m": 5, "ventana_desde": None, "ventana_hasta": None, "extraido": None}


class ClasificarTests(unittest.TestCase):
    def test_umbral_y_bordes(self):
        self.assertEqual(sc.clasificar(12, 0), sc.COMPRA_DIRECTA)
        self.assertEqual(sc.clasificar(11, 50), sc.COMPRA_ESPORADICA)
        self.assertEqual(sc.clasificar(1, 0), sc.COMPRA_ESPORADICA)
        self.assertEqual(sc.clasificar(0, 3), sc.NO_COMPRA)
        self.assertEqual(sc.clasificar(0, 0), sc.SIN_OPERACION)
        self.assertEqual(sc.clasificar(None, 10), sc.SIN_EVIDENCIA)

    def test_umbral_configurable(self):
        self.assertEqual(sc.clasificar(6, 0, umbral=6), sc.COMPRA_DIRECTA)
        self.assertEqual(sc.clasificar(12, 0, umbral=24), sc.COMPRA_ESPORADICA)


class _BaseDB(unittest.TestCase):
    """Cuatro sucursales en el mismo corredor, un material. SOP sin inventario."""

    def setUp(self):
        self._csv = mock.patch.object(sc, "CSV_EVIDENCIA", Path("/no/existe.csv"))
        self._csv.start()
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_PATH.read_text())
        self.conn.execute("INSERT INTO materiales (material_id, descripcion, familia, abc, m2_por_caja, costo) "
                          "VALUES ('MAT', 'MAT', 'F1', 'A', 1.44, 15)")
        self.conn.execute("INSERT INTO proveedores (material_id, proveedor, lead_time_dias, moq_cajas, cajas_por_pallet) "
                          "VALUES ('MAT', 'Prov', 10, 20, 40)")
        for p in PLANTAS:
            self.conn.execute("INSERT INTO sucursales (plant, nombre, organizacion, canal, corredor) "
                              "VALUES (?, ?, 'GAM', 'Menudeo', 'C1')", (p, p))
            self.conn.execute("INSERT INTO inventarios (material_id, plant, disponible, transito, comprometido) "
                              "VALUES ('MAT', ?, ?, 0, 5)", (p, 0 if p == "SOP" else 10))
            for mes in ("2026-05", "2026-06", "2026-07", "2026-08"):
                self.conn.execute("INSERT INTO ventas_mensuales (material_id, plant, canal, anio_mes, cantidad_m2, importe) "
                                  "VALUES ('MAT', ?, 'Menudeo', ?, 57.6, 0)", (p, mes))
        self.conn.commit()
        sc.init_tables(self.conn)

    def tearDown(self):
        self.conn.close()
        self._csv.stop()

    def cargar_evidencia(self):
        sc.reemplazar_evidencia(self.conn, [_evidencia("DIR", 30), _evidencia("ESP", 3),
                                            _evidencia("NOC", 0), _evidencia("SOP", 0)])
        return sc.recalcular(self.conn)


class RecalcularTests(_BaseDB):
    def test_sin_evidencia_no_filtra(self):
        sc.recalcular(self.conn)
        self.assertEqual(sc.conteo(self.conn), {sc.SIN_EVIDENCIA: 4})
        self.assertEqual(sc.plantas_sin_compra(self.conn), set())
        self.assertEqual(sc.plantas_sin_operacion(self.conn), set())

    def test_clasifica_con_evidencia(self):
        self.cargar_evidencia()
        clases = sc.clases_por_planta(self.conn)
        self.assertEqual(clases, {"DIR": sc.COMPRA_DIRECTA, "ESP": sc.COMPRA_ESPORADICA,
                                  "NOC": sc.NO_COMPRA, "SOP": sc.SIN_OPERACION})
        self.assertEqual(sc.plantas_sin_compra(self.conn), {"ESP", "NOC", "SOP"})

    def test_override_manda_y_se_puede_quitar(self):
        self.cargar_evidencia()
        self.conn.execute("INSERT INTO sucursal_compra_override (plant, clase, actualizado) VALUES ('ESP', ?, 'x')",
                          (sc.COMPRA_DIRECTA,))
        sc.recalcular(self.conn)
        fila = self.conn.execute("SELECT * FROM sucursal_compra WHERE plant='ESP'").fetchone()
        self.assertEqual((fila["clase"], fila["clase_calculada"], fila["fuente"]),
                         (sc.COMPRA_DIRECTA, sc.COMPRA_ESPORADICA, "override"))
        self.conn.execute("DELETE FROM sucursal_compra_override")
        sc.recalcular(self.conn)
        self.assertEqual(sc.clases_por_planta(self.conn)["ESP"], sc.COMPRA_ESPORADICA)

    def test_cambiar_umbral_reclasifica(self):
        self.cargar_evidencia()
        sc.set_umbral(self.conn, 3)
        sc.recalcular(self.conn)
        self.assertEqual(sc.clases_por_planta(self.conn)["ESP"], sc.COMPRA_DIRECTA)


class FiltrosMotoresTests(_BaseDB):
    def _generar(self):
        lotes_compra.init_tables(self.conn)
        self.conn.execute("DELETE FROM lotes_compra_clasificacion")
        self.conn.execute("DELETE FROM lotes_compra")
        return generar_sugeridos(familia=None, proveedor=None, corredor=None, plant=None, abc=None,
                                 solo_criticos=False, page=1, page_size=200, fecha=None, db=self.conn)

    def test_sugeridos_solo_compra_directa(self):
        self.cargar_evidencia()
        res = self._generar()
        self.assertEqual({i["plant"] for i in res["items"]}, {"DIR"})
        self.assertTrue(res["sucursal_compra"]["activo"])
        self.assertEqual(res["sucursal_compra"]["sucursales_excluidas"], 3)

    def test_sugeridos_sin_catalogo_no_filtra(self):
        sc.recalcular(self.conn)
        res = self._generar()
        self.assertEqual({i["plant"] for i in res["items"]}, set(PLANTAS))
        self.assertFalse(res["sucursal_compra"]["activo"])

    def test_balanceos_excluye_solo_sin_operacion(self):
        self.cargar_evidencia()
        filas = [{"plant": p} for p in PLANTAS]
        self.assertEqual([f["plant"] for f in balanceos._sin_plantas_fuera_de_universo(self.conn, filas)],
                         ["DIR", "ESP", "NOC"])


if __name__ == "__main__":
    unittest.main()
