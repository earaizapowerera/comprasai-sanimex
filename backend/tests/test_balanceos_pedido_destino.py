"""Backorder de compra del Grid 1 solo en la sucursal receptora de la OC
(waykee 292243): una OC cuyo almacén destino es M416 no debe aparecer en
M414/M415 aunque estén en la misma zona.

Ejecutar:
    cd backend && python3 -m unittest tests.test_balanceos_pedido_destino -v
"""

import sqlite3
import sys
import unittest
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.db import _row_factory  # noqa: E402
from app.routers.engines.balanceos import (  # noqa: E402
    _compute_grid1, init_tables, resumir_pedidos_compra,
)

HOY = date(2026, 9, 24)
MAT = "G06-55-1-124"


def _doc(plant, po, cant, fecha):
    return {"plant": plant, "po": po, "cantidad_pendiente": cant, "fecha_po": fecha}


class TestResumirPedidosCompra(unittest.TestCase):
    DOCS = [
        _doc("M416", "4500533285", 36, "2026-07-17"),
        _doc("M416", "4500533376", 72, "2026-07-17"),
        _doc("M416", "4500534356", 36, "2026-07-24"),
    ]

    def test_solo_cuenta_en_la_sucursal_receptora(self):
        r = resumir_pedidos_compra(self.DOCS, "M416", HOY)
        self.assertEqual(r, {"cajas": 144, "numeroPedidos": 3, "diasDesdePedido": 69})

    def test_otra_sucursal_de_la_zona_no_ve_la_oc(self):
        for plant in ("M414", "M415"):
            r = resumir_pedidos_compra(self.DOCS, plant, HOY)
            self.assertEqual(r, {"cajas": 0, "numeroPedidos": 0, "diasDesdePedido": None})

    def test_lineas_de_la_misma_oc_cuentan_un_pedido(self):
        docs = [_doc("M414", "45001", 10, "2026-09-01"), _doc("M414", "45001", 5, "2026-09-01")]
        self.assertEqual(resumir_pedidos_compra(docs, "M414", HOY)["numeroPedidos"], 1)

    def test_lineas_ya_recibidas_no_cuentan(self):
        docs = [_doc("M414", "45001", 0, "2026-09-01")]
        self.assertEqual(resumir_pedidos_compra(docs, "M414", HOY)["numeroPedidos"], 0)


class TestGrid1PedidoDestino(unittest.TestCase):
    def setUp(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = _row_factory
        db.executescript((BACKEND_DIR / "app" / "core" / "schema.sql").read_text())
        init_tables(db)
        db.execute(
            """CREATE TABLE pedidos_compra_detalle (material_id TEXT, plant TEXT, po TEXT,
               posicion TEXT, proveedor TEXT, cantidad_pendiente REAL, cantidad_pedida REAL,
               fecha_po TEXT, fecha_entrega_estimada TEXT)"""
        )
        db.execute(
            "INSERT INTO materiales(material_id, descripcion, familia, formato, m2_por_caja, abc, precio_venta, costo, economico)"
            " VALUES (?, 'Piso', 'F', '60x60', 1.82, 'A', 100, 50, 0)", (MAT,),
        )
        for plant in ("M414", "M415", "M416"):
            db.execute(
                "INSERT INTO sucursales(plant, nombre, organizacion, canal, corredor, es_cedis)"
                " VALUES (?, ?, 'GAM', 'Menudeo', 'JAL', 0)", (plant, f"GDL {plant}"),
            )
            # El agregado trae pedidos en las 3 (como un snapshot desalineado):
            # el detalle por OC debe mandar.
            db.execute(
                "INSERT INTO inventarios(material_id, plant, disponible, transito, comprometido, pedidos_abiertos, cajas_remanentes)"
                " VALUES (?, ?, 5, 0, 0, 144, 0)", (MAT, plant),
            )
        db.execute(
            "INSERT INTO pedidos_compra_detalle(material_id, plant, po, posicion, cantidad_pendiente, fecha_po)"
            " VALUES (?, 'M416', '4500533285', '00050', 144, '2026-07-17')", (MAT,),
        )
        self.db = db

    def test_oc_solo_en_su_sucursal(self):
        filas = {f["plant"]: f["backorderCompra"] for f in _compute_grid1(self.db, MAT, "JAL", HOY)}
        self.assertEqual(filas["M416"]["cajas"], 144)
        self.assertEqual(filas["M416"]["numeroPedidos"], 1)
        self.assertEqual(filas["M416"]["diasDesdePedido"], 69)
        for plant in ("M414", "M415"):
            self.assertEqual(filas[plant]["cajas"], 0, plant)
            self.assertEqual(filas[plant]["numeroPedidos"], 0, plant)
            self.assertIsNone(filas[plant]["diasDesdePedido"], plant)


if __name__ == "__main__":
    unittest.main()
