"""Tests de integración HTTP para el scope del rol "agente" (bot de Waykee,
ticket T24, waykee 290122): autenticación por X-Api-Key contra
COMPRASAI_AGENT_KEY y el scope GET-consulta/genera-propuestas vs
bloqueado-confirma/aprueba.

Usa fastapi.testclient (requiere httpx) porque el scope se aplica vía
middleware HTTP -- llamar a los handlers directo (como el resto de los
tests de este repo) se saltaría el middleware por completo.

Ejecutar:
    cd backend && python3 -m unittest tests.test_agent_scope -v
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# IMPORTANTE: hay que fijar COMPRASAI_DB_PATH (a una DB de prueba, con solo
# el esquema, sin datos) ANTES de importar app.main -- app.core.config lee
# la env var una sola vez al importarse, y si no existe ningún .db en
# BACKEND_DIR/data la app intentaría generar el dataset sintético completo
# (lento, y con efecto secundario de escribir un archivo real en el repo).
_TMP_DB = Path(tempfile.mkdtemp(prefix="comprasai_agent_scope_")) / "test.db"
os.environ["COMPRASAI_DB_PATH"] = str(_TMP_DB)
os.environ["AUTO_SEED_IF_MISSING"] = "0"
os.environ.setdefault("FRONTEND_STATIC_DIR", str(BACKEND_DIR / "_no_frontend_static_en_tests"))

_SCHEMA_PATH = BACKEND_DIR / "app" / "core" / "schema.sql"
_conn = sqlite3.connect(str(_TMP_DB))
_conn.executescript(_SCHEMA_PATH.read_text())
_conn.commit()
_conn.close()

from fastapi.testclient import TestClient  # noqa: E402

import app.main as app_main  # noqa: E402
from app.core.agent_scope import AGENT_KEY_ENV_VAR  # noqa: E402

VALID_KEY = "test-agent-key-12345"


class AgentScopeTestsBase(unittest.TestCase):
    def setUp(self):
        self._env_backup = os.environ.get(AGENT_KEY_ENV_VAR)
        # Usar TestClient como context manager para que dispare los eventos
        # de "startup" (crea/siembra las tablas auxiliares de remates y
        # balanceos) -- instanciarlo directo NO ejecuta el lifespan.
        self._client_cm = TestClient(app_main.app)
        self.client = self._client_cm.__enter__()
        self.addCleanup(self._client_cm.__exit__, None, None, None)

    def tearDown(self):
        if self._env_backup is None:
            os.environ.pop(AGENT_KEY_ENV_VAR, None)
        else:
            os.environ[AGENT_KEY_ENV_VAR] = self._env_backup


class SinVariableDeEntornoTests(AgentScopeTestsBase):
    """1) Sin COMPRASAI_AGENT_KEY configurada -> modo agente deshabilitado."""

    def setUp(self):
        super().setUp()
        os.environ.pop(AGENT_KEY_ENV_VAR, None)

    def test_resto_de_la_app_sigue_igual_sin_header(self):
        resp = self.client.get("/api/kpis")
        self.assertEqual(resp.status_code, 200)

    def test_resto_de_la_app_sigue_igual_con_header_random(self):
        # Alguien manda X-Api-Key igual, pero como el modo está deshabilitado
        # no debe rechazarse ni otorgar ningún privilegio especial.
        resp = self.client.get("/api/kpis", headers={"X-Api-Key": "lo-que-sea"})
        self.assertEqual(resp.status_code, 200)

    def test_manifest_deshabilitado(self):
        resp = self.client.get("/api/agent/manifest", headers={"X-Api-Key": "lo-que-sea"})
        self.assertEqual(resp.status_code, 503)


class ConVariableDeEntornoTests(AgentScopeTestsBase):
    """2)-4) Con COMPRASAI_AGENT_KEY configurada."""

    def setUp(self):
        super().setUp()
        os.environ[AGENT_KEY_ENV_VAR] = VALID_KEY

    def test_key_valida_get_permitido_ok(self):
        for path in ("/api/kpis", "/api/inventarios/cobertura", "/api/engines/sugeridos/lista",
                     "/api/balanceos/propuestas", "/api/remates/detectar", "/api/tendencias/ganadores"):
            with self.subTest(path=path):
                resp = self.client.get(path, headers={"X-Api-Key": VALID_KEY})
                self.assertEqual(resp.status_code, 200, resp.text)

    def test_key_valida_generacion_de_propuestas_ok(self):
        resp = self.client.get("/api/engines/sugeridos/generar", headers={"X-Api-Key": VALID_KEY})
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_key_valida_sobre_endpoint_bloqueado_403(self):
        casos = [
            ("POST", "/api/engines/sugeridos/decidir", {"ids": ["x"], "accion": "aprobar"}),
            ("GET", "/api/engines/sugeridos/exportar-sap", None),
            ("PUT", "/api/engines/sugeridos/SUG-1/editar", {"cantidad_final": 1, "justificacion": "porque si"}),
            ("PUT", "/api/balanceos/config", {}),
            ("PUT", "/api/remates/config/escalas", []),
            ("PUT", "/api/remates/config/rutas", {}),
            ("POST", "/api/chat", {"message": "hola"}),
        ]
        for metodo, path, body in casos:
            with self.subTest(metodo=metodo, path=path):
                resp = self.client.request(metodo, path, headers={"X-Api-Key": VALID_KEY}, json=body)
                self.assertEqual(resp.status_code, 403, resp.text)

    def test_sin_key_no_se_restringe_el_scope(self):
        # Sin header, el request sigue como hoy (no es "agente"): un endpoint
        # que estaría bloqueado para el agente sigue accesible para el
        # frontend/humano normal.
        resp = self.client.get("/api/engines/sugeridos/exportar-sap")
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_key_invalida_401(self):
        resp = self.client.get("/api/kpis", headers={"X-Api-Key": "no-es-la-key"})
        self.assertEqual(resp.status_code, 401)

    def test_manifest_sin_key_401(self):
        resp = self.client.get("/api/agent/manifest")
        self.assertEqual(resp.status_code, 401)

    def test_manifest_key_invalida_401(self):
        resp = self.client.get("/api/agent/manifest", headers={"X-Api-Key": "no-es-la-key"})
        self.assertEqual(resp.status_code, 401)

    def test_manifest_coherente(self):
        resp = self.client.get("/api/agent/manifest", headers={"X-Api-Key": VALID_KEY})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()

        self.assertIn("endpoints_permitidos", data)
        self.assertIn("endpoints_bloqueados", data)
        self.assertIn("deep_link_base", data)
        self.assertTrue(data["deep_link_base"].startswith("https://"))
        self.assertNotIn("#/", data["deep_link_base"])

        permitidos = data["endpoints_permitidos"]
        self.assertTrue(len(permitidos) > 10)
        for item in permitidos:
            self.assertIn("metodo", item)
            self.assertIn("path", item)
            self.assertIn("descripcion", item)
            self.assertIn("parametros", item)
            # Todo lo listado como "permitido" debe efectivamente pasar el
            # scope real que aplica el middleware (evita que el manifest
            # mienta sobre lo que el agente puede hacer).
            from app.core.agent_scope import is_blocked_for_agent
            path_concreto = item["path"].replace("{material_id}", "MAT-1").replace("{plant_o_canal}", "P1").replace("{plant}", "P1")
            self.assertFalse(
                is_blocked_for_agent(item["metodo"], item["path"]),
                f"{item['metodo']} {item['path']} está en endpoints_permitidos pero el middleware lo bloquea",
            )

        bloqueados = data["endpoints_bloqueados"]
        self.assertTrue(len(bloqueados) > 0)
        for item in bloqueados:
            self.assertTrue(
                is_blocked_for_agent(item["metodo"], item["path"]),
                f"{item['metodo']} {item['path']} está en endpoints_bloqueados pero el middleware lo permite",
            )

        # Pantallas: deep-links reales del router (BrowserRouter, sin "#/").
        self.assertIn("sugeridos", data["pantallas"])
        self.assertEqual(data["pantallas"]["sugeridos"]["url"], "https://comprassanimexai.powerera.com/comprasAI/sugeridos")


if __name__ == "__main__":
    unittest.main()
