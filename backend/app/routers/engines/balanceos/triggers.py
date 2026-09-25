"""Balanceos v2 (waykee 292187) -- funciones puras del motor de triggers.

Sin I/O: reciben los números ya calculados (mismo criterio de
disponible_neto/demanda/cobertura que propuestas._compute_all_propuestas y que
COBERTURA_CTE en routers/inventarios.py) y devuelven una decisión. Full
unit-test coverage en tests/test_balanceos_triggers.py.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from app.routers.semaforo import _fecha_pedido_simulada

def calc_cajas_a_m2(cajas: float, m2_por_caja: Optional[float]) -> float:
    """Inversa de calc_m2_a_cajas (sugeridos.py): cajas -> m2 para mostrar
    "metros" en el Grid 1 de Balanceos. Solo es para display (no alimenta
    ninguna decisión de compra/traslado), por eso no lleva el guard de
    redondeo hacia arriba de calc_m2_a_cajas."""
    if not m2_por_caja or m2_por_caja <= 0:
        return round(cajas, 2)
    return round(cajas * m2_por_caja, 2)


def estado_semaforo_balanceo(disponible_neto: float, cobertura: Optional[float], objetivo: float) -> str:
    """Clasifica quiebre/riesgo/ok/exceso/sin_dato con los MISMOS umbrales
    que COBERTURA_CTE en routers/inventarios.py (T8, waykee 290093) -- única
    fuente de verdad del semáforo rojo/amarillo/verde en toda la app. Para
    los triggers de Balanceos v2, "Rojo" = estado 'quiebre' (ver es_rojo)."""
    if disponible_neto <= 0:
        return "quiebre"
    if cobertura is None:
        return "sin_dato"
    if cobertura < objetivo * 0.5:
        return "quiebre"
    if cobertura < objetivo:
        return "riesgo"
    if cobertura > objetivo * 2.5:
        return "exceso"
    return "ok"


def es_rojo(estado: str) -> bool:
    return estado == "quiebre"


def calc_dias_desde_pedido(material_id: str, plant: str, hoy: date) -> int:
    """SUPUESTO documentado (Trigger 2, waykee 292187): el dataset NO tiene
    pedidos_compra_detalle (confirmado: tabla ausente en schema.sql y "no
    such table" al consultarla), solo el agregado inventarios.pedidos_abiertos
    (cantidad, sin fecha por OC). Se reusa la MISMA fecha simulada
    determinística (hash MD5 material_id+plant) que ya usa semaforo.py
    (_fecha_pedido_simulada) en vez de inventar un mecanismo nuevo: así un
    mismo material+sucursal muestra la misma antigüedad de pedido en la
    pantalla Semáforo y en Balanceos, en lugar de dos números contradictorios
    para el mismo dato inexistente. Cuando T1 entregue pedidos_compra_detalle
    real, esta función se reemplaza por MIN(fecha_po) real."""
    fecha_pedido = _fecha_pedido_simulada(material_id, plant, hoy)
    return (hoy - fecha_pedido).days


def resumir_pedidos_compra(documentos: list[dict], plant: str, hoy: date) -> dict:
    """Backorder de compra de UNA sucursal a partir del detalle real por OC
    (waykee 292243). Regla de negocio (Enrique): la OC indica el almacén
    donde se recibe y solo cuenta en la sucursal receptora. El receptor es
    pedidos_compra_detalle.plant = EKPO.WERKS de la línea de la OC (su
    almacén EKPO.LGORT pertenece a ese mismo centro, p.ej. M416/B416).
    Por eso se filtra por plant aquí mismo aunque el llamador ya lo haga:
    una OC de otra sucursal de la zona nunca debe sumar en esta fila.

    Antigüedad = MIN(fecha_po) de las OCs pendientes (la más vieja manda
    para el Trigger 2). numero = OCs distintas, no líneas."""
    propios = [
        d for d in documentos
        if d["plant"] == plant and (d["cantidad_pendiente"] or 0) > 0
    ]
    cajas = round(sum(d["cantidad_pendiente"] for d in propios), 2)
    fechas = [date.fromisoformat(d["fecha_po"]) for d in propios if d["fecha_po"]]
    return {
        "cajas": cajas,
        "numeroPedidos": len({d["po"] for d in propios}),
        "diasDesdePedido": (hoy - min(fechas)).days if fechas else None,
    }


def evaluar_trigger(
    disponible_neto: float,
    cobertura: Optional[float],
    objetivo: float,
    pedidos_abiertos: float,
    dias_desde_pedido: Optional[int],
    umbral_dias: int,
    hay_alternativa_en_zona: bool,
) -> Optional[dict]:
    """Decide si un par material+sucursal dispara una sugerencia de balanceo
    (spec cerrada de Enrique, waykee 292187, 23-sep-2026):
      T1 - rojo SIN pedido de compra pendiente -> siempre sugerir.
      T2 - rojo CON pedido pendiente -> si dias_desde_pedido <= umbral_dias,
           NO sugerir (se asume que llega); si lo excede, SÍ sugerir.
      T3 (zona) - aplica a T1 y T2: solo si existe al menos otra ubicación en
           la MISMA zona (== corredor, ver _compute_grid1) que NO está en
           rojo para ese material. Si toda la zona está en rojo, no hay de
           dónde balancear.
    Retorna None si no dispara; si dispara, un dict con 'trigger' en
    {'sin_pedido', 'con_pedido_vencido'} y el detalle usado en la decisión.

    Golden cases:
      - rojo, sin pedido, con alternativa -> dispara 'sin_pedido' sin
        importar días (test_evaluar_trigger_sin_pedido_siempre_dispara).
      - rojo, con pedido, dias=10, umbral=30 -> no dispara (aún puede llegar).
      - rojo, con pedido, dias=45, umbral=30 -> dispara 'con_pedido_vencido'.
      - rojo pero SIN alternativa en zona -> nunca dispara (T3).
      - no rojo (riesgo/ok/exceso) -> nunca dispara.
    """
    estado = estado_semaforo_balanceo(disponible_neto, cobertura, objetivo)
    if not es_rojo(estado):
        return None
    if not hay_alternativa_en_zona:
        return None
    if pedidos_abiertos and pedidos_abiertos > 0:
        if dias_desde_pedido is not None and dias_desde_pedido <= umbral_dias:
            return None
        return {
            "trigger": "con_pedido_vencido",
            "diasDesdePedido": dias_desde_pedido,
            "umbralDias": umbral_dias,
        }
    return {"trigger": "sin_pedido"}


def permite_transferencia_por_prioridad(
    prioridad_origen: float,
    prioridad_destino: float,
    excedente_origen: float,
) -> bool:
    """RN prioridad entre sucursales (waykee 292187, spec cerrada):
      - Si origen tiene excedente real (sobre-inventario), la prioridad se
        IGNORA SIEMPRE -- el excedente manda, se permite la transferencia.
      - Si NO hay excedente en origen: se protege el consumo de origen si su
        prioridad efectiva es mayor que la de destino (no se sugiere).

    SUPUESTO de interpretación (Enrique no detalló cómo cruza la tabla
    balanceo_prioridad con "mayor consumo"; decidido aquí sin más preguntas,
    igual que el supuesto de remates >30 cajas): balanceo_prioridad(material_id,
    plant, prioridad) es un override EXPLÍCITO -- mayor valor = más protegido.
    Cuando no hay override para una ubicación, el llamador (_prioridad_efectiva)
    usa su demanda_mensual como proxy implícito de prioridad, que es
    exactamente el criterio literal del ticket ("si el posible origen tiene
    MAYOR CONSUMO que el destino"). Esta función solo compara los valores ya
    resueltos, sea cual sea su fuente.
    """
    if excedente_origen > 0:
        return True
    return not (prioridad_origen > prioridad_destino)


def calc_cantidad_sugerida_balanceo(
    disponible_neto_origen: float,
    demanda_origen: float,
    disponible_neto_destino: float,
    demanda_destino: float,
    meses_objetivo_destino: float,
    es_cedis_origen: bool,
    destino_tiene_mayor_prioridad: bool,
) -> dict:
    """Cantidad sugerida (en cajas) para prellenar el modal "Agregar" de
    Grid 1 (waykee 292187). Algoritmo de referencia: Enrique lo validará con
    el cliente después; la cantidad SIEMPRE queda editable a mano en el
    modal -- esto solo prellena un valor con su fuente visible, nunca postea
    solo.

    Base: cubrir el déficit de destino hasta su meses_objetivo, sin dejar a
    origen con menos meses de cobertura que destino tras la transferencia
    (tope: emparejar meses entre origen y destino, nunca invertir el
    problema) -- EXCEPTO si destino tiene mayor prioridad que origen, caso
    en el que ese tope no aplica. Caso especial CEDIS: como origen casi
    siempre es CEDIS (no vende al público en el mismo sentido que una
    sucursal), CEDIS NO se limita por "emparejar meses", solo por las cajas
    realmente disponibles ahí.

    Derivación del tope "emparejar meses" (x = cajas a transferir):
        meses_destino_final = (disponible_neto_destino + x) / demanda_destino
        meses_origen_final  = (disponible_neto_origen  - x) / demanda_origen
      Igualando y despejando x:
        x_max = (disponible_neto_origen*demanda_destino - disponible_neto_destino*demanda_origen)
                / (demanda_origen + demanda_destino)

    Golden case 1: origen(disp=200, dem=20), destino(disp=10, dem=20,
    objetivo=2) -> cantidad_para_objetivo=30, x_max=95 -> final=30 (cubre
    déficit completo; origen queda en 8.5 meses, destino queda exacto en 2.0
    = objetivo).
    Golden case 2: origen(disp=40, dem=20), destino(disp=0, dem=10,
    objetivo=2) -> cantidad_para_objetivo=20, x_max=13.33 -> final=13.33
    (origen y destino quedan emparejados en 1.33 meses cada uno).
    """
    cantidad_para_objetivo = max(0.0, meses_objetivo_destino * demanda_destino - disponible_neto_destino)

    if es_cedis_origen:
        tope = disponible_neto_origen
        fuente_tope = "solo_disponible_cedis"
    elif destino_tiene_mayor_prioridad:
        tope = disponible_neto_origen
        fuente_tope = "prioridad_destino_sin_tope_meses"
    else:
        denom = demanda_origen + demanda_destino
        if denom <= 0:
            x_max = disponible_neto_origen
        else:
            x_max = (disponible_neto_origen * demanda_destino - disponible_neto_destino * demanda_origen) / denom
        tope = min(disponible_neto_origen, max(0.0, x_max))
        fuente_tope = "emparejar_meses_origen_destino"

    tope = max(0.0, tope)
    cantidad_final = round(min(cantidad_para_objetivo, tope), 2)
    return {
        "cantidadSugerida": cantidad_final,
        "cantidadParaObjetivo": round(cantidad_para_objetivo, 2),
        "tope": round(tope, 2),
        "fuenteTope": fuente_tope,
    }
