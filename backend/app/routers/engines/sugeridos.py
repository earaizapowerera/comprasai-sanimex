"""Motor C1 · Sugeridos de Compra (backend de la pantalla estrella S8).

Implementa el contrato descrito en README_MOTORES.py:
  - disponible neto, cobertura actual vs objetivo (RN-01)
  - transferencia antes que compra dentro del corredor (RN-02)
  - redondeo a MOQ / múltiplo de empaque / pallet (RF-011 / RF-016)
  - workflow Planeador (propone) -> Gerente (aprueba/rechaza) (RF-008)
  - exportación de plantilla de carga masiva a SAP (RF-009)

Este motor nació como parte de T9 (pantalla Sugeridos) porque T4 (dueño
formal de motores_c1.py) todavía no había arrancado cuando el deadline de
la demo obligaba a tener el flujo estrella funcionando end-to-end. Las
funciones puras de esta capa (prefijo `calc_`) están aisladas y son fáciles
de mover/fusionar a `motores_c1.py` sin tocar el contrato HTTP si T4 entrega
su propia versión — ver mensaje de coordinación en waykee 290092.

Casos golden validados a mano por T14 (waykee 290102, msg 61807):
  G1/G2/G3 -> RN-01 (ver calc_cobertura_meses + regla de no-sugerir)
  G4/G5    -> RN-02 (ver _aplicar_transferencia)
  G6/G7/G8 -> redondeo MOQ/empaque/m2 (ver calc_redondeo_moq y calc_m2_a_cajas)
"""

from __future__ import annotations

import csv
import io
import json
import math
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
import sqlite3

from app.core.constants import EPS_DEMANDA
from app.core.db import get_db

router = APIRouter(prefix="/api/engines/sugeridos", tags=["engines:sugeridos"])

MESES_HISTORIA = 6  # ventana de meses usada para tendencia/confianza (informativo, C2)
MESES_SERIE_DISPLAY = 5  # T27 (waykee 291745): meses calendario contiguos para el popup de decisión
DEFAULT_MOQ = 20
DEFAULT_PALLET = 40
DEFAULT_OBJETIVO_MESES = 2.0

# T28 (waykee 291765): motor de 3 promedios -- paridad con la hoja Excel del
# área de compras. Promedio 1 = ventana completa de MESES_SERIE_DISPLAY (5)
# meses calendario; Promedio 2 = solo los últimos PROMEDIO2_MESES; Promedio 3
# = misma ventana de 5 meses con el pico de cada mes restado (ver
# _ajuste_pico_mes). PROMEDIO_GENERAL = promedio simple de los 3.
PROMEDIO2_MESES = 2
# Campo de ventas_stats_mensuales a restar en el modo 1 de Promedio 3 (dataset
# v6, ya desplegado -- ver mensaje puente waykee 290066->291765, confirmado
# en vivo 17-sep-2026: max_linea == max_ticket siempre en este POS, así que
# la duda de compras sobre cuál definición usa su Excel no cambia el
# resultado). Cambiar a "max_linea" es la única acción para encender esa
# variante si compras pide lo contrario.
PROMEDIO3_CAMPO_STATS = "max_ticket"

# T28 (mensaje puente waykee 290066->291765, 17-sep-2026): el mes de
# REFERENCIA de la ventana (el más reciente, hoy 2026-08) viene PARCIAL en
# ventas_mensuales por diseño -- se extrae a mitad de mes -- mientras que
# ventas_stats_mensuales (POS /POSDW/TLOGF) sí lo trae completo. Por eso el
# consumo de ESE mes específico se sustituye por
# ventas_stats_mensuales.suma_cantidad cuando la tabla existe (ver
# calc_consumo_mes_referencia_corregido y serie_pts_display), bloqueando el fallback silencioso a
# ventas_mensuales que subestimaba ese mes ~30%. suma_cantidad viene en
# PIEZAS POS (RETAILQUANTITY), NO en m2 como cantidad_m2 -- no son
# comparables 1:1 (ver comprasai_v6_reconciliacion.json). Como no hay un
# campo "piezas por caja" limpio en materiales (columna `formato` viene
# vacía en el dataset real), el factor de conversión piezas->m2 se deriva
# POR MATERIAL de su propia superposición real en los meses previos de la
# misma ventana (vm_m2 / stats_piezas) -- más preciso que el ratio global
# del dataset (~1.04, mezcla de todo el catálogo, NO constante por SKU). Ese
# ratio global queda solo como fallback para materiales sin superposición
# válida (SKU nuevo, o piezas=0 en los meses previos).
RATIO_M2_POR_PIEZA_FALLBACK = 1.0399


# ---------------------------------------------------------------------------
# Funciones puras (C1) — sin I/O, testeables 1:1 contra los casos golden.
# ---------------------------------------------------------------------------

def calc_m2_a_cajas(m2: float, m2_por_caja: Optional[float]) -> float:
    """G8: need=100 m2, m2_por_caja=1.44 -> ceil(100/1.44) = 70 cajas.
    Redondea la división a 6 decimales antes del ceil: 43.2/1.44 da
    30.000000000000004 en punto flotante, y sin este guard eso subía a 31
    cajas por ruido de FP en vez del 30 exacto (detectado por
    test_kardex_con_salidas_activa_modo_pico_en_promedio_3)."""
    if not m2_por_caja or m2_por_caja <= 0:
        return round(m2, 2)
    return math.ceil(round(m2 / m2_por_caja, 6))


def calc_cobertura_meses(disponible_neto: float, demanda_mensual: Optional[float]) -> Optional[float]:
    """Cobertura en meses = inventario disponible / demanda mensual promedio.
    None cuando no hay demanda reciente (no hay base para decidir), o cuando
    la demanda es residual (~1e-15, ruido de origen del dataset REAL CAR):
    ver EPS_DEMANDA en app.core.constants -- mismo guard que kpis.py (T16,
    waykee 290112) e inventarios.py/COBERTURA_CTE (T18, waykee 290114). Sin
    este guard, disponible_neto / demanda_mensual con un denominador ínfimo
    produce coberturas absurdas (~1e+15 meses)."""
    if demanda_mensual is None or demanda_mensual < EPS_DEMANDA:
        return None
    return disponible_neto / demanda_mensual


def calc_redondeo_moq(need: float, moq: int, multiplo_empaque: int = 1) -> int:
    """RF-011/016. G6: need=37, multiplo=12, MOQ=20 -> max(20, ceil(37/12)*12) = 48.
    G7: need=8, MOQ=20 -> 20 (sube a MOQ)."""
    if need <= 0:
        return 0
    multiplo_empaque = max(1, multiplo_empaque)
    en_multiplo = math.ceil(need / multiplo_empaque) * multiplo_empaque
    return int(max(moq, en_multiplo))


