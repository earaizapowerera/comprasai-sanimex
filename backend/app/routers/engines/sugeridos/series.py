"""Series mensuales: meses contiguos, saldos fin de mes y días sin inventario."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional

from .persistencia import _tabla_existe


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


def _cargar_dias_sin_inventario_tabla(
    db: sqlite3.Connection, material_ids: list[str], placeholders: str
) -> dict[tuple[str, str, str], float]:
    """v7 (mensaje puente 290066->291788, dataset data-real-car-v7): la tabla
    dias_sin_inventario_mensual llega YA derivada del kardex por el Data
    Expert (misma fuente que calc_dias_sin_inventario_por_mes) -- se lee tal
    cual para evitar recomputar 3.9M combos material x plant x mes en
    runtime. Solo se usa si trae las columnas esperadas; si el schema no
    calza, se ignora con gracia y el llamador sigue calculando desde
    kardex_diario (fallback sin cambios)."""
    if not _tabla_existe(db, "dias_sin_inventario_mensual"):
        return {}
    cols = {row["name"] for row in db.execute("PRAGMA table_info(dias_sin_inventario_mensual)")}
    if not {"material_id", "plant", "anio_mes", "dias_sin_inventario"} <= cols:
        return {}
    rows = db.execute(
        f"""SELECT material_id, plant, anio_mes, dias_sin_inventario
            FROM dias_sin_inventario_mensual
            WHERE material_id IN ({placeholders})""",
        material_ids,
    ).fetchall()
    return {(r["material_id"], r["plant"], r["anio_mes"]): r["dias_sin_inventario"] for r in rows}


def _fusionar_dias_sin_inventario_tabla(
    resultado: dict[str, dict],
    tabla_dsi: dict[tuple[str, str, str], float],
    material_id: str,
    plant: str,
) -> dict[str, dict]:
    """La tabla v7 (HANA) manda sobre el cálculo local mes a mes cuando cubre
    ese mes -- misma fuente, solo evita recomputar. Si no lo cubre, se
    conserva el valor ya calculado desde kardex_diario (o el 'sin datos' por
    default) sin cambios."""
    fusion = dict(resultado)
    for mes in resultado:
        valor = tabla_dsi.get((material_id, plant, mes))
        if valor is not None:
            dias_mes = len(_dias_calendario_mes(mes))
            fusion[mes] = {
                "dias": valor,
                "dias_con_dato": dias_mes,
                "dias_mes": dias_mes,
                "cobertura_parcial": False,
            }
    return fusion
