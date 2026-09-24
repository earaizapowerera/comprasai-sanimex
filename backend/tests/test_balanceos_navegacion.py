"""Tests de la navegación Zona -> Artículos de Balanceos v3 (waykee 292197):
agrupar_por_zona y agrupar_por_articulo sobre propuestas ya calculadas.

Ejecutar:
    cd backend && python3 -m unittest tests.test_balanceos_navegacion -v
"""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.routers.engines.balanceos import agrupar_por_articulo, agrupar_por_zona  # noqa: E402


def _p(material, corredor, ahorro, cajas=10, deficit=5.0, destino="D1"):
    return {
        "material_id": material, "descripcion": f"desc {material}", "abc": "A", "corredor": corredor,
        "origen": {"plant": "O1", "nombre": "Origen"}, "destino": {"plant": destino, "nombre": destino},
        "deficit": deficit, "cajasTransferir": cajas, "cajasComprar": 0,
        "costoTraslado": 100, "ahorroEstimado": ahorro,
    }


PROPUESTAS = [
    _p("M1", "NORTE", 500),
    _p("M1", "NORTE", 300, destino="D2"),
    _p("M2", "NORTE", 100),
    _p("M3", "SUR", 2000),
]


class TestAgruparPorZona(unittest.TestCase):
    def test_conteos_y_totales(self):
        zonas = {z["corredor"]: z for z in agrupar_por_zona(PROPUESTAS)}
        self.assertEqual(zonas["NORTE"]["propuestas"], 3)
        self.assertEqual(zonas["NORTE"]["materiales"], 2)
        self.assertEqual(zonas["NORTE"]["ahorroTotal"], 900)
        self.assertEqual(zonas["NORTE"]["cajasTransferir"], 30)
        self.assertEqual(zonas["SUR"]["propuestas"], 1)

    def test_orden_por_ahorro_desc(self):
        self.assertEqual([z["corredor"] for z in agrupar_por_zona(PROPUESTAS)], ["SUR", "NORTE"])

    def test_vacio(self):
        self.assertEqual(agrupar_por_zona([]), [])


class TestAgruparPorArticulo(unittest.TestCase):
    def test_filtra_corredor_y_agrupa_material(self):
        arts = agrupar_por_articulo(PROPUESTAS, "NORTE")
        self.assertEqual([a["material_id"] for a in arts], ["M1", "M2"])
        m1 = arts[0]
        self.assertEqual(m1["propuestas"], 2)
        self.assertEqual(m1["ahorroEstimado"], 800)
        self.assertEqual(m1["deficit"], 10.0)
        self.assertEqual(len(m1["destinos"]), 2)

    def test_corredor_inexistente(self):
        self.assertEqual(agrupar_por_articulo(PROPUESTAS, "XX"), [])

    def test_suma_de_articulos_cuadra_con_zona(self):
        zona = next(z for z in agrupar_por_zona(PROPUESTAS) if z["corredor"] == "NORTE")
        arts = agrupar_por_articulo(PROPUESTAS, "NORTE")
        self.assertEqual(sum(a["propuestas"] for a in arts), zona["propuestas"])
        self.assertEqual(sum(a["ahorroEstimado"] for a in arts), zona["ahorroTotal"])


if __name__ == "__main__":
    unittest.main()