def calc_redondeo_pallet(cantidad: int, cajas_por_pallet: Optional[int]) -> int:
    """Si la cantidad ya supera un pallet completo, sube al múltiplo de pallet
    más cercano (evita fracciones de pallet en compras grandes)."""
    if not cajas_por_pallet or cajas_por_pallet <= 0 or cantidad <= cajas_por_pallet:
        return cantidad
    return int(math.ceil(cantidad / cajas_por_pallet) * cajas_por_pallet)


def calc_promedio_simple(valores: list[float]) -> float:
    """Promedio 1: media simple de la ventana de meses calendario (con ceros
    incluidos para meses sin venta -- paridad con la hoja Excel, que no
    excluye meses en blanco del promedio)."""
    if not valores:
        return 0.0
    return sum(valores) / len(valores)


def calc_promedio_ultimos_n(valores: list[float], n: int) -> float:
    """Promedio 2: media de los últimos `n` meses de la misma ventana."""
    if n <= 0:
        return 0.0
    return calc_promedio_simple(valores[-n:])


def calc_factor_m2_por_pieza(pares_m2_piezas: list[tuple[float, float]]) -> float:
    """Factor piezas POS -> m2 de UN material, derivado de la superposición
    real (mismo material) entre ventas_mensuales y ventas_stats_mensuales en
    meses previos completos. `pares_m2_piezas` = [(m2_del_mes, piezas_del_mes), ...].
    Promedia el ratio mes a mes (no suma-total/suma-total) para no dejar que
    un solo mes de mucho volumen domine el factor. Cae al fallback global
    del dataset si no hay ningún mes con piezas > 0."""
    ratios = [m2 / piezas for m2, piezas in pares_m2_piezas if piezas and piezas > 0]
    if not ratios:
        return RATIO_M2_POR_PIEZA_FALLBACK
    return sum(ratios) / len(ratios)


def calc_consumo_mes_referencia_corregido(
    piezas_mes_ref: float,
    m2_por_caja: Optional[float],
    factor_m2_por_pieza: float,
) -> float:
    """T28 (mensaje puente waykee 290066->291765, 17-sep-2026): cajas del mes de
    REFERENCIA (hoy 2026-08) recalculadas desde ventas_stats_mensuales.suma_cantidad
    (piezas POS, mes completo) en vez de ventas_mensuales.cantidad_m2 (m2, mes
    PARCIAL -- se extrae a mitad de mes y subestima ~30%). `factor_m2_por_pieza`
    ya viene derivado por el llamador (ver calc_factor_m2_por_pieza) de la propia
    superposición histórica del material, NO del ratio global del dataset
    (1.0399, mezcla de todo el catálogo -- no es una constante válida por SKU)."""
    m2_estimado = (piezas_mes_ref or 0.0) * factor_m2_por_pieza
    return calc_m2_a_cajas(m2_estimado, m2_por_caja)


def calc_valor_mes_ajustado(valor_mes: float, ajuste: float) -> float:
    """Ejemplo del mensaje puente (waykee 291765): abril 30 con ajuste 2 -> 28;
    junio 39 con ajuste 9 -> 30. Nunca deja el mes en negativo."""
    return max(0.0, valor_mes - max(0.0, ajuste))


def calc_promedio_general(promedio_1: float, promedio_2: float, promedio_3: float) -> float:
    return (promedio_1 + promedio_2 + promedio_3) / 3.0


def calc_compra_sugerida(
    meses_objetivo: float,
    promedio_general: float,
    disponible: float,
    transito: float,
) -> float:
    """Fórmula del Excel de compras: MesesObjetivo x PROMEDIO - Disponible -
    BackorderCompra(tránsito), sin netear el disponible de antemano. Caso
    golden del mensaje puente: 6*504.6667-536-473 = 2019.0.

    T29 (waykee 291788, punto 4): el término '+ comprometido' se ELIMINA de
    esta fórmula -- lo que la pantalla mostraba como "Backorder venta
    (comprometido)" es en realidad BACKORDER TRASLADO (mercancía por SALIR de
    la sucursal, no una venta pendiente de surtir), así que sumarlo a la
    compra sugerida inflaba la cantidad a pedir por algo que no es demanda.
    `comprometido` se sigue mostrando en el popup (ver build_datos_decision,
    campo "backorder_traslado") y sigue afectando disponible_neto/cobertura
    (RN-01, decide SI sugerir), solo se saca del MONTO a comprar. Cuando
    exista backorder de VENTA real (cliente esperando surtido), ese término
    se reintroduce por separado -- ver mensaje puente waykee 290066->291788."""
    bruta = (
        meses_objetivo * promedio_general
        - (disponible or 0.0)
        - (transito or 0.0)
    )
    return round(max(0.0, bruta), 2)


def calc_redondeo_pallets_completos(cantidad: float, cajas_por_pallet: Optional[int]) -> int:
    """Redondeo a Pallets del Excel: SIEMPRE sube al múltiplo de pallet
    completo (a diferencia de calc_redondeo_pallet, que solo redondea si la
    cantidad ya supera un pallet -- esa se conserva intacta porque
    backtest_forecast.py la reusa). Caso golden: 2019 cajas, pallet=16 ->
    ceil(2019/16)*16 = 2032."""
    if cantidad <= 0:
        return 0
    pallet = cajas_por_pallet if cajas_por_pallet and cajas_por_pallet > 0 else DEFAULT_PALLET
    return int(math.ceil(cantidad / pallet) * pallet)


def calc_motivo_redondeo_pallet(bruta: float, final: int, cajas_por_pallet: int) -> str:
    """Texto determinista del redondeo a pallet (sin MOQ -- el motor de 3
    promedios no aplica MOQ, solo pallet completo)."""
    if bruta <= 0:
        return "Sin compra: el faltante quedó cubierto por transferencia o el objetivo ya está cumplido."
    if final > bruta:
        return f"Se redondea de {bruta:.0f} a {final} cajas para completar pallets de {cajas_por_pallet} cajas cada uno."
    return f"Sin ajuste: {bruta:.0f} cajas ya es múltiplo exacto de pallet ({cajas_por_pallet} cajas)."


def calc_mediana(valores: list[float]) -> float:
    ordenados = sorted(valores)
    n = len(ordenados)
    if n == 0:
        return 0.0
    mitad = n // 2
    if n % 2 == 1:
        return ordenados[mitad]
    return (ordenados[mitad - 1] + ordenados[mitad]) / 2.0


def calc_mad(valores: list[float], mediana: Optional[float] = None) -> float:
    """Median Absolute Deviation -- estadístico robusto (no lo mueve un solo
    valor extremo, a diferencia de la desviación estándar)."""
    if not valores:
        return 0.0
    m = mediana if mediana is not None else calc_mediana(valores)
    return calc_mediana([abs(v - m) for v in valores])


