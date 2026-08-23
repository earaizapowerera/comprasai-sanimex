"""Tests unitarios/integración para app.routers.inventarios: guard de demanda
residual/cero en COBERTURA_CTE al calcular cobertura_meses (T18, waykee
290114 -- mismo bug reportado y ya corregido en kpis.py por T16, waykee
290112, commit 1ecdefe).

El dataset REAL CAR trae demandas que pueden venir en 0 o en valores
residuales ~1e-15 (ruido de origen). Sin el guard EPS_DEMANDA,
disponible_neto / demanda_prom con un denominador ínfimo producía
coberturas absurdas (~1e+15 meses) en /api/inventarios/cobertura y
derivados (/cobertura/resumen, /cobertura/priorizadas).

Ejecutar (sin dependencias extra, solo stdlib):
    cd backend && python3 -m unittest tests.test_inventarios -v
"""

import sqlite3
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.constants import EPS_DEMANDA  # noqa: E402
from app.routers.inventarios import (  # noqa: E402
    cobertura_resumen,
    list_cobertura,
)

SCHEMA_PATH = BACKEND_DIR / "app" / "core" / "schema.sql"


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
    # MAT-NORMAL con demanda real (cobertura = 500/100 = 5.0); MAT-RESIDUAL
    # con demanda ~1e-15 (antes del fix: 500/1e-15 = 5e+17 meses); MAT-CERO
    # sin filas de ventas (COALESCE(demanda_prom, 0) -> 0, sin_dato).
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


class ListCoberturaIntegrationTests(unittest.TestCase):
    """/api/inventarios/cobertura (COBERTURA_CTE) ya no debe producir
    cobertura_meses absurda ni clasificar MAT-RESIDUAL como 'ok'/'exceso'."""

    def setUp(self):
        self.conn = _build_memory_db()

    def tearDown(self):
        self.conn.close()

    def _items_by_material(self):
        # Los parámetros Query(...) con pattern (abc, estado, sort, page,
        # page_size) deben pasarse explícitos: llamando la función directa
        # (fuera del ciclo de request de FastAPI) el default sería el objeto
        # Query en sí, no el valor que resuelve en runtime.
        result = list_cobertura(
            organizacion=None, canal=None, corredor=None, plant=None, familia=None,
            abc=None, estado=None, search=None, sort="cobertura_asc", page=1, page_size=50,
            db=self.conn,
        )
        return {item["material_id"]: item for item in result["items"]}

    def test_demanda_normal_calcula_cobertura(self):
        items = self._items_by_material()
        self.assertAlmostEqual(items["MAT-NORMAL"]["cobertura_meses"], 5.0)
        # objetivo=2.0 -> 5.0 no es < objetivo ni > objetivo*2.5 (=5.0, límite exclusivo) -> 'ok'
        self.assertEqual(items["MAT-NORMAL"]["estado"], "ok")

    def test_demanda_cero_es_sin_dato(self):
        items = self._items_by_material()
        self.assertIsNone(items["MAT-CERO"]["cobertura_meses"])
        self.assertEqual(items["MAT-CERO"]["estado"], "sin_dato")

    def test_demanda_residual_es_sin_dato_no_absurda(self):
        # Antes del fix: 500 / 1e-15 = 5e+17 meses y el par calificaba 'exceso'.
        items = self._items_by_material()
        self.assertIsNone(items["MAT-RESIDUAL"]["cobertura_meses"])
        self.assertEqual(items["MAT-RESIDUAL"]["estado"], "sin_dato")

    def test_demanda_justo_en_el_umbral_si_calcula(self):
        # Límite inclusivo (>= EPS_DEMANDA): se considera demanda "real".
        self.conn.execute(
            "INSERT INTO materiales (material_id, descripcion, familia, abc, costo) VALUES "
            "('MAT-LIMITE', 'Limite EPS', 'F1', 'A', 10)"
        )
        self.conn.execute(
            "INSERT INTO inventarios (material_id, plant, disponible, transito, comprometido) VALUES "
            "('MAT-LIMITE', 'P1', 100, 0, 0)"
        )
        self.conn.execute(
            "INSERT INTO ventas_mensuales (material_id, plant, canal, anio_mes, cantidad_m2, importe) VALUES "
            f"('MAT-LIMITE', 'P1', 'Menudeo', '2026-08', {EPS_DEMANDA}, 0)"
        )
        self.conn.commit()
        items = self._items_by_material()
        self.assertIsNotNone(items["MAT-LIMITE"]["cobertura_meses"])
        self.assertAlmostEqual(items["MAT-LIMITE"]["cobertura_meses"], 100.0 / EPS_DEMANDA, places=0)


class CoberturaResumenIntegrationTests(unittest.TestCase):
    """/api/inventarios/cobertura/resumen: el promedio de cobertura no debe
    quedar distorsionado por demandas residuales."""

    def setUp(self):
        self.conn = _build_memory_db()

    def tearDown(self):
        self.conn.close()

    def test_cobertura_media_no_es_absurda(self):
        row = cobertura_resumen(
            organizacion=None, canal=None, corredor=None, plant=None, familia=None,
            abc=None, search=None, db=self.conn,
        )
        # AVG(cobertura_meses) ignora NULLs en SQLite -> solo MAT-NORMAL (5.0)
        self.assertAlmostEqual(row["cobertura_media_meses"], 5.0)
        self.assertLess(row["cobertura_media_meses"], 1000)  # antes del fix: ~1.67e+17
        self.assertEqual(row["total_pares"], 3)


if __name__ == "__main__":
    unittest.main()
