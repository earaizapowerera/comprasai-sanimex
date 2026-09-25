"""GET /api/inventarios/saldo-actual: HANA en vivo con fallback al snapshot."""

import os
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core import hana_live  # noqa: E402
from app.routers.saldo_actual import saldo_actual  # noqa: E402


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE inventarios (material_id TEXT, plant TEXT, disponible REAL)")
    conn.execute("INSERT INTO inventarios VALUES ('M1', 'P1', 191.0)")
    return conn


@mock.patch.dict(os.environ, {"COMPRASAI_SQLSERVER_HOST": ""})
class SaldoActualTest(unittest.TestCase):
    def test_sin_credenciales_cae_al_snapshot(self):
        env = {k: "" for k in hana_live._ENV}
        with mock.patch.dict(os.environ, env):
            r = saldo_actual("M1", "P1", db=_db())
        self.assertFalse(r["live"])
        self.assertEqual(r["fuente"], "snapshot")
        self.assertEqual(r["disponible"], 191.0)
        self.assertEqual(r["motivo_fallback"], "hana_no_configurado")
        self.assertIn("corte_snapshot_utc", r)

    def test_hana_caido_cae_al_snapshot(self):
        with mock.patch.object(hana_live, "stock_actual",
                               side_effect=hana_live.HanaNoDisponible("conexion: timeout")):
            r = saldo_actual("M1", "P1", db=_db())
        self.assertFalse(r["live"])
        self.assertEqual(r["disponible"], 191.0)

    def test_en_vivo_manda_hana(self):
        with mock.patch.object(hana_live, "stock_actual", return_value=182.0):
            r = saldo_actual("M1", "P1", db=_db())
        self.assertTrue(r["live"])
        self.assertEqual(r["fuente"], "hana_car")
        self.assertEqual(r["disponible"], 182.0)
        self.assertEqual(r["disponible_snapshot"], 191.0)

    def test_sin_fila_en_hana_es_cero(self):
        with mock.patch.object(hana_live, "stock_actual", return_value=None):
            r = saldo_actual("M9", "P9", db=_db())
        self.assertTrue(r["live"])
        self.assertEqual(r["disponible"], 0.0)
        self.assertIsNone(r["disponible_snapshot"])


if __name__ == "__main__":
    unittest.main()
