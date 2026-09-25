"""Abrir un artículo = HANA en vivo, snapshot solo como respaldo (waykee 292300).

Ejecutar:
    cd backend && python3 -m unittest tests.test_articulo_vivo -v
"""

import os
import sqlite3
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core import hana_articulo, hana_live  # noqa: E402
from app.core.db import _row_factory  # noqa: E402
from app.routers.articulo_vivo import articulo_en_vivo  # noqa: E402
from app.routers.engines.balanceos import _compute_grid1, init_tables  # noqa: E402
from app.routers.engines.balanceos import vivo as balanceos_vivo  # noqa: E402
from app.routers.engines.sugeridos import backorder_detalle, pedidos_detalle  # noqa: E402

MAT = "G16-18-1-49"
HOY = date(2026, 9, 25)
CAIDO = hana_live.HanaNoDisponible("conexion: OperationalError")

VIVO = {
    "posicion": {"M414": {"disponible": 187.0, "transito": 10.0, "comprometido": 3.0},
                 "M416": {"disponible": 40.0, "transito": 0.0, "comprometido": 0.0},
                 "CDG1": {"disponible": 999.0, "transito": 0.0, "comprometido": 0.0}},
    "pedidos": [{"plant": "M414", "po": "4500000001", "posicion": "00010", "proveedor": "LAMOSA",
                 "cantidad_pendiente": 80.0, "cantidad_pedida": 80.0, "fecha_po": "2026-09-01",
                 "fecha_entrega_estimada": "2026-09-30"}],
    "backorder": [{"plant": "M414", "documento": "0285461327", "posicion": "000020", "cliente": "MENUDEO",
                   "cantidad_pendiente": 3.0, "fecha_documento": "2026-09-25",
                   "fecha_entrega_comprometida": "2026-09-25"}],
    "venta_mes": {"anio_mes": "2026-09", "m2_por_plant": {"M414": 297.44}},
}


def _en_vivo(material_id, plant=None, partes=None):
    return {p: VIVO[p] for p in partes or VIVO}


def _db():
    db = sqlite3.connect(":memory:")
    db.row_factory = _row_factory
    db.executescript((BACKEND_DIR / "app" / "core" / "schema.sql").read_text())
    init_tables(db)
    db.execute("INSERT INTO materiales(material_id, descripcion, familia, formato, m2_por_caja, abc, precio_venta, costo, economico)"
               " VALUES (?, 'Piso', 'F', '60x60', 1.69, 'A', 100, 50, 0)", (MAT,))
    for plant in ("M414", "M415", "M416"):
        db.execute("INSERT INTO sucursales(plant, nombre, organizacion, canal, corredor, es_cedis)"
                   " VALUES (?, ?, 'GAM', 'Menudeo', 'JAL', 0)", (plant, f"GDL {plant}"))
    for plant, disp in (("M414", 191.0), ("M415", 12.0)):  # M416 aún no está en el snapshot
        db.execute("INSERT INTO inventarios(material_id, plant, disponible, transito, comprometido, pedidos_abiertos, cajas_remanentes)"
                   " VALUES (?, ?, ?, 0, 0, 0, 0)", (MAT, plant, disp))
    return db


