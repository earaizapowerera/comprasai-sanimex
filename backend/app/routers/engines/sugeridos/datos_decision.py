"""Payload `datos_decision` del popup de decisión (T28/T29)."""

from __future__ import annotations

from typing import Optional

from .calculos import calc_motivo_redondeo_pallet
from .constantes import PROMEDIO2_MESES


def build_datos_decision(
    *,
    historia_meses: list[str],
    historia_consumo: list[float],
    promedio_1: float,
    promedio_2: float,
    promedio_3: float,
    promedio_3_ajustes: list[dict],
    promedio_general: float,
    meses_actual: Optional[float],
    meses_con_venta: int,
    meses_historia: int,
    disponible: float,
    transito: float,
    comprometido: float,
    disponible_neto: float,
    cobertura_actual: Optional[float],
    meses_objetivo: float,
    meses_objetivo_fuente: str,
    compra_sugerida: float,
    proveedor: Optional[str],
    moq_cajas: int,
    cajas_por_pallet: int,
    lead_time_dias: int,
    m2_por_caja: Optional[float],
    costo_unitario: float,
    cantidad_transferir: float,
    detalle_transferencias: list[dict],
    cantidad_comprar_bruta: float,
    cantidad_final: int,
    n_pallets: int,
    inventario_fin_mes: Optional[dict[str, Optional[float]]] = None,
    kardex_disponible: bool = False,
    dias_sin_inventario: Optional[dict[str, dict]] = None,
    categoria: Optional[dict] = None,
) -> dict:
    """T28 (waykee 291765): motor de 3 promedios -- reemplaza al promedio móvil
    corto (T19/T25) como base de cobertura/faltante/compra sugerida, en
    paridad con la hoja Excel del área de compras. Cada campo es trazable a
    una variable ya calculada en generar_sugeridos(), reproducible a mano
    contra ventas_mensuales/kardex_diario (criterio de aceptación del ticket).

    `historia` trae los `MESES_SERIE_DISPLAY` meses calendario contiguos (con
    ceros para meses sin venta, igual que la hoja Excel) y el desglose de los
    3 promedios: Promedio 1 = media de toda la ventana, Promedio 2 = media de
    los últimos `PROMEDIO2_MESES`, Promedio 3 = media de la ventana con el
    pico de cada mes restado (`promedio_3_ajustes`, con la fuente del ajuste
    para el tooltip: `venta_mayor_transaccion` cuando ventas_stats_mensuales
    ya aterrizó -- dataset v6, aún pendiente --, `dia_pico_kardex` como
    fallback, o `sin_datos` cuando ninguna de las dos tablas existe)."""
    m2 = m2_por_caja
    return {
        "historia": _bloque_historia(historia_meses, historia_consumo, promedio_1, promedio_2,
                                     promedio_3, promedio_3_ajustes, m2),
        "promedio_general": round(promedio_general, 2),
        "promedio_general_m2": _a_m2(promedio_general, m2),
        "meses_actual": round(meses_actual, 2) if meses_actual is not None else None,
        "meses_con_venta": meses_con_venta,
        "meses_historia": meses_historia,
        "inventario_fin_mes": [
            _mes_fin(mes, inventario_fin_mes or {}, dias_sin_inventario or {}, m2) for mes in historia_meses
        ],
        "kardex_disponible": kardex_disponible,
        "inventario": _bloque_inventario(disponible, transito, comprometido, disponible_neto, m2),
        "cobertura_actual": round(cobertura_actual, 2) if cobertura_actual is not None else None,
        # T29 (punto 5): categoría vigente al mes de referencia -- {valor, anio_mes}
        # (anio_mes puede no ser el de referencia si se usó fallback, ver
        # _categoria_para_linea) o None si el material no tiene categoría cargada.
        "categoria": categoria,
        "meses_objetivo": {
            "valor": meses_objetivo,
            # T29 (punto 1): 'excepcion' (material+sucursal) | 'default'
            # (material) | 'fallback' (sin fila en ninguna tabla, usa
            # DEFAULT_OBJETIVO_MESES) -- el popup muestra badge "Excepción"
            # solo cuando este valor es 'excepcion'.
            "fuente": meses_objetivo_fuente,
        },
        "proveedor": {
            "nombre": proveedor,
            "moq_cajas": moq_cajas,
            "cajas_por_pallet": cajas_por_pallet,
            "lead_time_dias": lead_time_dias,
        },
        "m2_por_caja": m2,
        "costo_unitario": costo_unitario,
        "transferencia": {
            "cantidad_transferir": cantidad_transferir,
            "detalle_transferencias": detalle_transferencias,
        },
        "compra": _bloque_compra(compra_sugerida, cantidad_comprar_bruta, cantidad_final,
                                 n_pallets, cajas_por_pallet, m2),
    }