def calc_es_outlier_venta_dia(valores_dia: list[float], valor: float, k: float = 3.0) -> bool:
    """Detección informativa (no altera la cantidad sugerida): venta atípica
    si |valor - mediana| > k*MAD. Con MAD=0 (todos los días iguales) se marca
    outlier solo si el valor evaluado supera esa mediana constante."""
    if len(valores_dia) < 2:
        return False
    mediana = calc_mediana(valores_dia)
    mad = calc_mad(valores_dia, mediana)
    if mad <= 0:
        return valor > mediana
    return abs(valor - mediana) > k * mad


def calc_tendencia(serie_mensual: list[float]) -> str:
    """Compara el último mes contra el promedio de los meses previos.
    +-10% se considera estable (evita ruido de series cortas/sintéticas)."""
    if len(serie_mensual) < 2:
        return "estable"
    *previos, ultimo = serie_mensual
    promedio_previo = sum(previos) / len(previos) if previos else 0
    if promedio_previo <= 0:
        return "estable"
    delta = (ultimo - promedio_previo) / promedio_previo
    if delta >= 0.10:
        return "alza"
    if delta <= -0.10:
        return "baja"
    return "estable"


def calc_confianza(meses_con_venta: int, meses_totales: int) -> int:
    """Score 50-95 determinista según qué tan completo está el historial de
    demanda usado — no es aleatorio: mismo input, mismo score siempre."""
    if meses_totales <= 0:
        return 50
    cobertura_historial = meses_con_venta / meses_totales
    return int(round(50 + cobertura_historial * 45))


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
    inventario_fin_mes = inventario_fin_mes or {}
    corte_promedio_2 = max(0, len(historia_meses) - PROMEDIO2_MESES)
    return {
        "historia": {
            "meses": historia_meses,
            "consumo": [round(v, 2) for v in historia_consumo],
            "promedio_1": {"valor": round(promedio_1, 2)},
            "promedio_2": {
                "valor": round(promedio_2, 2),
                "incluidos": [idx >= corte_promedio_2 for idx in range(len(historia_meses))],
            },
            "promedio_3": {
                "valor": round(promedio_3, 2),
                "ajustes": promedio_3_ajustes,
            },
        },
        "promedio_general": round(promedio_general, 2),
        "meses_actual": round(meses_actual, 2) if meses_actual is not None else None,
        "meses_con_venta": meses_con_venta,
        "meses_historia": meses_historia,
        "inventario_fin_mes": [
            {"anio_mes": mes, "saldo": inventario_fin_mes.get(mes)} for mes in historia_meses
        ],
        "kardex_disponible": kardex_disponible,
        "inventario": {
            "disponible": disponible or 0,
            "transito": transito or 0,
            "comprometido": comprometido or 0,
            "disponible_neto": disponible_neto,
            "sobrevendido": disponible_neto < 0,
        },
        "cobertura_actual": round(cobertura_actual, 2) if cobertura_actual is not None else None,
        "meses_objetivo": meses_objetivo,
        "proveedor": {
            "nombre": proveedor,
            "moq_cajas": moq_cajas,
            "cajas_por_pallet": cajas_por_pallet,
            "lead_time_dias": lead_time_dias,
        },
        "m2_por_caja": m2_por_caja,
        "costo_unitario": costo_unitario,
        "transferencia": {
            "cantidad_transferir": cantidad_transferir,
            "detalle_transferencias": detalle_transferencias,
        },
        "compra": {
            "compra_sugerida_cajas": compra_sugerida,
            "compra_sugerida_m2": round(compra_sugerida * m2_por_caja, 2) if m2_por_caja else None,
            "cantidad_comprar_bruta": cantidad_comprar_bruta,
            "cantidad_final_cajas": cantidad_final,
            "cantidad_final_m2": round(cantidad_final * m2_por_caja, 2) if m2_por_caja else None,
            "n_pallets": n_pallets,
            "cajas_por_pallet": cajas_por_pallet,
            "motivo": calc_motivo_redondeo_pallet(cantidad_comprar_bruta, cantidad_final, cajas_por_pallet),
        },
    }


# ---------------------------------------------------------------------------
# Persistencia ligera del workflow (Borrador/Propuesto/Aprobado/Rechazado).
# Tabla adicional, aditiva al esquema de T3 (CREATE TABLE IF NOT EXISTS).
# ---------------------------------------------------------------------------

