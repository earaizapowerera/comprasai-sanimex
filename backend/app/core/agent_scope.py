"""Autenticación y scope del "rol agente" (bot de Waykee) sobre la API de
ComprasAI -- ticket T24 (waykee 290122).

Filosofía (instrucción de Enrique): el agente puede CONSULTAR (GET) y
PROPONER (generar sugeridos/balanceos/remates), pero NUNCA confirmar ni
aprobar pedidos -- eso lo hace un humano dentro de la app.

Diseño centralizado -- una sola dependency de FastAPI (`require_agent_key`)
más un middleware de Starlette (`AgentScopeMiddleware`) que corren para
TODO el árbol de rutas, sin `if` sueltos dentro de cada endpoint:

  1. Autenticación: header `X-Api-Key` contra la env var
     `COMPRASAI_AGENT_KEY`.
       * Si la env var no está definida -> "modo agente" deshabilitado: el
         header se ignora por completo, la app se comporta exactamente
         igual que hoy (no rompe la demo ni el frontend, que nunca manda
         ese header).
       * Si el header no viene -> el request sigue como un request normal
         del frontend/humano (sin scope de agente, sin restricciones
         nuevas). Los endpoints que SÍ requieren agente explícitamente
         (ej. el manifest) usan `require_agent_key` y exigen el header por
         su cuenta.
       * Si el header viene pero no coincide con la key configurada -> 401.
       * Si coincide -> el request queda marcado como "agente"
         (`request.state.is_agent = True`) y se le aplica el scope.

  2. Scope (solo aplica a requests ya autenticados como agente):
       * GET permitido, salvo una lista explícita de rutas GET bloqueadas
         (ej. exportar-sap: exporta/confirma pedidos aprobados a SAP).
       * Cualquier otro método (POST/PUT/DELETE) bloqueado, salvo una
         lista explícita de "generación de propuestas" (hoy son GET, se
         deja la lista por si en el futuro se exponen también como POST).
       * Catálogo de keywords (decidir/aprobar/rechazar/confirmar/
         exportar-sap) como red de seguridad extra: si mañana se agrega un
         endpoint nuevo con ese patrón y alguien olvida actualizar la
         lista explícita, igual queda bloqueado.
"""

from __future__ import annotations

import os

from fastapi import Header, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

AGENT_KEY_HEADER = "X-Api-Key"
AGENT_KEY_ENV_VAR = "COMPRASAI_AGENT_KEY"

# Rutas (metodo, path) explícitamente bloqueadas para el agente aunque el
# método sea GET (exportar-sap) o encajen en el patrón de "decidir".
BLOCKED_AGENT_ROUTES: set[tuple[str, str]] = {
    ("GET", "/api/engines/sugeridos/exportar-sap"),
    ("POST", "/api/engines/sugeridos/decidir"),
}

# Únicas rutas de escritura permitidas al agente: "generación de propuestas"
# (RF del ticket T24). Hoy están implementadas como GET (ya cubiertas por la
# regla "todo GET" de abajo); se listan explícitamente por si en el futuro
# alguna cambia a POST.
ALLOWED_AGENT_WRITE_PATHS: set[str] = {
    "/api/engines/sugeridos/generar",
    "/api/balanceos/propuestas",
    "/api/remates/detectar",
}

# Red de seguridad: cualquier ruta que contenga alguna de estas palabras
# queda bloqueada para el agente sin importar el método, aunque no esté en
# BLOCKED_AGENT_ROUTES (cubre endpoints nuevos que no se hayan enumerado).
BLOCKED_KEYWORDS: tuple[str, ...] = ("decidir", "aprobar", "rechazar", "confirmar", "exportar-sap")


def get_configured_agent_key() -> str | None:
    """Se lee del entorno EN CADA LLAMADA (no como constante de módulo) para
    que:
      a) los tests puedan hacer monkeypatch de la env var sin recargar `app`.
      b) rotar la key en el servidor solo requiera reiniciar el proceso
         (systemd EnvironmentFile), no tocar código.
    """
    return os.environ.get(AGENT_KEY_ENV_VAR) or None


def is_agent_mode_enabled() -> bool:
    return get_configured_agent_key() is not None


def is_blocked_for_agent(method: str, path: str) -> bool:
    """True si el rol agente NO puede ejecutar `method path`."""
    method = method.upper()
    if (method, path) in BLOCKED_AGENT_ROUTES:
        return True
    if any(keyword in path for keyword in BLOCKED_KEYWORDS):
        return True
    if method == "GET":
        return False
    return path not in ALLOWED_AGENT_WRITE_PATHS


class AgentScopeMiddleware(BaseHTTPMiddleware):
    """Aplica el scope del agente a TODA la app cuando el request trae una
    `X-Api-Key` válida. Si no trae el header, o si el modo agente está
    deshabilitado (env var ausente), el request sigue exactamente igual que
    hoy -- el frontend/humano nunca manda este header, así que nunca se ve
    afectado."""

    async def dispatch(self, request: Request, call_next):
        api_key = request.headers.get(AGENT_KEY_HEADER)
        if api_key is None:
            return await call_next(request)

        configured_key = get_configured_agent_key()
        if configured_key is None:
            # Modo agente deshabilitado: no se otorga ningún privilegio ni se
            # rechaza el request por traer un header que nadie pidió.
            return await call_next(request)

        if api_key != configured_key:
            return JSONResponse({"detail": "X-Api-Key inválida."}, status_code=401)

        request.state.is_agent = True
        if is_blocked_for_agent(request.method, request.url.path):
            return JSONResponse(
                {
                    "detail": (
                        "Este endpoint requiere confirmación/aprobación humana en la app; "
                        "el agente solo puede consultar y proponer."
                    )
                },
                status_code=403,
            )
        return await call_next(request)


async def require_agent_key(x_api_key: str | None = Header(default=None, alias=AGENT_KEY_HEADER)) -> bool:
    """Dependency para endpoints que SIEMPRE requieren identidad de agente
    (ej. GET /api/agent/manifest), independientemente de si el header viene
    o no -- a diferencia del middleware, que solo actúa cuando el header
    está presente."""
    configured_key = get_configured_agent_key()
    if configured_key is None:
        raise HTTPException(status_code=503, detail="Modo agente deshabilitado: COMPRASAI_AGENT_KEY no está configurada.")
    if x_api_key is None:
        raise HTTPException(status_code=401, detail="Falta header X-Api-Key.")
    if x_api_key != configured_key:
        raise HTTPException(status_code=401, detail="X-Api-Key inválida.")
    return True
