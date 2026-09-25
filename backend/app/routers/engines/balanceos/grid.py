"""Balanceos v2 (waykee 292187) -- Grid 1 (triggers por ubicación), modal de
backorder de compra y sugerencia de cantidad del modal "Agregar"."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import Depends, Query

from app.core.db import get_db
from app.routers.engines.sugeridos import calc_cobertura_meses, calc_m2_a_cajas, _tabla_existe
from app.routers.semaforo import _fecha_pedido_simulada

from .constantes import DEFAULT_OBJETIVO_MESES, _now
from .persistencia import (
    _descartes_activos,
    _prioridad_efectiva,
    _sin_plantas_fuera_de_universo,
    _umbral_dias_pedido,
)
from .propuestas import _demanda_promedio
from .triggers import (
    calc_cajas_a_m2,
    calc_cantidad_sugerida_balanceo,
    calc_dias_desde_pedido,
    es_rojo,
    estado_semaforo_balanceo,
    evaluar_trigger,
    permite_transferencia_por_prioridad,
    resumir_pedidos_compra,
)


def _filas_material(db: sqlite3.Connection, material_id: str) -> list[dict]:
    rows = db.execute(
        """SELECT i.material_id, i.plant, i.disponible, i.transito, i.comprometido, i.pedidos_abiertos,
                  m.descripcion, m.abc, m.m2_por_caja,
                  s.nombre, s.corredor, s.es_cedis,
                  COALESCE(c.meses_objetivo, ?) AS meses_objetivo
           FROM inventarios i
           JOIN materiales m ON m.material_id = i.material_id
           JOIN sucursales s ON s.plant = i.plant
           LEFT JOIN coberturas_objetivo c ON c.material_id = i.material_id
           WHERE i.material_id = ?""",
        (DEFAULT_OBJETIVO_MESES, material_id),
    ).fetchall()
    return _sin_plantas_fuera_de_universo(db, rows)


def _serie_cajas_por_plant(db: sqlite3.Connection, material_id: str, m2_por_caja) -> dict:
    ventas_rows = db.execute(
        """SELECT plant, anio_mes, SUM(cantidad_m2) AS m2 FROM ventas_mensuales
           WHERE material_id = ? GROUP BY plant, anio_mes ORDER BY anio_mes""",
        (material_id,),
    ).fetchall()
    serie: dict[str, list[tuple[str, float]]] = {}
    for r in ventas_rows:
        cajas = calc_m2_a_cajas(r["m2"] or 0.0, m2_por_caja)
        serie.setdefault(r["plant"], []).append((r["anio_mes"], cajas))
    return serie


def _docs_compra(db: sqlite3.Connection, material_id: str):
    if not _tabla_existe(db, "pedidos_compra_detalle"):
        return None
    return db.execute(
        """SELECT plant, po, cantidad_pendiente, fecha_po FROM pedidos_compra_detalle
           WHERE material_id = ?""",
        (material_id,),
    ).fetchall()


def _lineas(rows: list[dict], serie: dict) -> list[dict]:
    lineas = []
    for r in rows:
        disp_neto = round((r["disponible"] or 0) + (r["transito"] or 0) - (r["comprometido"] or 0), 2)
        dem = _demanda_promedio(serie, r["plant"])
        cobertura = calc_cobertura_meses(disp_neto, dem)
        estado = estado_semaforo_balanceo(disp_neto, cobertura, r["meses_objetivo"])
        lineas.append({"row": r, "disponible_neto": disp_neto, "demanda": dem, "cobertura": cobertura, "estado": estado})
    return lineas


def _compra(r: dict, docs_compra, material_id: str, hoy: date) -> dict:
    if docs_compra is not None:
        return resumir_pedidos_compra(docs_compra, r["plant"], hoy)
    # Dataset sin detalle por OC: agregado + fecha simulada (292187).
    cajas_ag = r["pedidos_abiertos"] or 0
    return {
        "cajas": cajas_ag,
        "numeroPedidos": 1 if cajas_ag > 0 else 0,
        "diasDesdePedido": calc_dias_desde_pedido(material_id, r["plant"], hoy) if cajas_ag > 0 else None,
    }


def _fila_grid(material_id: str, linea: dict, compra: dict, trigger, descartado: bool, m2_por_caja) -> dict:
    r = linea["row"]
    if trigger and not descartado:
        orden = 0 if trigger["trigger"] == "sin_pedido" else 1
    else:
        orden = 2
    pedidos_abiertos = compra["cajas"]
    comprometido = r["comprometido"] or 0
    return {
        "materialId": material_id,
        "plant": r["plant"],
        "nombre": r["nombre"],
        "corredor": r["corredor"],
        "esCedis": bool(r["es_cedis"]),
        "estado": linea["estado"],
        "metros": calc_cajas_a_m2(linea["disponible_neto"], m2_por_caja),
        "meses": linea["cobertura"],
        "mesesObjetivo": r["meses_objetivo"],
        "disponibleNetoCajas": linea["disponible_neto"],
        "demandaCajas": linea["demanda"],
        "m2PorCaja": m2_por_caja,
        "backorderCompra": {
            "cajas": pedidos_abiertos,
            "metros": calc_cajas_a_m2(pedidos_abiertos, m2_por_caja),
            "diasDesdePedido": compra["diasDesdePedido"],
            "numeroPedidos": compra["numeroPedidos"],
        },
        "backorderTraslado": {
            "cajas": comprometido,
            "metros": calc_cajas_a_m2(comprometido, m2_por_caja),
            "meses": calc_cobertura_meses(comprometido, linea["demanda"]),
        },
        "trigger": trigger,
        "descartado": descartado,
        "orden": orden,
        "layer": "C1",
    }


def _compute_grid1(db: sqlite3.Connection, material_id: str, corredor: Optional[str] = None, hoy: Optional[date] = None) -> list[dict]:
    """Grid 1 (waykee 292187): una fila por ubicación para el material
    seleccionado, con el trigger evaluado por fila. "Zona" == corredor (el
    ticket no define zona aparte; Balanceos ya trabaja "dentro de corredor"
    desde RN-02, así que se reusa esa agrupación -- supuesto documentado)."""
    hoy = hoy or datetime.now(timezone.utc).date()
    rows = _filas_material(db, material_id)
    if not rows:
        return []

    m2_por_caja = rows[0]["m2_por_caja"]
    serie = _serie_cajas_por_plant(db, material_id, m2_por_caja)
    umbral_dias = _umbral_dias_pedido(db)
    descartes = _descartes_activos(db, material_id, hoy)
    docs_compra = _docs_compra(db, material_id)
    lineas = _lineas(rows, serie)

    resultado = []
    for linea in lineas:
        r = linea["row"]
        if corredor and r["corredor"] != corredor:
            continue
        alternativa = any(
            o["row"]["plant"] != r["plant"] and o["row"]["corredor"] == r["corredor"] and not es_rojo(o["estado"])
            for o in lineas
        )
        compra = _compra(r, docs_compra, material_id, hoy)
        trigger = evaluar_trigger(
            linea["disponible_neto"], linea["cobertura"], r["meses_objetivo"],
            compra["cajas"], compra["diasDesdePedido"], umbral_dias, alternativa,
        )
        resultado.append(_fila_grid(material_id, linea, compra, trigger, r["plant"] in descartes, m2_por_caja))

    resultado.sort(key=lambda x: (x["corredor"] or "", x["orden"], x["plant"]))
    return resultado


def grid1(
    material_id: str = Query(...),
    corredor: Optional[str] = Query(None),
    db: sqlite3.Connection = Depends(get_db),
):
    return {"items": _compute_grid1(db, material_id, corredor), "generado": _now()}


def grid1_backorder_detalle(
    material_id: str = Query(...),
    plant: str = Query(...),
    db: sqlite3.Connection = Depends(get_db),
):
    """Modal de detalle de backorder de compra (Grid 1): fecha + número de
    pedido por OC. SUPUESTO (waykee 292187): pedidos_compra_detalle no
    existe en este dataset (confirmado: ausente en schema.sql / "no such
    table"), solo el agregado inventarios.pedidos_abiertos. Se degrada igual
    que GET /pedidos-detalle en sugeridos.py: disponible=False con el
    agregado visible, hasta que T1 entregue el detalle real por OC."""
    if _tabla_existe(db, "pedidos_compra_detalle"):
        docs = db.execute(
            """SELECT po, posicion, proveedor, cantidad_pendiente, fecha_po, fecha_entrega_estimada
               FROM pedidos_compra_detalle WHERE material_id = ? AND plant = ?
               ORDER BY fecha_po""",
            (material_id, plant),
        ).fetchall()
        return {"disponible": True, "documentos": docs}

    row = db.execute(
        "SELECT pedidos_abiertos FROM inventarios WHERE material_id = ? AND plant = ?",
        (material_id, plant),
    ).fetchone()
    pedidos_abiertos = row["pedidos_abiertos"] if row else 0
    hoy = datetime.now(timezone.utc).date()
    fecha_simulada = _fecha_pedido_simulada(material_id, plant, hoy) if pedidos_abiertos else None
    return {
        "disponible": False,
        "motivo": "pedidos_compra_detalle no existe en el dataset -- solo se conoce el agregado.",
        "pedidosAbiertosCajas": pedidos_abiertos,
        "fechaPedidoSimulada": fecha_simulada.isoformat() if fecha_simulada else None,
        "documentos": [],
    }


def sugerencia_cantidad(
    material_id: str = Query(...),
    origen_plant: str = Query(...),
    destino_plant: str = Query(...),
    db: sqlite3.Connection = Depends(get_db),
):
    """Prellenado del modal "Agregar" de Grid 1 -- ver
    calc_cantidad_sugerida_balanceo. La cantidad SIEMPRE es editable a mano
    en el modal; esto solo sugiere un punto de partida con su fuente visible."""
    grid = _compute_grid1(db, material_id)
    origen = next((g for g in grid if g["plant"] == origen_plant), None)
    destino = next((g for g in grid if g["plant"] == destino_plant), None)
    if origen is None or destino is None:
        return {"error": "material_id/plant no encontrado (origen o destino)"}

    prioridad_origen, fuente_prioridad_origen = _prioridad_efectiva(db, material_id, origen_plant, origen["demandaCajas"])
    prioridad_destino, fuente_prioridad_destino = _prioridad_efectiva(db, material_id, destino_plant, destino["demandaCajas"])
    destino_mayor_prioridad = prioridad_destino > prioridad_origen

    sugerencia = calc_cantidad_sugerida_balanceo(
        disponible_neto_origen=origen["disponibleNetoCajas"],
        demanda_origen=origen["demandaCajas"],
        disponible_neto_destino=destino["disponibleNetoCajas"],
        demanda_destino=destino["demandaCajas"],
        meses_objetivo_destino=destino["mesesObjetivo"],
        es_cedis_origen=origen["esCedis"],
        destino_tiene_mayor_prioridad=destino_mayor_prioridad,
    )
    excedente_origen = max(
        0.0, origen["disponibleNetoCajas"] - origen["mesesObjetivo"] * origen["demandaCajas"]
    )
    permitido = permite_transferencia_por_prioridad(prioridad_origen, prioridad_destino, excedente_origen)

    m2_por_caja = origen["m2PorCaja"]
    return {
        **sugerencia,
        "cantidadSugeridaMetros": calc_cajas_a_m2(sugerencia["cantidadSugerida"], m2_por_caja),
        "permitidoPorPrioridad": permitido,
        "prioridadOrigen": {"valor": prioridad_origen, "fuente": fuente_prioridad_origen},
        "prioridadDestino": {"valor": prioridad_destino, "fuente": fuente_prioridad_destino},
        "m2PorCaja": m2_por_caja,
    }
