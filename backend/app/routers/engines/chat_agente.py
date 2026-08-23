"""C3 - Explicabilidad (RN-12) + chat del planeador con tool calling real.

Router delgado a proposito: toda la logica de negocio (provider abstraction
LLM/plantilla, C1-lite/C2-lite, prompts, loop agentico) vive en
`backend/agente_c3.py` (fuera de app/), tal como pide el ticket T6. Este
router solo expone esa logica como endpoints HTTP, siguiendo la convencion
de motores de app/routers/engines/README_MOTORES.py."""

import sqlite3
from typing import Generator, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.db import get_connection, get_db

import agente_c3

router = APIRouter(prefix="/api/engines/chat_agente", tags=["C3-agente"])


@router.get("/explicar/{material_id}/{plant}")
def explicar(material_id: str, plant: str, db: sqlite3.Connection = Depends(get_db)):
    """RN-12: sugerido (C1/C2) + explicacion en lenguaje natural."""
    try:
        return agente_c3.explicar_sugerido(db, material_id, plant)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


class MensajeChat(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    """Contrato real de frontend/src/hooks/useChatStream.js (T12): el mensaje
    actual va aparte en `message` y `history` trae el resto de la
    conversacion SIN el mensaje actual. Se acepta tambien `mensajes` (lista
    unica, incluyendo el actual) por compatibilidad con integraciones
    directas al API que no pasen por ese hook."""

    message: Optional[str] = None
    history: list[MensajeChat] = []
    mensajes: Optional[list[MensajeChat]] = None

    def a_lista_mensajes(self) -> list:
        if self.mensajes is not None:
            return [{"role": m.role, "content": m.content} for m in self.mensajes]
        lista = [{"role": m.role, "content": m.content} for m in self.history]
        if self.message:
            lista.append({"role": "user", "content": self.message})
        return lista


def _stream_con_conexion_propia(mensajes: list) -> Generator[str, None, None]:
    """IMPORTANTE: no usar `Depends(get_db)` aquí. Esa dependencia cierra la
    conexión en cuanto el endpoint retorna el objeto StreamingResponse -- que
    pasa ANTES de que el generador de streaming se itere -- y truena con
    'Cannot operate on a closed database' a medio streaming. En su lugar,
    esta función abre y mantiene su propia conexión viva durante todo el
    tiempo de vida del generador (se abre/cierra al iterarlo, no antes)."""
    with get_connection() as db:
        yield from agente_c3.chat_stream(db, mensajes)


def chat_response(payload: ChatRequest) -> StreamingResponse:
    mensajes = payload.a_lista_mensajes()
    return StreamingResponse(_stream_con_conexion_propia(mensajes), media_type="text/event-stream")


@router.post("/chat")
def chat(payload: ChatRequest):
    """Chat del planeador con tool calling real (SSE). Tambien disponible
    como alias literal en POST /api/chat (ver app/main.py)."""
    return chat_response(payload)