def _mes_fin(mes: str, inventario_fin_mes: dict, dias_sin_inventario: dict,
             m2_por_caja: Optional[float]) -> dict:
    # T29 (waykee 291788, punto 2 + punto 3): saldo de fin de mes en m2
    # junto al de cajas, y "días sin inventario" del mismo mes (fuente
    # única calc_dias_sin_inventario_por_mes) -- None cuando no aplica
    # (sin kardex_diario poblado) en vez de 0, para no confundir "sin
    # dato" con "sin días de quiebre".
    dsi = dias_sin_inventario.get(mes)
    return {
        "anio_mes": mes,
        "saldo": inventario_fin_mes.get(mes),
        "saldo_m2": _a_m2(inventario_fin_mes.get(mes), m2_por_caja),
        "dias_sin_inventario": dsi["dias"] if dsi else None,
        "dias_con_dato": dsi["dias_con_dato"] if dsi else None,
        "dias_mes": dsi["dias_mes"] if dsi else None,
        "cobertura_parcial": dsi["cobertura_parcial"] if dsi else None,
    }


def _bloque_historia(historia_meses: list[str], historia_consumo: list[float], promedio_1: float,
                     promedio_2: float, promedio_3: float, promedio_3_ajustes: list[dict],
                     m2_por_caja: Optional[float]) -> dict:
    corte_promedio_2 = max(0, len(historia_meses) - PROMEDIO2_MESES)
    return {
        "meses": historia_meses,
        "consumo": [round(v, 2) for v in historia_consumo],
        "consumo_m2": [_a_m2(v, m2_por_caja) for v in historia_consumo],
        "promedio_1": {
            "valor": round(promedio_1, 2),
            "valor_m2": _a_m2(promedio_1, m2_por_caja),
        },
        "promedio_2": {
            "valor": round(promedio_2, 2),
            "valor_m2": _a_m2(promedio_2, m2_por_caja),
            "incluidos": [idx >= corte_promedio_2 for idx in range(len(historia_meses))],
        },
        "promedio_3": {
            "valor": round(promedio_3, 2),
            "valor_m2": _a_m2(promedio_3, m2_por_caja),
            "ajustes": promedio_3_ajustes,
        },
    }


def _bloque_inventario(disponible: float, transito: float, comprometido: float,
                       disponible_neto: float, m2_por_caja: Optional[float]) -> dict:
    return {
        "disponible": disponible or 0,
        "disponible_m2": _a_m2(disponible or 0, m2_por_caja),
        "transito": transito or 0,
        "transito_m2": _a_m2(transito or 0, m2_por_caja),
        "comprometido": comprometido or 0,
        "comprometido_m2": _a_m2(comprometido or 0, m2_por_caja),
        "disponible_neto": disponible_neto,
        "disponible_neto_m2": _a_m2(disponible_neto, m2_por_caja),
        "sobrevendido": disponible_neto < 0,
    }


def _bloque_compra(compra_sugerida: float, cantidad_comprar_bruta: float, cantidad_final: int,
                   n_pallets: int, cajas_por_pallet: int, m2_por_caja: Optional[float]) -> dict:
    return {
        "compra_sugerida_cajas": compra_sugerida,
        "compra_sugerida_m2": round(compra_sugerida * m2_por_caja, 2) if m2_por_caja else None,
        "cantidad_comprar_bruta": cantidad_comprar_bruta,
        "cantidad_final_cajas": cantidad_final,
        "cantidad_final_m2": round(cantidad_final * m2_por_caja, 2) if m2_por_caja else None,
        "n_pallets": n_pallets,
        "cajas_por_pallet": cajas_por_pallet,
        "motivo": calc_motivo_redondeo_pallet(cantidad_comprar_bruta, cantidad_final, cajas_por_pallet),
    }


def _a_m2(valor_cajas: Optional[float], m2_por_caja: Optional[float]) -> Optional[float]:
    """T29 (punto 2): equivalente en m2 de un valor en cajas, mismo criterio
    ya usado por build_datos_decision para compra_sugerida_m2/cantidad_final_m2
    -- multiplicar por m2_por_caja (constante por material). None cuando no
    hay factor de conversión (m2_por_caja ausente/0) o el valor es None."""
    if valor_cajas is None or not m2_por_caja:
        return None
    return round(valor_cajas * m2_por_caja, 2)
