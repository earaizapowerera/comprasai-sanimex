"""Cargas batch por request: categorías, stats POS, salidas kardex, ajuste de
pico (Promedio 3) y filtro de sucursales que compran."""

from __future__ import annotations

import sqlite3
from typing import Optional

from app.core import sucursal_compra

from .calculos import calc_m2_a_cajas
from .constantes import PROMEDIO3_CAMPO_STATS, RATIO_M2_POR_PIEZA_FALLBACK
from .estadistica import calc_es_outlier_venta_dia
from .persistencia import _tabla_existe


def _cargar_categorias_tabla(
    db: sqlite3.Connection, material_ids: list[str], placeholders: str
) -> dict[str, list[tuple[str, str]]]:
    """T29 (punto 5, waykee 291788): categoría mensual por material -- hoy la
    siembra el loader del Excel muestra-compras.xlsb (ver
    data/load_categorias_excel.py), mañana SAP/HANA (v7). Devuelve
    material_id -> lista de (anio_mes, categoria) ordenada ascendente."""
    if not material_ids:
        return {}
    rows = db.execute(
        f"""SELECT material_id, anio_mes, categoria FROM categorias_mensuales
            WHERE material_id IN ({placeholders})
            ORDER BY material_id, anio_mes""",
        material_ids,
    ).fetchall()
    out: dict[str, list[tuple[str, str]]] = {}
    for r in rows:
        out.setdefault(r["material_id"], []).append((r["anio_mes"], r["categoria"]))
    return out


def _categoria_para_linea(
    tabla_categorias: dict[str, list[tuple[str, str]]], material_id: str, mes_ref: str
) -> Optional[dict]:
    """Categoría vigente al mes de referencia: exacta si existe, si no la más
    reciente <= mes_ref, si no -- fallback pedido por el PM (mensaje puente
    290066->291788) -- la más reciente disponible aunque sea posterior."""
    puntos = tabla_categorias.get(material_id)
    if not puntos:
        return None
    exacta = next((c for m, c in puntos if m == mes_ref), None)
    if exacta:
        return {"valor": exacta, "anio_mes": mes_ref}
    anteriores = [(m, c) for m, c in puntos if m <= mes_ref]
    if anteriores:
        m, c = max(anteriores, key=lambda par: par[0])
        return {"valor": c, "anio_mes": m}
    m, c = max(puntos, key=lambda par: par[0])
    return {"valor": c, "anio_mes": m}



def _modo_promedio3(db: sqlite3.Connection) -> str:
    """T28 (waykee 291765), mensaje puente: estrategia de 3 modos para el
    ajuste de Promedio 3, en orden de preferencia -- (1) ventas_stats_mensuales
    (dataset v6, aún no aterriza), (2) fallback kardex_diario (día pico), (3)
    sin datos: sin ajuste. Un solo lugar decide el modo para todo el batch."""
    if _tabla_existe(db, "ventas_stats_mensuales"):
        return "stats"
    if _tabla_existe(db, "kardex_diario"):
        return "kardex"
    return "ninguno"


def _cargar_stats_mensuales(db: sqlite3.Connection, material_ids: list[str], placeholders: str):
    rows = db.execute(
        f"""SELECT material_id, plant, anio_mes, suma_cantidad, max_ticket, max_linea, fecha_max_ticket
            FROM ventas_stats_mensuales
            WHERE material_id IN ({placeholders})""",
        material_ids,
    ).fetchall()
    return {(r["material_id"], r["plant"], r["anio_mes"]): r for r in rows}


def _cargar_salidas_diarias(db: sqlite3.Connection, material_ids: list[str], placeholders: str):
    rows = db.execute(
        f"""SELECT material_id, plant, fecha, salidas
            FROM kardex_diario
            WHERE material_id IN ({placeholders}) AND salidas > 0
            ORDER BY material_id, plant, fecha""",
        material_ids,
    ).fetchall()
    salidas_por_linea: dict[tuple[str, str], list[tuple[str, float]]] = {}
    for r in rows:
        salidas_por_linea.setdefault((r["material_id"], r["plant"]), []).append((r["fecha"], r["salidas"]))
    return salidas_por_linea


def _ajuste_pico_mes(
    modo: str,
    material_id: str,
    plant: str,
    anio_mes: str,
    m2_por_caja: Optional[float],
    stats_por_linea_mes: dict,
    salidas_por_linea: dict,
    factor_m2_por_pieza: float = RATIO_M2_POR_PIEZA_FALLBACK,
) -> dict:
    """Ajuste (en cajas) a restar del mes para Promedio 3, con la estrategia de
    3 modos de `_modo_promedio3`. Retorna también la metadata que el popup usa
    en el tooltip: fuente del ajuste, fecha de la venta/día pico, y si ese pico
    fue un outlier estadístico (solo aplica al modo kardex; el modo stats ya
    identifica la transacción exacta, no requiere el test de MAD).
    `factor_m2_por_pieza` convierte PROMEDIO3_CAMPO_STATS (max_ticket/max_linea,
    en PIEZAS POS -- ver comprasai_v6_reconciliacion.json) a m2 antes de pasarlo
    a calc_m2_a_cajas; el llamador lo deriva por línea (calc_factor_m2_por_pieza)."""
    if modo == "stats":
        row = stats_por_linea_mes.get((material_id, plant, anio_mes))
        if not row:
            return {"ajuste_cajas": 0.0, "fuente": "venta_mayor_transaccion", "fecha_pico": None, "es_outlier": None}
        valor_piezas = row[PROMEDIO3_CAMPO_STATS] or 0.0
        valor_m2 = valor_piezas * factor_m2_por_pieza
        return {
            "ajuste_cajas": calc_m2_a_cajas(valor_m2, m2_por_caja),
            "fuente": "venta_mayor_transaccion",
            "fecha_pico": row["fecha_max_ticket"],
            "es_outlier": None,
        }
    if modo == "kardex":
        dias_mes = [(f, s) for (f, s) in salidas_por_linea.get((material_id, plant), []) if f[:7] == anio_mes]
        if not dias_mes:
            return {"ajuste_cajas": 0.0, "fuente": "dia_pico_kardex", "fecha_pico": None, "es_outlier": False}
        fecha_pico, salida_pico = max(dias_mes, key=lambda t: t[1])
        valores_dia = [s for _, s in dias_mes]
        return {
            "ajuste_cajas": calc_m2_a_cajas(salida_pico, m2_por_caja),
            "fuente": "dia_pico_kardex",
            "fecha_pico": fecha_pico,
            "es_outlier": calc_es_outlier_venta_dia(valores_dia, salida_pico),
        }
    return {"ajuste_cajas": 0.0, "fuente": "sin_datos", "fecha_pico": None, "es_outlier": None}


def _filtrar_sucursales_que_compran(db: sqlite3.Connection, candidatos: list[dict]) -> tuple[list[dict], dict]:
    """Quita las líneas de sucursales que no compran directo (catálogo
    sucursal_compra). Catálogo vacío -> sin filtro."""
    excluidas = sucursal_compra.plantas_sin_compra(db)
    if not excluidas:
        return candidatos, {"activo": False, "lineas_excluidas": 0, "sucursales_excluidas": 0}
    filtrados = [c for c in candidatos if c["plant"] not in excluidas]
    afectadas = {c["plant"] for c in candidatos} & excluidas
    return filtrados, {"activo": True, "lineas_excluidas": len(candidatos) - len(filtrados),
                       "sucursales_excluidas": len(afectadas)}