def _ensure_tables(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS sugeridos_generados (
            id                  TEXT PRIMARY KEY,
            material_id         TEXT NOT NULL,
            plant               TEXT NOT NULL,
            descripcion         TEXT,
            abc                 TEXT,
            cobertura_actual    REAL,
            cobertura_objetivo  REAL,
            cantidad_sugerida   REAL,
            cantidad_transferir REAL,
            cantidad_comprar    REAL,
            cantidad_final      REAL,
            costo_unitario      REAL,
            costo_estimado      REAL,
            confianza           INTEGER,
            tendencia           TEXT,
            capa                TEXT,
            explicacion         TEXT,
            factores_json       TEXT,
            datos_decision_json TEXT,
            estado              TEXT NOT NULL DEFAULT 'propuesto',
            justificacion_edicion TEXT,
            aprobado_por        TEXT,
            creado              TEXT NOT NULL,
            actualizado         TEXT NOT NULL
        )"""
    )
    # T19 (waykee 290116): tablas ya creadas ANTES de este cambio no tienen
    # datos_decision_json (CREATE TABLE IF NOT EXISTS no la agrega
    # retroactivamente) -- migración aditiva idempotente, mismo patrón con el
    # que esta tabla se sumó sobre el esquema de T3 sin tocar datos existentes.
    cols = {row["name"] for row in db.execute("PRAGMA table_info(sugeridos_generados)")}
    if "datos_decision_json" not in cols:
        db.execute("ALTER TABLE sugeridos_generados ADD COLUMN datos_decision_json TEXT")
    db.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tabla_existe(db: sqlite3.Connection, tabla: str) -> bool:
    """T25 (waykee 290148): guard para tablas opcionales del dataset que aún
    no aterrizan (kardex_diario, backorder_detalle, pedidos_compra_detalle) --
    permite degradar con gracia (None / "disponible": False) en vez de tronar
    con 'no such table', mismo patrón que _tabla_existe en
    analysis/backtest_forecast.py."""
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", [tabla]
    ).fetchone()
    return row is not None


def _meses_contiguos(ref_anio_mes: str, n: int) -> list[str]:
    """T27 (waykee 291745): últimos `n` meses CALENDARIO contiguos terminando
    en `ref_anio_mes` ('YYYY-MM'), ascendente, sin huecos -- a diferencia de
    `serie` (armada solo con meses que tuvieron venta en ventas_mensuales),
    esta lista siempre trae exactamente `n` elementos aunque algún mes no
    haya tenido ventas (el llamador rellena esos meses con 0). Mismo criterio
    de mes de referencia que remates.py: MAX(anio_mes) global de
    ventas_mensuales, con fallback a la fecha actual si la tabla está vacía."""
    year, month = (int(x) for x in ref_anio_mes.split("-"))
    meses = []
    for i in range(n - 1, -1, -1):
        y, m = year, month - i
        while m <= 0:
            m += 12
            y -= 1
        meses.append(f"{y:04d}-{m:02d}")
    return meses


def _saldos_fin_mes(puntos: list[tuple[str, float]], meses: list[str]) -> dict[str, Optional[float]]:
    """T25 (waykee 290148): inventario fin de mes = saldo_fin_dia del último
    registro de kardex_diario con fecha <= fin del mes -- el kardex solo tiene
    filas en días CON movimiento (ver build_kardex_v3.py, waykee 290120), así
    que el saldo se ARRASTRA del último movimiento conocido, igual que un
    kardex real. `puntos` debe venir ordenado ascendente por fecha (columna
    `fecha`, formato 'YYYY-MM-DD') y `meses` ascendente ('YYYY-MM'). None
    cuando no hay ningún movimiento registrado en o antes de ese mes."""
    resultado: dict[str, Optional[float]] = {}
    idx = 0
    n = len(puntos)
    ultimo_saldo: Optional[float] = None
    for mes in meses:
        while idx < n and puntos[idx][0][:7] <= mes:
            ultimo_saldo = puntos[idx][1]
            idx += 1
        resultado[mes] = ultimo_saldo
    return resultado


def _dias_calendario_mes(anio_mes: str) -> list[str]:
    """Todos los días calendario ('YYYY-MM-DD') de un mes 'YYYY-MM', usando
    solo stdlib (sin `calendar`) -- el día 1 del mes siguiente menos un día
    evita tener que tabular meses de 28/29/30/31 a mano."""
    year, month = (int(x) for x in anio_mes.split("-"))
    if month == 12:
        primero_mes_sig = datetime(year + 1, 1, 1)
    else:
        primero_mes_sig = datetime(year, month + 1, 1)
    n_dias = (primero_mes_sig - datetime(year, month, 1)).days
    return [f"{year:04d}-{month:02d}-{d:02d}" for d in range(1, n_dias + 1)]


def calc_dias_sin_inventario_por_mes(
    puntos: list[tuple[str, float]], meses: list[str]
) -> dict[str, dict]:
    """T29 (waykee 291788, punto 3): "días sin inventario" por mes = días
    calendario del mes con saldo de inventario en CERO (o negativo), fuente
    ÚNICA función -- así se puede reemplazar por la tabla oficial que Araceli
    trae de HANA (v7, ticket hermano del Data Expert) sin tocar al llamador.

    `puntos` = TODO el historial de kardex_diario de la línea material+plant
    (columna `fecha` 'YYYY-MM-DD', `saldo_fin_dia`), ordenado ascendente --
    mismo insumo que `_saldos_fin_mes`. El kardex solo trae filas en días CON
    movimiento, así que el saldo se ARRASTRA día a día (mismo criterio de
    arrastre que `_saldos_fin_mes`, aquí a granularidad diaria en vez de solo
    fin de mes) para capturar los días de stockout que persisten SIN
    movimiento, no solo el día exacto en que la venta lo dejó en cero.

    Si el primer movimiento conocido es POSTERIOR al día evaluado, ese día
    queda SIN DETERMINAR (no cuenta ni en el numerador ni en `dias_con_dato`)
    -- de ahí `cobertura_parcial`: True cuando el kardex no cubre el mes
    completo, para que el popup muestre el tooltip de aviso en vez de
    presentar un número silenciosamente incompleto."""
    idx = 0
    n = len(puntos)
    ultimo_saldo: Optional[float] = None
    resultado: dict[str, dict] = {}
    for mes in meses:
        dias_mes = _dias_calendario_mes(mes)
        con_dato = 0
        en_cero = 0
        for dia in dias_mes:
            while idx < n and puntos[idx][0] <= dia:
                ultimo_saldo = puntos[idx][1]
                idx += 1
            if ultimo_saldo is not None:
                con_dato += 1
                if ultimo_saldo <= 0:
                    en_cero += 1
        resultado[mes] = {
            "dias": en_cero,
            "dias_con_dato": con_dato,
            "dias_mes": len(dias_mes),
            "cobertura_parcial": con_dato < len(dias_mes),
        }
    return resultado


def _a_m2(valor_cajas: Optional[float], m2_por_caja: Optional[float]) -> Optional[float]:
    """T29 (punto 2): equivalente en m2 de un valor en cajas, mismo criterio
    ya usado por build_datos_decision para compra_sugerida_m2/cantidad_final_m2
    -- multiplicar por m2_por_caja (constante por material). None cuando no
    hay factor de conversión (m2_por_caja ausente/0) o el valor es None."""
    if valor_cajas is None or not m2_por_caja:
        return None
    return round(valor_cajas * m2_por_caja, 2)


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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/opciones")
def opciones(db: sqlite3.Connection = Depends(get_db)):
    """Catálogos para los combobox searchable del filtro (familia/proveedor/corredor)."""
    familias = [r["familia"] for r in db.execute("SELECT DISTINCT familia FROM materiales ORDER BY familia")]
    proveedores = [r["proveedor"] for r in db.execute("SELECT DISTINCT proveedor FROM proveedores ORDER BY proveedor")]
    corredores = [r["corredor"] for r in db.execute("SELECT DISTINCT corredor FROM sucursales WHERE corredor IS NOT NULL ORDER BY corredor")]
    return {"familias": familias, "proveedores": proveedores, "corredores": corredores}


@router.get("/generar")
def generar_sugeridos(
    familia: Optional[str] = None,
    proveedor: Optional[str] = None,
    corredor: Optional[str] = None,
    plant: Optional[str] = None,
    abc: Optional[str] = Query(None, pattern="^[ABC]$"),
    solo_criticos: bool = Query(False, description="Solo líneas con cobertura actual = 0"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: sqlite3.Connection = Depends(get_db),
):
    """Clic 1 del flujo estrella: corre C1 (reglas) + C2 (forecast simple) +
    C3 (explicación) y persiste cada línea como 'propuesto'."""
    _ensure_tables(db)

    where = ["1=1"]
    params: list = []
    if familia:
        where.append("m.familia = ?")
        params.append(familia)
    if proveedor:
        where.append("pr.proveedor = ?")
        params.append(proveedor)
    if corredor:
        where.append("s.corredor = ?")
        params.append(corredor)
    if plant:
        where.append("i.plant = ?")
        params.append(plant)
    if abc:
        where.append("m.abc = ?")
        params.append(abc)
    where_sql = " AND ".join(where)

    candidatos = db.execute(
        f"""SELECT i.material_id, i.plant, i.disponible, i.transito, i.comprometido,
                   m.descripcion, m.abc, m.m2_por_caja, m.precio_venta, m.costo,
                   s.corredor, s.organizacion, s.canal,
                   COALESCE(c.meses_objetivo, {DEFAULT_OBJETIVO_MESES}) AS meses_objetivo,
                   COALESCE(pr.moq_cajas, {DEFAULT_MOQ}) AS moq_cajas,
                   COALESCE(pr.cajas_por_pallet, {DEFAULT_PALLET}) AS cajas_por_pallet,
                   pr.proveedor, COALESCE(pr.lead_time_dias, 15) AS lead_time_dias
            FROM inventarios i
            JOIN materiales m ON m.material_id = i.material_id
            JOIN sucursales s ON s.plant = i.plant
            LEFT JOIN coberturas_objetivo c ON c.material_id = i.material_id
            LEFT JOIN proveedores pr ON pr.material_id = i.material_id
            WHERE {where_sql}
            ORDER BY i.material_id, i.plant""",
        params,
    ).fetchall()

    if not candidatos:
        return {"total": 0, "page": page, "page_size": page_size, "items": [], "generado": _now()}

    material_ids = sorted({r["material_id"] for r in candidatos})
    placeholders = ",".join("?" * len(material_ids))
    ventas_rows = db.execute(
        f"""SELECT material_id, plant, anio_mes, SUM(cantidad_m2) AS m2
            FROM ventas_mensuales
            WHERE material_id IN ({placeholders})
            GROUP BY material_id, plant, anio_mes
            ORDER BY anio_mes""",
        material_ids,
    ).fetchall()

    m2_por_caja_map = {r["material_id"]: r["m2_por_caja"] for r in candidatos}
    serie: dict[tuple[str, str], list[tuple[str, float]]] = {}
    # m2 CRUDO (sin convertir a cajas) por línea+mes -- lo necesita
    # _consumo_mes_referencia_corregido para derivar el factor piezas->m2 de
    # cada material contra ventas_stats_mensuales (ver RATIO_M2_POR_PIEZA_FALLBACK).
    m2_por_linea_mes: dict[tuple[str, str], dict[str, float]] = {}
    for r in ventas_rows:
        key = (r["material_id"], r["plant"])
        m2 = r["m2"] or 0.0
        cajas = calc_m2_a_cajas(m2, m2_por_caja_map.get(r["material_id"]))
        serie.setdefault(key, []).append((r["anio_mes"], cajas))
        m2_por_linea_mes.setdefault(key, {})[r["anio_mes"]] = m2

    # T25 (waykee 290148): inventario fin de mes, batch en UNA query (mismo
    # patrón que ventas_rows arriba) -- kardex_diario todavía no aterriza en
    # este dataset (T20/290120 sigue sin mergear/poblar con datos reales de
    # SAP), así que se degrada con gracia: kardex_disponible=False y cada mes
    # queda en None hasta que la tabla exista.
    kardex_disponible = _tabla_existe(db, "kardex_diario")
    kardex_por_linea: dict[tuple[str, str], list[tuple[str, float]]] = {}
    salidas_por_linea: dict[tuple[str, str], list[tuple[str, float]]] = {}
    if kardex_disponible:
        kardex_rows = db.execute(
            f"""SELECT material_id, plant, fecha, saldo_fin_dia
                FROM kardex_diario
                WHERE material_id IN ({placeholders})
                ORDER BY material_id, plant, fecha""",
            material_ids,
        ).fetchall()
        for kr in kardex_rows:
            kardex_por_linea.setdefault((kr["material_id"], kr["plant"]), []).append(
                (kr["fecha"], kr["saldo_fin_dia"])
            )
        salidas_por_linea = _cargar_salidas_diarias(db, material_ids, placeholders)

    # T28 (waykee 291765): estrategia de Promedio 3 resuelta UNA vez por
    # request (no por línea) -- ver mensaje puente waykee 290066->291765.
    modo_promedio3 = _modo_promedio3(db)
    stats_por_linea_mes: dict = {}
    if modo_promedio3 == "stats":
        stats_por_linea_mes = _cargar_stats_mensuales(db, material_ids, placeholders)

    # T27 (waykee 291745): serie de EXHIBICIÓN para el popup de decisión --
    # últimos MESES_SERIE_DISPLAY meses calendario contiguos, rellenando con 0
    # los meses sin venta (a diferencia de `serie`, que solo trae meses con
    # movimiento y por eso deja huecos). Con el motor de 3 promedios (T28) esta
    # serie YA NO es solo informativa: es la base de PROMEDIO_GENERAL, que a su
    # vez maneja cobertura/faltante/compra sugerida.
    ref_row = db.execute("SELECT MAX(anio_mes) AS m FROM ventas_mensuales").fetchone()
    ref_anio_mes = ref_row["m"] if ref_row and ref_row["m"] else datetime.now(timezone.utc).strftime("%Y-%m")
    meses_display = _meses_contiguos(ref_anio_mes, MESES_SERIE_DISPLAY)

    mes_ref = meses_display[-1]

    def factor_piezas_a_m2_linea(material_id: str, plant: str) -> float:
        """Factor piezas POS -> m2 de esta línea (ver calc_factor_m2_por_pieza),
        derivado SOLO de meses previos al de referencia (nunca del propio mes_ref,
        que es justo el que se está corrigiendo -- evita circularidad). Se usa
        tanto para corregir el consumo del mes de referencia como para convertir
        max_ticket/max_linea (piezas) a m2 en el ajuste de Promedio 3 de
        CUALQUIER mes de la ventana, ya que esas columnas de
        ventas_stats_mensuales están en piezas POS en todos los meses, no solo
        en el de referencia (ver comprasai_v6_reconciliacion.json)."""
        m2_por_mes = m2_por_linea_mes.get((material_id, plant), {})
        pares_previos = [
            (m2_por_mes[mes], stats_por_linea_mes[(material_id, plant, mes)]["suma_cantidad"] or 0.0)
            for mes in meses_display
            if mes != mes_ref and mes in m2_por_mes and (material_id, plant, mes) in stats_por_linea_mes
        ]
        return calc_factor_m2_por_pieza(pares_previos)

    def serie_pts_display(
        material_id: str, plant: str, m2_por_caja: Optional[float] = None
    ) -> list[tuple[str, float]]:
        ventas_por_mes = dict(serie.get((material_id, plant), []))
        puntos = [(mes, ventas_por_mes.get(mes, 0.0)) for mes in meses_display]
        # T28 (waykee 291765, decisión cerrada 17-sep-2026): el mes de
        # REFERENCIA (el más reciente, hoy 2026-08) viene PARCIAL en
        # ventas_mensuales -- se bloquea ese fallback y se recalcula desde
        # ventas_stats_mensuales.suma_cantidad (piezas POS, completo). Solo
        # aplica si el dataset v6 está disponible (modo_promedio3 == "stats").
        if modo_promedio3 != "stats":
            return puntos
        stats_ref = stats_por_linea_mes.get((material_id, plant, mes_ref))
        if stats_ref is None:
            return puntos
        factor = factor_piezas_a_m2_linea(material_id, plant)
        cajas_corregidas = calc_consumo_mes_referencia_corregido(
            stats_ref["suma_cantidad"] or 0.0, m2_por_caja, factor,
        )
        puntos = list(puntos)
        puntos[-1] = (mes_ref, cajas_corregidas)
        return puntos

    def promedios_linea(material_id: str, plant: str, m2_por_caja: Optional[float]) -> dict:
        """T28: Promedio 1 (media de la ventana completa), Promedio 2 (media de
        los últimos PROMEDIO2_MESES) y Promedio 3 (ventana completa con el pico
        de cada mes restado, ver _ajuste_pico_mes) + PROMEDIO_GENERAL."""
        puntos = serie_pts_display(material_id, plant, m2_por_caja)
        consumo = [v for _, v in puntos]
        promedio_1 = calc_promedio_simple(consumo)
        promedio_2 = calc_promedio_ultimos_n(consumo, PROMEDIO2_MESES)
        factor_stats = (
            factor_piezas_a_m2_linea(material_id, plant) if modo_promedio3 == "stats" else RATIO_M2_POR_PIEZA_FALLBACK
        )
        ajustes = []
        valores_ajustados = []
        for anio_mes, valor_mes in puntos:
            ajuste = _ajuste_pico_mes(
                modo_promedio3, material_id, plant, anio_mes, m2_por_caja,
                stats_por_linea_mes, salidas_por_linea, factor_stats,
            )
            valor_ajustado = calc_valor_mes_ajustado(valor_mes, ajuste["ajuste_cajas"])
            valores_ajustados.append(valor_ajustado)
            ajustes.append({
                "anio_mes": anio_mes,
                "valor_ajustado": round(valor_ajustado, 2),
                **ajuste,
            })
        promedio_3 = calc_promedio_simple(valores_ajustados)
        promedio_general = calc_promedio_general(promedio_1, promedio_2, promedio_3)
        return {
            "consumo": consumo,
            "promedio_1": promedio_1,
            "promedio_2": promedio_2,
            "promedio_3": promedio_3,
            "promedio_3_ajustes": ajustes,
            "promedio_general": promedio_general,
        }

    # Info por (material,plant) para resolver transferencias intra-corredor (RN-02).
    info_por_linea = {}
    for r in candidatos:
        key = (r["material_id"], r["plant"])
        disp_neto = round((r["disponible"] or 0) + (r["transito"] or 0) - (r["comprometido"] or 0), 2)
        promedios = promedios_linea(r["material_id"], r["plant"], r["m2_por_caja"])
        dem = promedios["promedio_general"]
        cobertura = calc_cobertura_meses(disp_neto, dem)
        info_por_linea[key] = {
            "row": r,
            "disponible_neto": disp_neto,
            "demanda_mensual": dem,
            "cobertura": cobertura,
            "promedios": promedios,
        }

    # Índice material+corredor -> lista de plants, precomputado UNA vez.
    # Antes cada línea deficitaria escaneaba TODO info_por_linea buscando a
    # sus hermanos de corredor (O(n²): con el universo sin filtrar, ~9.8k
    # líneas deficitarias x ~18k pares = ~180M iteraciones en Python puro,
    # >2 min por request) -> bajo concurrencia esto es lo que realmente
    # agotaba el busy_timeout de SQLite y producía "database is locked",
    # no solo el volumen de INSERTs. Con el índice, cada línea solo mira a
    # sus hermanos reales (O(1) promedio).
    plants_por_material_corredor: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for k, v in info_por_linea.items():
        corredor_h = v["row"]["corredor"]
        if corredor_h:
            plants_por_material_corredor.setdefault((k[0], corredor_h), []).append(k)

    # RN-02: remanente transferible por (material_id, plant) ORIGEN. Se
    # inicializa perezosamente con el excedente total de esa línea y se
    # DECREMENTA cada vez que una línea deficitaria lo consume. Sin esto,
    # cada línea deficitaria recalculaba el excedente completo del hermano
    # desde cero -> el mismo excedente se prometía varias veces a distintos
    # destinos (sobre-asignación detectada por QA 23-ago, ver waykee 290102).
    remanente_transferible: dict[tuple[str, str], float] = {}

    def _excedente_disponible(material_id: str, plant: str) -> float:
        key = (material_id, plant)
        if key not in remanente_transferible:
            info_origen = info_por_linea.get(key)
            if (
                info_origen
                and info_origen["cobertura"] is not None
                and info_origen["cobertura"] > info_origen["row"]["meses_objetivo"]
            ):
                remanente_transferible[key] = round(
                    (info_origen["cobertura"] - info_origen["row"]["meses_objetivo"]) * info_origen["demanda_mensual"],
                    2,
                )
            else:
                remanente_transferible[key] = 0.0
        return remanente_transferible[key]

    items = []
    for r in candidatos:
        key = (r["material_id"], r["plant"])
        info = info_por_linea[key]
        cobertura = info["cobertura"]
        objetivo = r["meses_objetivo"]
        dem = info["demanda_mensual"]

        if cobertura is None:
            continue  # sin demanda reciente: no hay base para sugerir (ni RN-01 aplica)
        if cobertura >= objetivo:
            continue  # RN-01: cobertura ya cubre el objetivo, SUGERIDO=0
        if solo_criticos and cobertura > 0:
            continue

        # T28 (waykee 291765): compra sugerida = fórmula del Excel de compras
        # (MesesObjetivo x PROMEDIO_GENERAL - Disponible - Tránsito,
        # sin netear de antemano -- ver calc_compra_sugerida), NO el faltante de
        # cobertura*demanda de la versión anterior. La cobertura sigue viniendo
        # de calc_cobertura_meses (RN-01, disponible_neto/dem) para decidir SI
        # se sugiere; el MONTO ya no depende de ese neteo.
        # T29 (waykee 291788, punto 4): 'comprometido' YA NO participa en el
        # MONTO -- ver docstring de calc_compra_sugerida.
        compra_sugerida = calc_compra_sugerida(
            objetivo, dem, r["disponible"], r["transito"]
        )

        # RN-02: transferencia antes que compra, dentro del mismo corredor.
        cantidad_transferir = 0.0
        detalle_transferencias = []
        if r["corredor"]:
            hermanos_keys = [
                k for k in plants_por_material_corredor.get((r["material_id"], r["corredor"]), [])
                if k[1] != r["plant"]
            ]
            hermanos_keys.sort(key=lambda k: -_excedente_disponible(*k))
            restante = compra_sugerida
            for h_material, h_plant in hermanos_keys:
                if restante <= 0:
                    break
                disponible = _excedente_disponible(h_material, h_plant)
                if disponible <= 0:
                    continue
                usar = min(disponible, restante)
                cantidad_transferir += usar
                restante -= usar
                remanente_transferible[(h_material, h_plant)] = round(disponible - usar, 2)
                detalle_transferencias.append({"desde_plant": h_plant, "cantidad": round(usar, 2)})
            cantidad_transferir = round(cantidad_transferir, 2)

        cantidad_comprar_bruta = round(max(0.0, compra_sugerida - cantidad_transferir), 2)

        # T28: redondeo SOLO a pallet completo (sin MOQ -- el Excel de compras
        # no aplica mínimo de proveedor, solo múltiplo de pallet).
        cantidad_final = calc_redondeo_pallets_completos(cantidad_comprar_bruta, int(r["cajas_por_pallet"]))
        cajas_por_pallet_int = int(r["cajas_por_pallet"]) or DEFAULT_PALLET
        n_pallets = cantidad_final // cajas_por_pallet_int if cajas_por_pallet_int else 0

        serie_pts = serie.get(key, [])[-MESES_HISTORIA:]
        tendencia = calc_tendencia([v for _, v in serie_pts])
        meses_con_venta = sum(1 for _, v in serie_pts if v > 0)
        confianza = calc_confianza(meses_con_venta, MESES_HISTORIA)

        capa = "C3" if (cantidad_transferir > 0 or cantidad_final != cantidad_comprar_bruta) else "C2"

        costo_unitario = r["costo"] or 0
        costo_estimado = round(cantidad_final * costo_unitario, 2)

        meses_actual = calc_cobertura_meses(r["disponible"] or 0.0, dem)

        partes_explicacion = [
            f"Cobertura actual {cobertura:.1f} meses vs objetivo {objetivo:.1f} meses "
            f"(PROMEDIO general {dem:.0f} cajas/mes, disponible neto {info['disponible_neto']:.0f} cajas)."
        ]
        if cantidad_transferir > 0:
            origenes = ", ".join(f"{d['desde_plant']} ({d['cantidad']:.0f})" for d in detalle_transferencias)
            partes_explicacion.append(f"Se cubren {cantidad_transferir:.0f} cajas por transferencia desde {origenes} antes de comprar (RN-02).")
        if cantidad_comprar_bruta > 0:
            partes_explicacion.append(f"Faltante a comprar: {cantidad_comprar_bruta:.0f} cajas, redondeado a {cantidad_final} cajas ({n_pallets} pallet(s) de {cajas_por_pallet_int}) del proveedor {r['proveedor'] or 's/proveedor'}.")
        if tendencia == "alza":
            partes_explicacion.append("La demanda muestra tendencia al alza en el último mes.")
        elif tendencia == "baja":
            partes_explicacion.append("La demanda muestra tendencia a la baja en el último mes.")
        explicacion = " ".join(partes_explicacion)

        saldos_fin_mes = _saldos_fin_mes(kardex_por_linea.get(key, []), meses_display)

        datos_decision = build_datos_decision(
            historia_meses=meses_display,
            historia_consumo=info["promedios"]["consumo"],
            promedio_1=info["promedios"]["promedio_1"],
            promedio_2=info["promedios"]["promedio_2"],
            promedio_3=info["promedios"]["promedio_3"],
            promedio_3_ajustes=info["promedios"]["promedio_3_ajustes"],
            promedio_general=dem,
            meses_actual=meses_actual,
            meses_con_venta=meses_con_venta,
            meses_historia=MESES_HISTORIA,
            inventario_fin_mes=saldos_fin_mes,
            kardex_disponible=kardex_disponible,
            disponible=r["disponible"],
            transito=r["transito"],
            comprometido=r["comprometido"],
            disponible_neto=info["disponible_neto"],
            cobertura_actual=cobertura,
            meses_objetivo=objetivo,
            compra_sugerida=compra_sugerida,
            proveedor=r["proveedor"],
            moq_cajas=int(r["moq_cajas"]),
            cajas_por_pallet=cajas_por_pallet_int,
            lead_time_dias=r["lead_time_dias"],
            m2_por_caja=r["m2_por_caja"],
            costo_unitario=costo_unitario,
            cantidad_transferir=cantidad_transferir,
            detalle_transferencias=detalle_transferencias,
            cantidad_comprar_bruta=cantidad_comprar_bruta,
            cantidad_final=cantidad_final,
            n_pallets=n_pallets,
        )

        items.append({
            "material_id": r["material_id"],
            "descripcion": r["descripcion"],
            "abc": r["abc"],
            "plant": r["plant"],
            "corredor": r["corredor"],
            "proveedor": r["proveedor"],
            "cobertura_actual": round(cobertura, 2),
            "cobertura_objetivo": objetivo,
            "cantidad_transferir": cantidad_transferir,
            "detalle_transferencias": detalle_transferencias,
            "cantidad_comprar_bruta": cantidad_comprar_bruta,
            "cantidad_final": cantidad_final,
            "moq_cajas": r["moq_cajas"],
            "costo_estimado": costo_estimado,
            "confianza": confianza,
            "tendencia": tendencia,
            "capa": capa,
            "explicacion": explicacion,
            "datos_decision": datos_decision,
            "_faltante_bruto": compra_sugerida,
            "_costo_unitario": costo_unitario,
        })

    # Prioriza lo más crítico (menor cobertura primero); el orden/total
    # corren sobre TODO el universo filtrado para que el ranking sea correcto,
    # pero solo se PERSISTE/devuelve la página pedida (fix QA 23-ago: antes se
    # insertaba el universo completo -~9.8k filas- en cada click, ignorando
    # page_size y sin limpiar la tabla -> DB de 184MB y locks bajo concurrencia).
    items.sort(key=lambda x: x["cobertura_actual"])
    total = len(items)
    start = (page - 1) * page_size
    pagina = items[start:start + page_size]

    now = _now()
    insert_rows = []
    for it in pagina:
        row_id = str(uuid.uuid4())
        it["id"] = row_id
        it["estado"] = "propuesto"
        insert_rows.append((
            row_id, it["material_id"], it["plant"], it["descripcion"], it["abc"],
            it["cobertura_actual"], it["cobertura_objetivo"], it["_faltante_bruto"],
            it["cantidad_transferir"], it["cantidad_comprar_bruta"], it["cantidad_final"],
            it["_costo_unitario"], it["costo_estimado"], it["confianza"], it["tendencia"],
            it["capa"], it["explicacion"],
            # T19 (waykee 290116): "factores" (pesos hardcodeados 40/25/15/10/10)
            # se elimina -- ya no se genera ni se inventa nada en su lugar; la
            # columna queda vacía ("[]") solo por compatibilidad de esquema con
            # filas históricas. datos_decision_json es la fuente real ahora.
            "[]",
            json.dumps(it["datos_decision"], ensure_ascii=False),
            "propuesto", now, now,
        ))
        del it["_faltante_bruto"], it["_costo_unitario"]

    # DELETE previo (solo 'propuesto' — 'aprobado'/'rechazado' quedan como
    # historial/auditoría intactos) + executemany en UNA sola transacción.
    db.execute("DELETE FROM sugeridos_generados WHERE estado = 'propuesto'")
    if insert_rows:
        db.executemany(
            """INSERT INTO sugeridos_generados (
                id, material_id, plant, descripcion, abc, cobertura_actual, cobertura_objetivo,
                cantidad_sugerida, cantidad_transferir, cantidad_comprar, cantidad_final,
                costo_unitario, costo_estimado, confianza, tendencia, capa, explicacion, factores_json,
                datos_decision_json, estado, creado, actualizado
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            insert_rows,
        )
    db.commit()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": pagina,
        "generado": now,
    }


