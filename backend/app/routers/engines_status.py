"""Endpoint placeholder que confirma el punto de montaje para T4/T5/T6.
Ver app/routers/engines/README_MOTORES.py para instrucciones de cómo
registrar un motor nuevo (C1 deterministas, C2 ML, C3 agente)."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/engines", tags=["engines"])

MOTORES_ESPERADOS = [
    {"nombre": "sugeridos", "capa": "C1", "descripcion": "Disponible, cobertura vs objetivo, redondeo MOQ/pallet, transferencia antes que compra"},
    {"nombre": "remates", "capa": "C1", "descripcion": "Motor de remates minuta GAM (escalas 1-3/4-10/11-14/15-30 cajas, ruteo por organización)"},
    {"nombre": "forecast", "capa": "C2", "descripcion": "Forecast por canal (media móvil + estacionalidad, exclusión de picos atípicos)"},
    {"nombre": "chat_agente", "capa": "C3", "descripcion": "Explicabilidad en lenguaje natural + chat del planeador"},
]


@router.get("/status")
def engines_status():
    return {
        "mensaje": "Punto de montaje listo. Los motores T4/T5/T6 se registran en app/main.py.",
        "motores_esperados": MOTORES_ESPERADOS,
    }