@mock.patch.dict(os.environ, {"COMPRASAI_SQLSERVER_HOST": ""})
class ArticuloVivoTest(unittest.TestCase):
    def setUp(self):
        hana_live.reset_breaker()
        self.db = _db()

    def test_en_vivo_manda_hana(self):
        with mock.patch.object(hana_articulo, "leer", side_effect=_en_vivo):
            r = articulo_en_vivo(MAT, None, db=self.db)
        self.assertTrue(r["fuente"]["live"])
        self.assertEqual(r["fuente"]["fuente"], "hana_car")
        pos = {p["plant"]: p for p in r["posiciones"]}
        self.assertEqual(pos["M414"]["disponible"], 187.0)
        self.assertEqual(pos["M414"]["disponible_neto"], 194.0)
        self.assertEqual(pos["M414"]["pedidos_compra_pendientes"], 80.0)
        self.assertEqual(pos["M414"]["venta_mes_m2"], 297.44)
        self.assertNotIn("CDG1", pos)  # fuera del universo de sucursales
        self.assertNotIn("M415", pos)  # HANA no la reporta: hoy no tiene nada

    def test_hana_caido_cae_al_snapshot_marcado(self):
        with mock.patch.object(hana_articulo, "leer", side_effect=CAIDO):
            r = articulo_en_vivo(MAT, None, db=self.db)
        self.assertFalse(r["fuente"]["live"])
        self.assertEqual(r["fuente"]["motivo_fallback"], "conexion: OperationalError")
        self.assertIn("corte_snapshot_utc", r["fuente"])
        self.assertEqual({p["plant"]: p["disponible"] for p in r["posiciones"]}, {"M414": 191.0, "M415": 12.0})
        self.assertIsNone(r["venta_mes"])

    def test_sin_credenciales_no_intenta_conectar(self):
        with mock.patch.dict(os.environ, {k: "" for k in hana_live._ENV}):
            r = articulo_en_vivo(MAT, "M414", db=self.db)
        self.assertEqual(r["fuente"]["motivo_fallback"], "hana_no_configurado")

    def test_drill_downs_de_sugeridos_en_vivo(self):
        with mock.patch.object(hana_articulo, "leer", side_effect=_en_vivo):
            bo = backorder_detalle(material_id=MAT, plant="M414", db=self.db)
            po = pedidos_detalle(material_id=MAT, plant="M414", db=self.db)
        self.assertTrue(bo["disponible"] and bo["fuente"]["live"])
        self.assertEqual(bo["documentos"][0]["documento"], "0285461327")
        self.assertEqual(po["pedidos"][0]["proveedor"], "LAMOSA")

    def test_grid1_con_posicion_viva(self):
        with mock.patch.object(hana_articulo, "leer", side_effect=_en_vivo):
            vivo = balanceos_vivo.leer(self.db, MAT)
        filas = {f["plant"]: f for f in _compute_grid1(self.db, MAT, "JAL", HOY, vivo=vivo)}
        self.assertEqual(filas["M414"]["disponibleNetoCajas"], 194.0)
        self.assertEqual(filas["M414"]["backorderCompra"]["cajas"], 80.0)
        self.assertEqual(filas["M414"]["backorderTraslado"]["cajas"], 3.0)
        self.assertEqual(filas["M415"]["disponibleNetoCajas"], 0.0)  # snapshot decía 12, HANA ya no
        self.assertEqual(filas["M416"]["disponibleNetoCajas"], 40.0)  # nueva, solo en HANA

    def test_grid1_sin_hana_queda_igual_que_el_snapshot(self):
        with mock.patch.object(hana_articulo, "leer", side_effect=CAIDO):
            vivo = balanceos_vivo.leer(self.db, MAT)
        filas = {f["plant"]: f for f in _compute_grid1(self.db, MAT, "JAL", HOY, vivo=vivo)}
        self.assertEqual(set(filas), {"M414", "M415"})
        self.assertEqual(filas["M414"]["disponibleNetoCajas"], 191.0)


class CortacircuitoTest(unittest.TestCase):
    def setUp(self):
        hana_live.reset_breaker()

    def tearDown(self):
        hana_live.reset_breaker()

    def test_tras_fallo_de_conexion_no_reintenta_hasta_la_ventana(self):
        env = {"SANIMEX_CAR_HOST": "h", "SANIMEX_CAR_PORT": "1", "SANIMEX_CAR_USER": "u", "SANIMEX_CAR_PASS": "p"}
        dbapi = mock.MagicMock()
        dbapi.connect.side_effect = OSError("refused")
        with mock.patch.dict(os.environ, env), mock.patch.dict(sys.modules, {"hdbcli": mock.MagicMock(dbapi=dbapi)}):
            with self.assertRaises(hana_live.HanaNoDisponible):
                hana_live.stock_actual(MAT, "M414")
            with self.assertRaises(hana_live.HanaNoDisponible) as ctx:
                hana_live.stock_actual(MAT, "M414")
        self.assertEqual(dbapi.connect.call_count, 1)
        self.assertIn("reintento en espera", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