@router.get("/lista")
def lista_sugeridos(
    estado: Optional[str] = Query(None, pattern="^(propuesto|aprobado|rechazado)$"),
    db: sqlite3.Connection = Depends(get_db),
):
    """Vista del Gerente: lo ya propuesto por el Planeador, listo para decidir."""
    _ensure_tables(db)
    where = "WHERE estado = ?" if estado else ""
    params = [estado] if estado else []
    rows = [
        dict(r)
        for r in db.execute(
            f"""SELECT * FROM sugeridos_generados {where} ORDER BY actualizado DESC""",
            params,
        ).fetchall()
    ]
    for r in rows:
        # T19 (waykee 290116): factores_json queda como columna muerta
        # (compatibilidad con filas históricas) -- ya no se expone al
        # frontend; datos_decision_json es la fuente real de la explicación.
        r.pop("factores_json", None)
        r["datos_decision"] = json.loads(r.pop("datos_decision_json", None) or "{}")
    return {"items": rows}


@router.get("/backorder-detalle")
def backorder_detalle(
    material_id: str = Query(...),
    plant: str = Query(...),
    db: sqlite3.Connection = Depends(get_db),
):
    """T25 (waykee 290148): drill-down documento a documento del comprometido
    (backorder) de una línea material+plant, para el clic desde ExplainPanel.
    La tabla `backorder_detalle` (dataset v5: documento, posicion, cliente,
    cantidad_pendiente, fecha_documento, fecha_entrega_comprometida) la sigue
    extrayendo el Data Expert en waykee 290147 -- mientras no exista se
    responde `disponible: False` para que el frontend muestre el aviso de
    "detalle en camino" en vez de un 500."""
    if not _tabla_existe(db, "backorder_detalle"):
        return {"disponible": False, "material_id": material_id, "plant": plant, "documentos": []}
    rows = db.execute(
        """SELECT documento, posicion, cliente, cantidad_pendiente,
                  fecha_documento, fecha_entrega_comprometida
           FROM backorder_detalle
           WHERE material_id = ? AND plant = ?
           ORDER BY fecha_entrega_comprometida""",
        [material_id, plant],
    ).fetchall()
    return {"disponible": True, "material_id": material_id, "plant": plant, "documentos": rows}


