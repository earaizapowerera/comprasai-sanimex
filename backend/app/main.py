"""
ComprasAI Sanimex - API Core.

Sirve:
  - Endpoints REST bajo /api/* (materiales, sucursales, inventarios, kpis, ventas)
  - Build estático del frontend (T5) en la raíz "/"
  - Punto de montaje /api/engines/* para los motores C1/C2/C3 (T4/T5/T6)

Deploy detrás de nginx bajo el path /comprasAI (ver deploy/nginx-comprasAI.conf.example).
nginx hace strip del prefijo y reenvía a la raíz de este servicio; por eso se
arranca uvicorn con --root-path "$ROOT_PATH" (ver Dockerfile) para que
OpenAPI y las URLs generadas incluyan el prefijo correcto.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import AUTO_SEED_IF_MISSING, DB_PATH, FRONTEND_STATIC_DIR
from app.routers import engines_status, inventarios, kpis, materiales, sucursales, ventas
from app.routers.engines import chat_agente

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("comprasai")

app = FastAPI(
    title="ComprasAI Sanimex - API Core",
    description="Planeación Comercial, Inventarios y Abastecimiento con IA — Demo Fase 1",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _ensure_dataset() -> None:
    if DB_PATH.exists():
        logger.info("Usando dataset existente en %s", DB_PATH)
        return
    if not AUTO_SEED_IF_MISSING:
        logger.warning("DB %s no existe y AUTO_SEED_IF_MISSING=0. La API arrancará sin datos.", DB_PATH)
        return
    logger.info("DB %s no existe, generando dataset sintético automáticamente...", DB_PATH)
    from data.seed_sintetico import generate  # import diferido: evita costo si ya hay .db

    generate(DB_PATH)


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok", "db_path": str(DB_PATH), "db_exists": DB_PATH.exists()}


app.include_router(materiales.router)
app.include_router(sucursales.router)
app.include_router(inventarios.router)
app.include_router(kpis.router)
app.include_router(ventas.router)
app.include_router(engines_status.router)
app.include_router(chat_agente.router)
# Los motores T4/T5 (sugeridos, forecast) se registran aquí cuando aterricen.
# Ver app/routers/engines/README_MOTORES.py


@app.post("/api/chat", tags=["C3-agente"])
def chat_alias(payload: chat_agente.ChatRequest):
    """Alias literal pedido por el ticket T6: mismo handler que
    POST /api/engines/chat_agente/chat, expuesto también en /api/chat."""
    return chat_agente.chat_response(payload)

# Frontend estático (T5) — montado al final para que /api/* tenga prioridad.
if FRONTEND_STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_STATIC_DIR), html=True), name="frontend")
else:
    logger.warning("FRONTEND_STATIC_DIR %s no existe; no se monta el frontend estático.", FRONTEND_STATIC_DIR)
