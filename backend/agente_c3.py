"""
Agente C3 - ComprasAI Sanimex.

Capa agentica (IA) de la demo: EXPLICABILIDAD (RN-12) y CHAT del planeador
con tool calling real sobre los motores C1 (deterministas) y C2 (ML).

Regla de oro: este agente NUNCA calcula "a mano" el sugerido ni el forecast
en su propia redaccion -- consume los numeros que ya calcularon las
funciones C1-lite/C2-lite de este mismo modulo (que hacen las veces de T4/T5
mientras esos motores formales no aterricen) y SOLO redacta el razonamiento
o decide que tool invocar.

Proveedor de LLM: API de Anthropic (modelo claude-sonnet-5) cuando hay
ANTHROPIC_API_KEY en el entorno. Sin key, cae a un fallback deterministico
de plantillas que produce el MISMO formato de salida -- la demo NUNCA se
rompe en vivo, con o sin conexion al modelo.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import statistics
from typing import Any, Callable, Generator, Optional

logger = logging.getLogger("comprasai.agente_c3")

# --------------------------------------------------------------------------
# Config / abstraccion de proveedor LLM
# --------------------------------------------------------------------------

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()

_anthropic_client = None


def _get_anthropic_client():
    """Cliente anthropic singleton, o None si no hay API key configurada.

    Import perezoso: si el paquete `anthropic` no esta instalado y tampoco
    hay API key, nunca se intenta importar -- el fallback de plantillas
    sigue funcionando sin esa dependencia presente."""
    global _anthropic_client
    if not ANTHROPIC_API_KEY:
        return None
    if _anthropic_client is None:
        import anthropic

        _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client


def llm_disponible() -> bool:
    return bool(ANTHROPIC_API_KEY)


# --------------------------------------------------------------------------
# C2-lite: forecast por canal/material (media movil + exclusion de picos)
# --------------------------------------------------------------------------


def forecast_material(db: sqlite3.Connection, material_id: str, plant: str, meses_historial: int = 6) -> dict:
    """Forecast mensual (m2) de un material en una sucursal: media movil de
    los ultimos `meses_historial` meses, excluyendo picos atipicos (> 2.5x
    la mediana), mas una tendencia simple reciente-vs-antiguo."""
    filas = db.execute(
        """SELECT anio_mes, cantidad_m2 FROM ventas_mensuales
           WHERE material_id = ? AND plant = ?
           ORDER BY anio_mes DESC LIMIT ?""",
        (material_id, plant, meses_historial),
    ).fetchall()
    valores = [f["cantidad_m2"] for f in filas]

    if not valores:
        return {"forecast_mensual_m2": 0.0, "tendencia": "sin_datos", "meses_usados": 0, "picos_excluidos": 0}

    mediana = statistics.median(valores)
    umbral = mediana * 2.5 if mediana > 0 else max(valores)
    filtrados = [v for v in valores if v <= umbral] or valores
    picos_excluidos = len(valores) - len(filtrados)
    forecast_mensual = round(sum(filtrados) / len(filtrados), 2)

    tendencia = "estable"
    if len(filtrados) >= 4:
        mitad = len(filtrados) // 2
        recientes = filtrados[:mitad]  # la query viene ORDER BY anio_mes DESC
        antiguos = filtrados[mitad:]
        prom_reciente = sum(recientes) / len(recientes)
        prom_antiguo = sum(antiguos) / len(antiguos)
        if prom_antiguo > 0:
            variacion = (prom_reciente - prom_antiguo) / prom_antiguo
            if variacion > 0.10:
                tendencia = "creciente"
            elif variacion < -0.10:
                tendencia = "decreciente"

    return {
        "forecast_mensual_m2": forecast_mensual,
        "tendencia": tendencia,
        "meses_usados": len(filtrados),
        "picos_excluidos": picos_excluidos,
    }


# --------------------------------------------------------------------------
# C1-lite: sugerido de reabasto (disponible neto, cobertura, MOQ/pallet,
# transferencia antes que compra RN-02)
# --------------------------------------------------------------------------


def _redondear_a_multiplo(valor: float, multiplo: int) -> int:
    if not multiplo:
        return int(math.ceil(valor))
    return int(math.ceil(valor / multiplo) * multiplo)


def _buscar_excedente_transferible(
    db: sqlite3.Connection, material_id: str, plant_destino: str, meses_objetivo: float
) -> Optional[dict]:
    """RN-02: antes de sugerir compra, busca si otra sucursal tiene
    excedente de este material (disponible neto por encima de SU propio
    objetivo de cobertura) para transferir desde ahi."""
    otras = db.execute(
        "SELECT plant, disponible, transito, comprometido FROM inventarios WHERE material_id = ? AND plant != ?",
        (material_id, plant_destino),
    ).fetchall()

    mejor = None
    for fila in otras:
        disponible_neto = fila["disponible"] + fila["transito"] - fila["comprometido"]
        forecast_otra = forecast_material(db, material_id, fila["plant"])["forecast_mensual_m2"]
        objetivo_otra = forecast_otra * meses_objetivo
        excedente = disponible_neto - objetivo_otra
        if excedente > 0 and (mejor is None or excedente > mejor["excedente_m2"]):
            mejor = {"plant": fila["plant"], "excedente_m2": round(excedente, 2)}
    return mejor


def calcular_sugerido(db: sqlite3.Connection, material_id: str, plant: str) -> dict:
    """C1: sugerido de reabasto para un material+sucursal. Devuelve todos
    los numeros crudos que usa la capa de explicabilidad -- este es el
    UNICO lugar donde se decide compra/transferencia/sin_accion."""
    material = db.execute("SELECT * FROM materiales WHERE material_id = ?", (material_id,)).fetchone()
    if not material:
        raise ValueError(f"Material '{material_id}' no existe")
    sucursal = db.execute("SELECT * FROM sucursales WHERE plant = ?", (plant,)).fetchone()
    if not sucursal:
        raise ValueError(f"Sucursal '{plant}' no existe")

    inv = db.execute(
        "SELECT * FROM inventarios WHERE material_id = ? AND plant = ?", (material_id, plant)
    ).fetchone()
    disponible = inv["disponible"] if inv else 0.0
    transito = inv["transito"] if inv else 0.0
    comprometido = inv["comprometido"] if inv else 0.0
    disponible_neto = round(disponible + transito - comprometido, 2)

    cobertura_row = db.execute(
        "SELECT meses_objetivo FROM coberturas_objetivo WHERE material_id = ?", (material_id,)
    ).fetchone()
    meses_objetivo = cobertura_row["meses_objetivo"] if cobertura_row else 2.0

    forecast = forecast_material(db, material_id, plant)
    forecast_mensual = forecast["forecast_mensual_m2"]

    cobertura_actual_meses = round(disponible_neto / forecast_mensual, 2) if forecast_mensual > 0 else None

    objetivo_unidades_m2 = round(forecast_mensual * meses_objetivo, 2)
    faltante_m2 = round(objetivo_unidades_m2 - disponible_neto, 2)

    decision = "sin_accion"
    cantidad_sugerida_m2 = 0.0
    cantidad_sugerida_cajas = 0
    plant_origen_transferencia = None
    plant_origen_disponible_m2 = None

    if faltante_m2 > 0:
        origen = _buscar_excedente_transferible(db, material_id, plant, meses_objetivo)
        proveedor = db.execute("SELECT * FROM proveedores WHERE material_id = ?", (material_id,)).fetchone()
        m2_por_caja = material["m2_por_caja"] or 1.0

        if origen:
            decision = "transferencia"
            cantidad_sugerida_m2 = round(min(faltante_m2, origen["excedente_m2"]), 2)
            plant_origen_transferencia = origen["plant"]
            plant_origen_disponible_m2 = origen["excedente_m2"]
        else:
            decision = "compra"
            cantidad_sugerida_m2 = faltante_m2

        cajas_necesarias = cantidad_sugerida_m2 / m2_por_caja if m2_por_caja else 0
        if proveedor:
            moq = proveedor["moq_cajas"] or 1
            por_pallet = proveedor["cajas_por_pallet"] or moq
            cantidad_sugerida_cajas = max(moq, _redondear_a_multiplo(cajas_necesarias, por_pallet))
        else:
            cantidad_sugerida_cajas = int(math.ceil(cajas_necesarias))

    return {
        "material_id": material_id,
        "plant": plant,
        "descripcion": material["descripcion"],
        "sucursal_nombre": sucursal["nombre"],
        "disponible": disponible,
        "transito": transito,
        "comprometido": comprometido,
        "disponible_neto": disponible_neto,
        "forecast_mensual_m2": forecast_mensual,
        "tendencia": forecast["tendencia"],
        "picos_excluidos": forecast["picos_excluidos"],
        "cobertura_actual_meses": cobertura_actual_meses,
        "cobertura_objetivo_meses": meses_objetivo,
        "objetivo_unidades_m2": objetivo_unidades_m2,
        "faltante_m2": max(faltante_m2, 0.0),
        "decision": decision,
        "cantidad_sugerida_m2": round(cantidad_sugerida_m2, 2),
        "cantidad_sugerida_cajas": cantidad_sugerida_cajas,
        "plant_origen_transferencia": plant_origen_transferencia,
        "plant_origen_disponible_m2": plant_origen_disponible_m2,
    }


def consultar_inventario(db: sqlite3.Connection, material_id: str, plant: Optional[str] = None) -> dict:
    material = db.execute("SELECT descripcion FROM materiales WHERE material_id = ?", (material_id,)).fetchone()
    if not material:
        return {"error": f"Material '{material_id}' no existe"}

    if plant:
        inv = db.execute(
            "SELECT * FROM inventarios WHERE material_id = ? AND plant = ?", (material_id, plant)
        ).fetchone()
        if not inv:
            return {
                "material_id": material_id,
                "descripcion": material["descripcion"],
                "plant": plant,
                "disponible_neto": 0.0,
                "nota": "Sin registro de inventario para esa sucursal",
            }
        disponible_neto = inv["disponible"] + inv["transito"] - inv["comprometido"]
        return {
            "material_id": material_id,
            "descripcion": material["descripcion"],
            "plant": plant,
            "disponible": inv["disponible"],
            "transito": inv["transito"],
            "comprometido": inv["comprometido"],
            "disponible_neto": round(disponible_neto, 2),
        }

    filas = db.execute(
        "SELECT plant, disponible, transito, comprometido FROM inventarios WHERE material_id = ?", (material_id,)
    ).fetchall()
    return {
        "material_id": material_id,
        "descripcion": material["descripcion"],
        "sucursales": [
            {**f, "disponible_neto": round(f["disponible"] + f["transito"] - f["comprometido"], 2)} for f in filas
        ],
    }


def buscar_materiales(db: sqlite3.Connection, texto: str, limite: int = 10) -> dict:
    patron = f"%{texto}%"
    filas = db.execute(
        """SELECT material_id, descripcion, familia, abc FROM materiales
           WHERE descripcion LIKE ? OR familia LIKE ? OR material_id LIKE ?
           LIMIT ?""",
        (patron, patron, patron, limite),
    ).fetchall()
    return {"resultados": filas, "total": len(filas)}


# --------------------------------------------------------------------------
# Explicabilidad (RN-12)
# --------------------------------------------------------------------------

SYSTEM_PROMPT_EXPLICABILIDAD = (
    "Eres el motor de explicabilidad de ComprasAI Sanimex (capa C3, agente). "
    "Tu unico trabajo es REDACTAR en espanol claro, en 3 a 5 oraciones, el razonamiento "
    "detras de un sugerido de reabasto que YA fue calculado por los motores C1/C2. "
    "NUNCA inventes ni recalcules numeros: usa EXCLUSIVAMENTE los valores que se te dan. "
    "Explica la cobertura actual vs la cobertura objetivo, el forecast y su tendencia "
    "(menciona si se excluyeron picos atipicos del historial), y por que se sugiere "
    "comprar, transferir o no hacer nada -- recordando la regla de negocio RN-02: "
    "siempre se prioriza transferir stock de otra sucursal antes que comprar. "
    "Tono profesional y directo para un planeador de compras experto. "
    "Responde en texto plano, sin markdown."
)


def _prompt_explicabilidad(sugerido: dict) -> str:
    return (
        "Datos del sugerido ya calculados por C1/C2 (no los recalcules, solo explicalos):\n"
        f"{json.dumps(sugerido, ensure_ascii=False, indent=2, default=str)}\n\n"
        "Redacta la explicacion en espanol para el planeador."
    )


def _generar_explicacion_llm(sugerido: dict) -> Optional[str]:
    client = _get_anthropic_client()
    if client is None:
        return None
    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=500,
            system=SYSTEM_PROMPT_EXPLICABILIDAD,
            messages=[{"role": "user", "content": _prompt_explicabilidad(sugerido)}],
        )
        texto = "".join(block.text for block in response.content if block.type == "text").strip()
        return texto or None
    except Exception as exc:  # pragma: no cover - resiliencia de demo en vivo
        logger.warning("Fallo LLM en explicabilidad, usando fallback de plantilla: %s", exc)
        return None


def _generar_explicacion_fallback(sugerido: dict) -> str:
    partes = []
    descripcion = sugerido.get("descripcion", sugerido.get("material_id"))
    plant = sugerido.get("plant")
    cobertura_actual = sugerido.get("cobertura_actual_meses")
    cobertura_objetivo = sugerido.get("cobertura_objetivo_meses")
    forecast = sugerido.get("forecast_mensual_m2")
    tendencia = sugerido.get("tendencia")
    picos = sugerido.get("picos_excluidos") or 0
    decision = sugerido.get("decision")

    if cobertura_actual is None:
        partes.append(
            f"'{descripcion}' en {plant} no tiene historial de ventas suficiente para estimar un forecast, "
            "por lo que no se puede calcular su cobertura."
        )
    else:
        nota_picos = f" (se excluyeron {picos} mes(es) con picos atipicos del historial)" if picos else ""
        partes.append(
            f"'{descripcion}' en {plant} tiene {cobertura_actual} meses de cobertura actual contra un "
            f"objetivo de {cobertura_objetivo} meses, con un forecast de {forecast} m2/mes y tendencia "
            f"{tendencia}{nota_picos}."
        )

    if decision == "sin_accion":
        partes.append("El inventario disponible neto ya cubre el objetivo, por lo que no se sugiere ninguna accion.")
    elif decision == "transferencia":
        partes.append(
            f"Se detecto un excedente de {sugerido.get('plant_origen_disponible_m2')} m2 en la sucursal "
            f"{sugerido.get('plant_origen_transferencia')}; siguiendo la regla de negocio de transferir antes "
            f"que comprar, se sugiere transferir {sugerido.get('cantidad_sugerida_m2')} m2 "
            f"({sugerido.get('cantidad_sugerida_cajas')} cajas) desde ahi."
        )
    elif decision == "compra":
        partes.append(
            f"No se encontro excedente transferible en otras sucursales, por lo que se sugiere comprar "
            f"{sugerido.get('cantidad_sugerida_m2')} m2 ({sugerido.get('cantidad_sugerida_cajas')} cajas, "
            "ya redondeado al MOQ/pallet del proveedor)."
        )

    return " ".join(partes)


def explicar_sugerido(db: sqlite3.Connection, material_id: str, plant: str) -> dict:
    """RN-12: calcula el sugerido (C1/C2) y lo devuelve junto con su
    explicacion en lenguaje natural (LLM si hay key, plantilla si no)."""
    sugerido = calcular_sugerido(db, material_id, plant)
    texto = _generar_explicacion_llm(sugerido)
    fuente = "llm"
    if texto is None:
        texto = _generar_explicacion_fallback(sugerido)
        fuente = "plantilla"
    return {**sugerido, "explicacion": texto, "fuente_explicacion": fuente}


# --------------------------------------------------------------------------
# Chat del planeador: tool calling real + streaming SSE
# --------------------------------------------------------------------------

SYSTEM_PROMPT_CHAT = (
    "Eres el asistente C3 de ComprasAI Sanimex: el copiloto del planeador de compras. "
    "Respondes preguntas sobre inventario, forecast y sugeridos de reabasto usando "
    "EXCLUSIVAMENTE las herramientas disponibles -- nunca inventes cifras ni calcules a mano. "
    "Si el planeador menciona un producto por nombre, usa buscar_materiales para encontrar su "
    "material_id antes de consultar inventario o calcular el sugerido. Recuerda la regla de "
    "negocio RN-02: siempre se transfiere stock de otra sucursal antes que comprar -- si el "
    "sugerido trae decision='transferencia', explicalo asi. Responde en espanol, tono "
    "profesional y conciso, como si hablaras con un planeador experto que no necesita "
    "explicaciones basicas de retail."
)

TOOLS = [
    {
        "name": "buscar_materiales",
        "description": (
            "Busca materiales por texto en descripcion, familia o material_id. Usalo cuando el "
            "planeador menciona un producto por nombre y no conoces su material_id exacto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"texto": {"type": "string", "description": "Texto a buscar, ej. 'porcelanato' o 'pared'"}},
            "required": ["texto"],
        },
    },
    {
        "name": "consultar_inventario",
        "description": (
            "Consulta el inventario disponible neto (disponible + transito - comprometido) de un "
            "material en una sucursal. Si se omite plant, regresa todas las sucursales con ese material."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "material_id": {"type": "string"},
                "plant": {"type": "string", "description": "Codigo de sucursal. Opcional."},
            },
            "required": ["material_id"],
        },
    },
    {
        "name": "calcular_forecast",
        "description": (
            "Calcula el forecast de ventas mensual en m2 (C2: media movil con exclusion de picos "
            "atipicos) de un material en una sucursal, incluyendo su tendencia."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"material_id": {"type": "string"}, "plant": {"type": "string"}},
            "required": ["material_id", "plant"],
        },
    },
    {
        "name": "calcular_sugerido",
        "description": (
            "Calcula el sugerido de reabasto (C1) para un material+sucursal: disponible neto, "
            "cobertura actual vs objetivo, forecast, y si conviene comprar o transferir de otra "
            "sucursal antes (RN-02), con redondeo a MOQ/pallet del proveedor."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"material_id": {"type": "string"}, "plant": {"type": "string"}},
            "required": ["material_id", "plant"],
        },
    },
]

TOOL_FUNCTIONS: dict[str, Callable[..., dict]] = {
    "buscar_materiales": buscar_materiales,
    "consultar_inventario": consultar_inventario,
    "calcular_forecast": forecast_material,
    "calcular_sugerido": calcular_sugerido,
}


def _ejecutar_tool(db: sqlite3.Connection, nombre: str, tool_input: dict) -> dict:
    fn = TOOL_FUNCTIONS.get(nombre)
    if fn is None:
        return {"error": f"Tool desconocida: {nombre}"}
    try:
        resultado = fn(db, **tool_input)
        return resultado if isinstance(resultado, dict) else {"resultado": resultado}
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # pragma: no cover - resiliencia de demo en vivo
        logger.warning("Fallo ejecutando tool '%s': %s", nombre, exc)
        return {"error": f"Error interno ejecutando {nombre}: {exc}"}


# Contrato SSE consumido por frontend/src/hooks/useChatStream.js (T12):
# frames "data: {...}\n\n" (sin linea `event:`) con el tipo embebido en el
# JSON como campo "type". Ver el docstring de ese hook para el contrato
# completo -- este modulo debe emitir EXACTAMENTE esas formas.
TOOL_LABELS = {
    "buscar_materiales": "Buscando materiales...",
    "consultar_inventario": "Consultando inventario...",
    "calcular_forecast": "Calculando forecast (C2)...",
    "calcular_sugerido": "Calculando sugerido de reabasto (C1)...",
}

TOOL_LAYER = {
    "buscar_materiales": None,
    "consultar_inventario": "C1",
    "calcular_forecast": "C2",
    "calcular_sugerido": "C1",
}


def _sse(tipo: str, **campos) -> str:
    payload = {"type": tipo, **campos}
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _extraer_texto_ultimo_usuario(mensajes: list) -> str:
    for msg in reversed(mensajes):
        if msg.get("role") != "user":
            continue
        contenido = msg.get("content")
        if isinstance(contenido, str):
            return contenido
        if isinstance(contenido, list):
            return " ".join(b.get("text", "") for b in contenido if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _detectar_material_plant(db: sqlite3.Connection, texto: str) -> tuple:
    tokens = [t.strip(".,;:()¿?") for t in texto.upper().split()]
    material_id = None
    plant = None
    for t in tokens:
        if not t:
            continue
        if not material_id and db.execute("SELECT 1 FROM materiales WHERE material_id = ?", (t,)).fetchone():
            material_id = t
        if not plant and db.execute("SELECT 1 FROM sucursales WHERE plant = ?", (t,)).fetchone():
            plant = t
        if material_id and plant:
            break
    return material_id, plant


def _split_en_chunks(texto: str, palabras_por_chunk: int = 10) -> Generator[str, None, None]:
    palabras = texto.split(" ")
    buffer: list = []
    for palabra in palabras:
        buffer.append(palabra)
        if len(buffer) >= palabras_por_chunk:
            yield " ".join(buffer) + " "
            buffer = []
    if buffer:
        yield " ".join(buffer)


def _chat_fallback(db: sqlite3.Connection, mensajes: list) -> Generator[str, None, None]:
    """Fallback deterministico sin LLM: si detecta un material_id + plant
    conocidos en el ultimo mensaje del planeador, calcula el sugerido real y
    lo explica con plantilla; si no, da instrucciones de uso."""
    ultimo = _extraer_texto_ultimo_usuario(mensajes)
    texto = (
        "Modo plantilla (sin conexion al modelo Claude): puedo ayudarte a consultar inventario, "
        "forecast y sugeridos de compra/transferencia. Dime el material_id y la sucursal (plant) "
        "que te interesa, por ejemplo: 'sugerido para MAT-0123 en PLANT-05'."
    )
    material_id, plant = _detectar_material_plant(db, ultimo)
    if material_id and plant:
        try:
            sugerido = calcular_sugerido(db, material_id, plant)
            texto = _generar_explicacion_fallback(sugerido)
        except ValueError:
            pass

    for chunk in _split_en_chunks(texto):
        yield _sse("token", content=chunk)
    if material_id and plant:
        yield _sse("source", label=f"Sugerido {material_id} / {plant}", layer="C1")
    yield _sse("done", stop_reason="fallback")


def chat_stream(db: sqlite3.Connection, mensajes: list, max_turns: int = 6) -> Generator[str, None, None]:
    """Genera frames SSE `data: {"type": "token|tool_call|tool_end|source|done|error", ...}`
    (contrato de frontend/src/hooks/useChatStream.js, T12) para el chat del
    planeador. Con ANTHROPIC_API_KEY: loop agentico manual con streaming
    real y tool calling (ver skill claude-api, patron 'Streaming Manual
    Loop'). Sin key, o si el LLM falla en vivo: fallback de plantillas."""
    client = _get_anthropic_client()
    if client is None:
        yield from _chat_fallback(db, mensajes)
        return

    conversacion = list(mensajes)
    try:
        for _ in range(max_turns):
            with client.messages.stream(
                model=ANTHROPIC_MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT_CHAT,
                tools=TOOLS,
                messages=conversacion,
            ) as stream:
                for text in stream.text_stream:
                    yield _sse("token", content=text)
                response = stream.get_final_message()

            if response.stop_reason == "pause_turn":
                conversacion.append({"role": "assistant", "content": response.content})
                continue

            if response.stop_reason == "tool_use":
                conversacion.append({"role": "assistant", "content": response.content})
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    yield _sse("tool_call", label=TOOL_LABELS.get(block.name, f"Consultando {block.name}..."))
                    resultado = _ejecutar_tool(db, block.name, block.input)
                    es_error = isinstance(resultado, dict) and "error" in resultado
                    tool_result = {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(resultado, ensure_ascii=False, default=str),
                    }
                    if es_error:
                        tool_result["is_error"] = True
                    tool_results.append(tool_result)
                    yield _sse("tool_end")
                    layer = TOOL_LAYER.get(block.name)
                    if layer and not es_error:
                        label = resultado.get("descripcion") or resultado.get("material_id") or block.name
                        yield _sse("source", label=str(label), layer=layer)
                conversacion.append({"role": "user", "content": tool_results})
                continue

            # end_turn, max_tokens, refusal, etc. -- fin del loop
            yield _sse("done", stop_reason=response.stop_reason)
            return

        yield _sse("done", stop_reason="max_turns_alcanzado")
    except Exception as exc:  # pragma: no cover - resiliencia de demo en vivo
        logger.warning("Fallo LLM en chat, usando fallback de plantilla: %s", exc)
        yield _sse("error", message="El modelo no respondio a tiempo, cambiando a modo plantilla.")
        yield from _chat_fallback(db, mensajes)
