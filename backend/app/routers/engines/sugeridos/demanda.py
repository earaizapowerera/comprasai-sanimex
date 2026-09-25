"""Contexto de demanda de un request de /generar: series de venta, kardex,
stats POS y el motor de 3 promedios (T28) por línea material+plant.

Antes vivía como closures dentro de generar_sugeridos(); aquí es una clase
para que cada paso quede en una función corta y testeable."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .calculos import (
    calc_consumo_mes_referencia_corregido,
    calc_factor_m2_por_pieza,
    calc_m2_a_cajas,
    calc_promedio_general,
    calc_promedio_simple,
    calc_promedio_ultimos_n,
    calc_valor_mes_ajustado,
)
from .cargas import _ajuste_pico_mes, _cargar_salidas_diarias, _cargar_stats_mensuales, _modo_promedio3
from .constantes import MESES_SERIE_DISPLAY, PROMEDIO2_MESES, RATIO_M2_POR_PIEZA_FALLBACK
from .persistencia import _tabla_existe
from .series import _cargar_dias_sin_inventario_tabla, _meses_contiguos


class ContextoDemanda:
    """Todo lo que se carga UNA vez por request (en batch) para evaluar las
    líneas candidatas."""

    def __init__(self, db: sqlite3.Connection, candidatos: list, material_ids: list[str], placeholders: str):
        self._cargar_ventas(db, candidatos, material_ids, placeholders)
        self._cargar_kardex(db, material_ids, placeholders)
        # T29 (punto 3, v7): tabla oficial dias_sin_inventario_mensual -- si
        # existe, manda sobre el cálculo local mes a mes (ver _fusionar_...).
        self.tabla_dsi = _cargar_dias_sin_inventario_tabla(db, material_ids, placeholders)
        # T28 (waykee 291765): estrategia de Promedio 3 resuelta UNA vez por
        # request (no por línea) -- ver mensaje puente waykee 290066->291765.
        self.modo_promedio3 = _modo_promedio3(db)
        self.stats_por_linea_mes: dict = {}
        if self.modo_promedio3 == "stats":
            self.stats_por_linea_mes = _cargar_stats_mensuales(db, material_ids, placeholders)
        # T27 (waykee 291745): serie de EXHIBICIÓN para el popup de decisión --
        # últimos MESES_SERIE_DISPLAY meses calendario contiguos, rellenando con 0
        # los meses sin venta (a diferencia de `serie`, que solo trae meses con
        # movimiento y por eso deja huecos). Con el motor de 3 promedios (T28) esta
        # serie YA NO es solo informativa: es la base de PROMEDIO_GENERAL, que a su
        # vez maneja cobertura/faltante/compra sugerida.
        ref_row = db.execute("SELECT MAX(anio_mes) AS m FROM ventas_mensuales").fetchone()
        ref_anio_mes = ref_row["m"] if ref_row and ref_row["m"] else datetime.now(timezone.utc).strftime("%Y-%m")
        self.meses_display = _meses_contiguos(ref_anio_mes, MESES_SERIE_DISPLAY)
        self.mes_ref = self.meses_display[-1]

    def _cargar_ventas(self, db: sqlite3.Connection, candidatos: list, material_ids: list[str], placeholders: str):
        ventas_rows = db.execute(
            f"""SELECT material_id, plant, anio_mes, SUM(cantidad_m2) AS m2
                FROM ventas_mensuales
                WHERE material_id IN ({placeholders})
                GROUP BY material_id, plant, anio_mes
                ORDER BY anio_mes""",
            material_ids,
        ).fetchall()
        m2_por_caja_map = {r["material_id"]: r["m2_por_caja"] for r in candidatos}
        self.serie: dict[tuple[str, str], list[tuple[str, float]]] = {}
        # m2 CRUDO (sin convertir a cajas) por línea+mes -- lo necesita
        # factor_piezas_a_m2_linea para derivar el factor piezas->m2 de cada
        # material contra ventas_stats_mensuales (ver RATIO_M2_POR_PIEZA_FALLBACK).
        self.m2_por_linea_mes: dict[tuple[str, str], dict[str, float]] = {}
        for r in ventas_rows:
            key = (r["material_id"], r["plant"])
            m2 = r["m2"] or 0.0
            cajas = calc_m2_a_cajas(m2, m2_por_caja_map.get(r["material_id"]))
            self.serie.setdefault(key, []).append((r["anio_mes"], cajas))
            self.m2_por_linea_mes.setdefault(key, {})[r["anio_mes"]] = m2

    def _cargar_kardex(self, db: sqlite3.Connection, material_ids: list[str], placeholders: str):
        # T25 (waykee 290148): inventario fin de mes, batch en UNA query (mismo
        # patrón que ventas_rows) -- si kardex_diario no existe en el dataset
        # se degrada con gracia: kardex_disponible=False y cada mes queda en
        # None hasta que la tabla exista.
        self.kardex_disponible = _tabla_existe(db, "kardex_diario")
        self.kardex_por_linea: dict[tuple[str, str], list[tuple[str, float]]] = {}
        self.salidas_por_linea: dict[tuple[str, str], list[tuple[str, float]]] = {}
        if not self.kardex_disponible:
            return
        kardex_rows = db.execute(
            f"""SELECT material_id, plant, fecha, saldo_fin_dia
                FROM kardex_diario
                WHERE material_id IN ({placeholders})
                ORDER BY material_id, plant, fecha""",
            material_ids,
        ).fetchall()
        for kr in kardex_rows:
            self.kardex_por_linea.setdefault((kr["material_id"], kr["plant"]), []).append(
                (kr["fecha"], kr["saldo_fin_dia"])
            )
        self.salidas_por_linea = _cargar_salidas_diarias(db, material_ids, placeholders)

    def factor_piezas_a_m2_linea(self, material_id: str, plant: str) -> float:
        """Factor piezas POS -> m2 de esta línea (ver calc_factor_m2_por_pieza),
        derivado SOLO de meses previos al de referencia (nunca del propio mes_ref,
        que es justo el que se está corrigiendo -- evita circularidad). Se usa
        tanto para corregir el consumo del mes de referencia como para convertir
        max_ticket/max_linea (piezas) a m2 en el ajuste de Promedio 3 de
        CUALQUIER mes de la ventana, ya que esas columnas de
        ventas_stats_mensuales están en piezas POS en todos los meses, no solo
        en el de referencia (ver comprasai_v6_reconciliacion.json)."""
        m2_por_mes = self.m2_por_linea_mes.get((material_id, plant), {})
        stats = self.stats_por_linea_mes
        pares_previos = [
            (m2_por_mes[mes], stats[(material_id, plant, mes)]["suma_cantidad"] or 0.0)
            for mes in self.meses_display
            if mes != self.mes_ref and mes in m2_por_mes and (material_id, plant, mes) in stats
        ]
        return calc_factor_m2_por_pieza(pares_previos)

    def serie_pts_display(
        self, material_id: str, plant: str, m2_por_caja: Optional[float] = None
    ) -> list[tuple[str, float]]:
        ventas_por_mes = dict(self.serie.get((material_id, plant), []))
        puntos = [(mes, ventas_por_mes.get(mes, 0.0)) for mes in self.meses_display]
        # T28 (waykee 291765, decisión cerrada 17-sep-2026): el mes de
        # REFERENCIA (el más reciente, hoy 2026-08) viene PARCIAL en
        # ventas_mensuales -- se bloquea ese fallback y se recalcula desde
        # ventas_stats_mensuales.suma_cantidad (piezas POS, completo). Solo
        # aplica si el dataset v6 está disponible (modo_promedio3 == "stats").
        if self.modo_promedio3 != "stats":
            return puntos
        stats_ref = self.stats_por_linea_mes.get((material_id, plant, self.mes_ref))
        if stats_ref is None:
            return puntos
        factor = self.factor_piezas_a_m2_linea(material_id, plant)
        cajas_corregidas = calc_consumo_mes_referencia_corregido(
            stats_ref["suma_cantidad"] or 0.0, m2_por_caja, factor,
        )
        puntos = list(puntos)
        puntos[-1] = (self.mes_ref, cajas_corregidas)
        return puntos

    def promedios_linea(self, material_id: str, plant: str, m2_por_caja: Optional[float]) -> dict:
        """T28: Promedio 1 (media de la ventana completa), Promedio 2 (media de
        los últimos PROMEDIO2_MESES) y Promedio 3 (ventana completa con el pico
        de cada mes restado, ver _ajuste_pico_mes) + PROMEDIO_GENERAL."""
        puntos = self.serie_pts_display(material_id, plant, m2_por_caja)
        consumo = [v for _, v in puntos]
        promedio_1 = calc_promedio_simple(consumo)
        promedio_2 = calc_promedio_ultimos_n(consumo, PROMEDIO2_MESES)
        ajustes, valores_ajustados = self._ajustes_promedio3(material_id, plant, m2_por_caja, puntos)
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

    def _ajustes_promedio3(self, material_id: str, plant: str, m2_por_caja: Optional[float],
                           puntos: list[tuple[str, float]]) -> tuple[list[dict], list[float]]:
        factor_stats = (
            self.factor_piezas_a_m2_linea(material_id, plant)
            if self.modo_promedio3 == "stats" else RATIO_M2_POR_PIEZA_FALLBACK
        )
        ajustes = []
        valores_ajustados = []
        for anio_mes, valor_mes in puntos:
            ajuste = _ajuste_pico_mes(
                self.modo_promedio3, material_id, plant, anio_mes, m2_por_caja,
                self.stats_por_linea_mes, self.salidas_por_linea, factor_stats,
            )
            valor_ajustado = calc_valor_mes_ajustado(valor_mes, ajuste["ajuste_cajas"])
            valores_ajustados.append(valor_ajustado)
            ajustes.append({
                "anio_mes": anio_mes,
                "valor_ajustado": round(valor_ajustado, 2),
                **ajuste,
            })
        return ajustes, valores_ajustados
