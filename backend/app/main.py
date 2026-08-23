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

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import AUTO_SEED_IF_MISSING, DB_PATH, FRONTEND_STATIC_DIR
from app.core.db import get_db
from app.routers import engines_status, inventarios, kpis, materiales, semaforo, sucursales, ventas
from app.routers.engines import balanceos as engine_balanceos
from app.routers.engines import chat_agente
from app.routers.engines import forecast as engine_forecast
from app.routers.engines import remates as engine_remates
from app.routers.engines import sugeridos as engine_sugeridos

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
app.include_router(engine_sugeridos.router)
app.include_router(semaforo.router)
app.include_router(engine_forecast.router)
app.include_router(engine_balanceos.router)
app.include_router(engine_remates.router)
# Ver app/routers/engines/README_MOTORES.py


@app.post("/api/chat", tags=["C3-agente"])
def chat_alias(payload: chat_agente.ChatRequest):
    """Alias literal pedido por el ticket T6: mismo handler que
    POST /api/engines/chat_agente/chat, expuesto también en /api/chat."""
    return chat_agente.chat_response(payload)


@app.get("/api/forecast/{material_id}/{plant_o_canal}", tags=["C2-forecast"])
def forecast_alias(material_id: str, plant_o_canal: str, db=Depends(get_db)):
    """Alias literal pedido por el ticket T5: mismo handler que
    GET /api/engines/forecast/{material_id}/{plant_o_canal}."""
    return engine_forecast.forecast_material_canal(material_id, plant_o_canal, db)


@app.get("/api/tendencias/ganadores", tags=["C2-forecast"])
def tendencias_ganadores_alias(canal: str | None = None, limit: int = 50, db=Depends(get_db)):
    """Alias literal pedido por el ticket T5: mismo handler que
    GET /api/engines/forecast/tendencias/ganadores."""
    return engine_forecast.tendencias_ganadores(canal, limit, db)


@app.get("/api/forecast/precision", tags=["C2-forecast"])
def forecast_precision_alias(
    material_id: str | None = None,
    plant_o_canal: str | None = None,
    sample_size: int = 100,
    db=Depends(get_db),
):
    """Alias literal pedido por el ticket T5: mismo handler que
    GET /api/engines/forecast/precision."""
    return engine_forecast.precision_forecast(material_id, plant_o_canal, sample_size, db)

# Frontend estático (T5) — montado al final para que /api/* tenga prioridad.
if FRONTEND_STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_STATIC_DIR), html=True), name="frontend")
else:
    logger.warning("FRONTEND_STATIC_DIR %s no existe; no se monta el frontend estático.", FRONTEND_STATIC_DIR)
