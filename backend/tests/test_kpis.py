"""Tests unitarios/integración para app.routers.kpis: guard de demanda
residual/cero al calcular cobertura_meses (T16 - fix dataset REAL CAR).

El dataset REAL CAR trae demandas que pueden venir en 0 o en valores
residuales ~1e-15 (ruido de origen). Sin el guard EPS_DEMANDA,
disponible_neto / demanda_prom con un denominador ínfimo producía
coberturas absurdas (~1e+15 meses).

Ejecutar (sin dependencias extra, solo stdlib):
    cd backend && python3 -m unittest tests.test_kpis -v
"""

import sqlite3
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.routers.kpis import (  # noqa: E402
    EPS_DEMANDA,
    calcular_cobertura_meses,
    get_kpis,
    list_compras_urgentes,
)

SCHEMA_PATH = BACKEND_DIR / "app" / "core" / "schema.sql"


class CalcularCoberturaMesesTests(unittest.TestCase):
    """Casos pedidos en T16: demanda=0, demanda~1e-15, demanda normal."""

    def test_demanda_cero_retorna_none(self):
        self.assertIsNone(calcular_cobertura_meses(disponible_neto=500.0, demanda_prom=0.0))

    def test_demanda_residual_retorna_none(self):
        # Antes del fix: 500 / 1e-15 = 5e+17 meses (el bug reportado). Ahora: None ("sin dato").
        self.assertIsNone(calcular_cobertura_meses(disponible_neto=500.0, demanda_prom=1e-15))

    def test_demanda_none_retorna_none(self):
        self.assertIsNone(calcular_cobertura_meses(disponible_neto=500.0, demanda_prom=None))

    def test_demanda_normal_calcula_cobertura(self):
        self.assertAlmostEqual(calcular_cobertura_meses(disponible_neto=500.0, demanda_prom=100.0), 5.0)

    def test_demanda_justo_en_el_umbral_si_calcula(self):
        # demanda == EPS_DEMANDA es el límite inclusivo -> se considera "real", sí calcula.
        resultado = calcular_cobertura_meses(disponible_neto=1.0, demanda_prom=EPS_DEMANDA)
        self.assertIsNotNone(resultado)
        self.assertAlmostEqual(resultado, 1.0 / EPS_DEMANDA)


def _build_memory_db():
    """DB SQLite en memoria (esquema real de app/core/schema.sql) con 3 pares
    material-plant: demanda normal, demanda cero (sin ventas) y demanda
    residual ~1e-15 (el caso reportado del dataset REAL CAR)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = lambda cursor, row: dict(zip([c[0] for c in cursor.description], row))
    conn.executescript(SCHEMA_PATH.read_text())

    conn.execute(
        "INSERT INTO materiales (material_id, descripcion, familia, abc, costo) VALUES "
        "('MAT-NORMAL', 'Normal', 'F1', 'A', 10), "
        "('MAT-CERO', 'Sin ventas', 'F1', 'A', 10), "
        "('MAT-RESIDUAL', 'Ruido REAL CAR', 'F1', 'A', 10)"
    )
    conn.execute(
        "INSERT INTO sucursales (plant, nombre, organizacion, canal) VALUES "
        "('P1', 'Sucursal 1', 'GAM', 'Menudeo')"
    )
    conn.execute(
        "INSERT INTO inventarios (material_id, plant, disponible, transito, comprometido) VALUES "
        "('MAT-NORMAL', 'P1', 500, 0, 0), "
        "('MAT-CERO', 'P1', 500, 0, 0), "
        "('MAT-RESIDUAL', 'P1', 500, 0, 0)"
    )
    conn.execute(
        "INSERT INTO coberturas_objetivo (material_id, meses_objetivo) VALUES "
        "('MAT-NORMAL', 2.0), ('MAT-CERO', 2.0), ('MAT-RESIDUAL', 2.0)"
    )
    # MAT-NORMAL con demanda real; MAT-RESIDUAL con demanda ~1e-15;
    # MAT-CERO sin filas de ventas (COALESCE(demanda_prom, 0) -> 0).
    conn.execute(
        "INSERT INTO ventas_mensuales (material_id, plant, canal, anio_mes, cantidad_m2, importe) VALUES "
        "('MAT-NORMAL', 'P1', 'Menudeo', '2026-06', 100, 1000), "
        "('MAT-NORMAL', 'P1', 'Menudeo', '2026-07', 100, 1000), "
        "('MAT-NORMAL', 'P1', 'Menudeo', '2026-08', 100, 1000), "
        "('MAT-RESIDUAL', 'P1', 'Menudeo', '2026-06', 1e-15, 0), "
        "('MAT-RESIDUAL', 'P1', 'Menudeo', '2026-07', 1e-15, 0), "
        "('MAT-RESIDUAL', 'P1', 'Menudeo', '2026-08', 1e-15, 0)"
    )
    conn.commit()
    return conn


class GetKpisIntegrationTests(unittest.TestCase):
    """/api/kpis ya no debe arrojar cobertura_promedio_meses absurda cuando
    hay pares con demanda residual (~1e-15) en el dataset."""

    def setUp(self):
        self.conn = _build_memory_db()

    def tearDown(self):
        self.conn.close()

    def test_cobertura_promedio_no_es_absurda(self):
        result = get_kpis(organizacion=None, canal=None, db=self.conn)
        # (500/100 [MAT-NORMAL] + 0.0 [MAT-CERO, sin dato] + 0.0 [MAT-RESIDUAL, sin dato]) / 3
        self.assertAlmostEqual(result["cobertura_promedio_meses"], 1.67, places=2)
        self.assertLess(result["cobertura_promedio_meses"], 1000)  # antes del fix: ~1.67e+14


class ListComprasUrgentesIntegrationTests(unittest.TestCase):
    """El guard EPS también aplica al SQL crudo de /compras-urgentes (WHERE y CASE)."""

    def setUp(self):
        self.conn = _build_memory_db()

    def tearDown(self):
        self.conn.close()

    def test_excluye_pares_con_demanda_residual_o_cero(self):
        result = list_compras_urgentes(limit=50, db=self.conn)
        material_ids = {item["material_id"] for item in result["items"]}
        # MAT-RESIDUAL (demanda ~1e-15) no debe colarse como urgente: antes del
        # fix, 500/1e-15 daba una cobertura absurdamente alta que además podía
        # calificar falsamente "< meses_objetivo" por errores de precisión.
        self.assertNotIn("MAT-RESIDUAL", material_ids)
        self.assertNotIn("MAT-CERO", material_ids)


if __name__ == "__main__":
    unittest.main()
