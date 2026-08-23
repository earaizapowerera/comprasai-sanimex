"""Test unitario de calc_cobertura_meses en engines/sugeridos.py -- mismo
guard EPS_DEMANDA aplicado en el barrido de T18 (waykee 290114) porque
comparte el patrón de división por demanda vulnerable a residuales ~1e-15
del dataset REAL CAR (mismo bug que T16/kpis.py). Esta función también es
reusada por engines/balanceos.py (import directo), así que queda cubierta
transitivamente.

Ejecutar (sin dependencias extra, solo stdlib):
    cd backend && python3 -m unittest tests.test_sugeridos_cobertura -v
"""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.constants import EPS_DEMANDA  # noqa: E402
from app.routers.engines.sugeridos import calc_cobertura_meses  # noqa: E402


class CalcCoberturaMesesTests(unittest.TestCase):
    def test_demanda_cero_retorna_none(self):
        self.assertIsNone(calc_cobertura_meses(disponible_neto=500.0, demanda_mensual=0.0))

    def test_demanda_residual_retorna_none(self):
        # Antes del fix: 500 / 1e-15 = 5e+17 meses (el bug reportado). Ahora: None.
        self.assertIsNone(calc_cobertura_meses(disponible_neto=500.0, demanda_mensual=1e-15))

    def test_demanda_none_retorna_none(self):
        self.assertIsNone(calc_cobertura_meses(disponible_neto=500.0, demanda_mensual=None))

    def test_demanda_normal_calcula_cobertura(self):
        self.assertAlmostEqual(calc_cobertura_meses(disponible_neto=500.0, demanda_mensual=100.0), 5.0)

    def test_demanda_justo_en_el_umbral_si_calcula(self):
        resultado = calc_cobertura_meses(disponible_neto=1.0, demanda_mensual=EPS_DEMANDA)
        self.assertIsNotNone(resultado)
        self.assertAlmostEqual(resultado, 1.0 / EPS_DEMANDA)


if __name__ == "__main__":
    unittest.main()
