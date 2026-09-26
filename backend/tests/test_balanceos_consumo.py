"""Tests del consumo de Balanceos con la fórmula de la vista de compras
ZCV_SAC_COM_ANALISIS (waykee 292247): ventana calendario de 4 meses con
ceros, sin mes en curso; PROM1/PROM2/PROM3 y VENTA_ANALIZADA.

Ejecutar:
    cd backend && python3 -m unittest tests.test_balanceos_consumo -v
"""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.routers.engines.balanceos.consumo import (  # noqa: E402
    calc_consumo_vista,
    consumo_linea,
    m2_a_cajas_demanda,
    meses_ventana,
)


class MesesVentanaTests(unittest.TestCase):
    def test_excluye_mes_actual(self):
        self.assertEqual(meses_ventana("2026-09"), ["2026-05", "2026-06", "2026-07", "2026-08"])

    def test_cruza_anio(self):
        self.assertEqual(meses_ventana("2026-02"), ["2025-10", "2025-11", "2025-12", "2026-01"])


class CalcConsumoVistaTests(unittest.TestCase):
    def test_caso_g06_59_1_132_m423_de_la_vista(self):
        # Fila de ZCV_SAC_COM_ANALISIS_CONCENTRADO, centro suministrador M423
        r = calc_consumo_vista([0, 80.96, 0, 705.76])
        self.assertAlmostEqual(r["prom1"], 196.68, places=2)
        self.assertAlmostEqual(r["prom2"], 26.99, places=2)
        self.assertAlmostEqual(r["prom3"], 352.88, places=2)
        self.assertAlmostEqual(r["ventaAnalizada"], 192.18, places=2)

    def test_meses_en_cero_cuentan(self):
        r = calc_consumo_vista([0, 0, 0, 12])
        self.assertAlmostEqual(r["prom1"], 3)
        self.assertAlmostEqual(r["prom2"], 0)
        self.assertAlmostEqual(r["prom3"], 6)
        self.assertAlmostEqual(r["ventaAnalizada"], 3)

    def test_rechaza_ventana_incompleta(self):
        with self.assertRaises(ValueError):
            calc_consumo_vista([1, 2, 3])


class ConsumoLineaTests(unittest.TestCase):
    def test_tienda_m423_con_ceros_y_mes_actual_ignorado(self):
        # Nivel tienda (opción B): M423 vendió 8.8 m2 en jun y 5.28 en ago;
        # mayo y julio sin venta; septiembre (mes en curso) no entra.
        meses = meses_ventana("2026-09")
        serie = {("G06-59-1-132", "M423"): {"2026-06": 8.8, "2026-08": 5.28, "2026-09": 999.0}}
        r = consumo_linea(serie, ("G06-59-1-132", "M423"), meses, 1.76)
        self.assertEqual([m["m2"] for m in r["meses"]], [0.0, 8.8, 0.0, 5.28])
        self.assertAlmostEqual(r["prom1"], 3.52)
        self.assertAlmostEqual(r["prom2"], 1.76)
        self.assertAlmostEqual(r["prom3"], 2.64)
        self.assertAlmostEqual(r["ventaAnalizada"], 2.64)
        self.assertAlmostEqual(r["demandaCajas"], 1.5)

    def test_sin_venta_da_cero(self):
        r = consumo_linea({}, ("X", "M001"), meses_ventana("2026-09"), 2.0)
        self.assertEqual(r["demandaCajas"], 0)

    def test_demanda_no_redondea_hacia_arriba(self):
        self.assertAlmostEqual(m2_a_cajas_demanda(2.64, 1.76), 1.5)
        self.assertEqual(m2_a_cajas_demanda(3.0, None), 3.0)


if __name__ == "__main__":
    unittest.main()