@router.get("/pedidos-detalle")
def pedidos_detalle(
    material_id: str = Query(...),
    plant: str = Query(...),
    db: sqlite3.Connection = Depends(get_db),
):
    """T25 (waykee 290148): drill-down por orden de compra de "pedidos por
    cumplir" (tránsito) de una línea material+plant. Tabla
    `pedidos_compra_detalle` (dataset v5: po, posicion, proveedor,
    cantidad_pendiente, fecha_po, fecha_entrega_estimada), misma coordinación
    con el Data Expert en waykee 290147 y mismo fallback degradado que
    backorder-detalle mientras no aterriza."""
    if not _tabla_existe(db, "pedidos_compra_detalle"):
        return {"disponible": False, "material_id": material_id, "plant": plant, "pedidos": []}
    rows = db.execute(
        """SELECT po, posicion, proveedor, cantidad_pendiente,
                  fecha_po, fecha_entrega_estimada
           FROM pedidos_compra_detalle
           WHERE material_id = ? AND plant = ?
           ORDER BY fecha_entrega_estimada""",
        [material_id, plant],
    ).fetchall()
    return {"disponible": True, "material_id": material_id, "plant": plant, "pedidos": rows}


@router.put("/{sugerido_id}/editar")
def editar_sugerido(
    sugerido_id: str,
    cantidad_final: float = Body(..., embed=True),
    justificacion: str = Body(..., embed=True, min_length=5),
    db: sqlite3.Connection = Depends(get_db),
):
    """RN-08: toda edición manual de la cantidad requiere justificación."""
    _ensure_tables(db)
    row = db.execute("SELECT id, costo_unitario FROM sugeridos_generados WHERE id = ?", [sugerido_id]).fetchone()
    if not row:
        raise HTTPException(404, f"Sugerido '{sugerido_id}' no encontrado")
    costo_estimado = round(cantidad_final * (row["costo_unitario"] or 0), 2)
    db.execute(
        """UPDATE sugeridos_generados
           SET cantidad_final = ?, costo_estimado = ?, justificacion_edicion = ?, actualizado = ?
           WHERE id = ?""",
        [cantidad_final, costo_estimado, justificacion, _now(), sugerido_id],
    )
    db.commit()
    return {"ok": True, "id": sugerido_id, "cantidad_final": cantidad_final, "costo_estimado": costo_estimado}


@router.post("/decidir")
def decidir_sugeridos(
    ids: list[str] = Body(..., embed=True),
    accion: str = Body(..., embed=True, pattern="^(aprobar|rechazar)$"),
    aprobado_por: str = Body("Gerente Demo", embed=True),
    db: sqlite3.Connection = Depends(get_db),
):
    """Clic 3: el Gerente aprueba o rechaza uno o varios sugeridos (bulk)."""
    _ensure_tables(db)
    if not ids:
        raise HTTPException(400, "ids vacío")
    nuevo_estado = "aprobado" if accion == "aprobar" else "rechazado"
    placeholders = ",".join("?" * len(ids))
    db.execute(
        f"""UPDATE sugeridos_generados
            SET estado = ?, aprobado_por = ?, actualizado = ?
            WHERE id IN ({placeholders})""",
        [nuevo_estado, aprobado_por, _now(), *ids],
    )
    db.commit()
    afectados = db.execute(
        f"SELECT id, material_id, plant, cantidad_final, costo_estimado FROM sugeridos_generados WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    return {
        "ok": True,
        "estado": nuevo_estado,
        "afectados": len(afectados),
        "monto_total": round(sum((a["costo_estimado"] or 0) for a in afectados), 2),
        "items": afectados,
    }


@router.get("/exportar-sap")
def exportar_sap(db: sqlite3.Connection = Depends(get_db)):
    """RF-009: plantilla de carga masiva a SAP con los sugeridos aprobados."""
    _ensure_tables(db)
    rows = db.execute(
        """SELECT material_id, plant, cantidad_final, costo_estimado, aprobado_por, actualizado
           FROM sugeridos_generados WHERE estado = 'aprobado' ORDER BY plant, material_id"""
    ).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Material", "Centro", "Cantidad", "UMB", "Importe estimado", "Aprobado por", "Fecha aprobación"])
    for r in rows:
        writer.writerow([
            r["material_id"], r["plant"], int(r["cantidad_final"] or 0), "CAJ",
            r["costo_estimado"], r["aprobado_por"], r["actualizado"],
        ])
    buf.seek(0)
    filename = f"plantilla_sap_comprasai_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
