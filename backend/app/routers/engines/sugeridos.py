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

MESES_HISTORIA = 6  # ventana de meses usada para demanda promedio y tendencia
MESES_DEMANDA = 3    # promedio móvil corto para cobertura/faltante (más reactivo)
DEFAULT_MOQ = 20
DEFAULT_PALLET = 40
DEFAULT_OBJETIVO_MESES = 2.0


# ---------------------------------------------------------------------------
# Funciones puras (C1) — sin I/O, testeables 1:1 contra los casos golden.
# ---------------------------------------------------------------------------

def calc_m2_a_cajas(m2: float, m2_por_caja: Optional[float]) -> float:
    """G8: need=100 m2, m2_por_caja=1.44 -> ceil(100/1.44) = 70 cajas."""
    if not m2_por_caja or m2_por_caja <= 0:
        return round(m2, 2)
    return math.ceil(m2 / m2_por_caja)


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


def calc_motivo_redondeo(
    bruta: float, tras_moq: float, final: float, moq: int, cajas_por_pallet: Optional[int]
) -> str:
    """T19 (waykee 290116): texto determinista de POR QUÉ se llegó de la
    cantidad bruta a comprar (faltante - transferencia) a la cantidad final,
    en términos de los redondeos RF-011 (MOQ/empaque) y RF-016 (pallet)
    REALMENTE aplicados -- no una etiqueta genérica."""
    if bruta <= 0:
        return "Sin compra: el faltante quedó cubierto por transferencia (RN-02)."
    partes = []
    if tras_moq > bruta:
        partes.append(f"se sube de {bruta:.0f} a {tras_moq:.0f} cajas por MOQ mínimo del proveedor ({moq} cajas)")
    if final > tras_moq:
        partes.append(f"se redondea de {tras_moq:.0f} a {final:.0f} cajas por múltiplo de pallet ({cajas_por_pallet} cajas/pallet)")
    if not partes:
        return f"Sin ajuste: {bruta:.0f} cajas ya cumple MOQ ({moq}) y pallet ({cajas_por_pallet})."
    texto = "; ".join(partes)
    return texto[0].upper() + texto[1:] + "."


def build_datos_decision(
    *,
    serie_pts: list[tuple[str, float]],
    demanda_promedio_3m: float,
    meses_con_venta: int,
    meses_historia: int,
    disponible: float,
    transito: float,
    comprometido: float,
    disponible_neto: float,
    cobertura_actual: Optional[float],
    meses_objetivo: float,
    faltante_bruto: float,
    proveedor: Optional[str],
    moq_cajas: int,
    cajas_por_pallet: int,
    lead_time_dias: int,
    m2_por_caja: Optional[float],
    costo_unitario: float,
    cantidad_transferir: float,
    detalle_transferencias: list[dict],
    cantidad_comprar_bruta: float,
    cantidad_tras_moq: float,
    cantidad_final: float,
    meses_demanda: int = MESES_DEMANDA,
    inventario_fin_mes: Optional[dict[str, Optional[float]]] = None,
    kardex_disponible: bool = False,
) -> dict:
    """T19 (waykee 290116): inputs REALES que entraron en la fórmula del
    sugerido -- reemplaza los pesos hardcodeados de 'factores' (40/25/15/10/10,
    waykee 290116 msg inicial) que no salían de ningún cálculo. Cada campo de
    este dict es trazable a una variable ya calculada en generar_sugeridos(),
    no un valor inventado.

    T25 (waykee 290148): feedback directo de Enrique sobre T19 -- la
    explicación no era coherente porque no mostraba los datos que un humano
    usaría para decidir. Se agregan:
      - `incluido_promedio_3m` por mes en `serie_demanda`: marca cuáles de los
        `meses_historia` puntos entraron realmente al promedio corto
        (`meses_demanda`, los últimos N) usado para cobertura/faltante. Deja
        el campo listo para que T21 marque además los meses excluidos por
        desabasto (`meses_excluidos_desabasto`, aún vacío -- T21 no ha
        aterrizado el umbral).
      - `inventario_fin_mes`: saldo de fin de mes (kardex_diario.saldo_fin_dia
        del último día con movimiento <= fin de mes) alineado a los mismos
        meses de `serie_demanda`. `kardex_disponible=False` cuando la tabla
        kardex_diario todavía no existe en el dataset (T20/290120 aún no
        aterriza) -- el valor de cada mes viene en None y el frontend debe
        mostrar el aviso de "disponible próximamente", igual que hace con
        backorder/pedidos vía los endpoints de detalle."""
    n_incluidos = min(meses_demanda, len(serie_pts))
    corte = len(serie_pts) - n_incluidos
    inventario_fin_mes = inventario_fin_mes or {}
    return {
        "serie_demanda": [
            {
                "anio_mes": anio_mes,
                "cajas": cajas,
                "incluido_promedio_3m": idx >= corte,
            }
            for idx, (anio_mes, cajas) in enumerate(serie_pts)
        ],
        "demanda_promedio_3m": round(demanda_promedio_3m, 2),
        "meses_con_venta": meses_con_venta,
        "meses_historia": meses_historia,
        "meses_demanda": meses_demanda,
        "meses_excluidos_desabasto": [],
        "inventario_fin_mes": [
            {"anio_mes": anio_mes, "saldo": inventario_fin_mes.get(anio_mes)}
            for anio_mes, _ in serie_pts
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
        "faltante_bruto": faltante_bruto,
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
        "redondeo": {
            "cantidad_comprar_bruta": cantidad_comprar_bruta,
            "cantidad_tras_moq": cantidad_tras_moq,
            "cantidad_final": cantidad_final,
            "motivo": calc_motivo_redondeo(cantidad_comprar_bruta, cantidad_tras_moq, cantidad_final, moq_cajas, cajas_por_pallet),
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
    for r in ventas_rows:
        key = (r["material_id"], r["plant"])
        cajas = calc_m2_a_cajas(r["m2"] or 0.0, m2_por_caja_map.get(r["material_id"]))
        serie.setdefault(key, []).append((r["anio_mes"], cajas))

    # T25 (waykee 290148): inventario fin de mes, batch en UNA query (mismo
    # patrón que ventas_rows arriba) -- kardex_diario todavía no aterriza en
    # este dataset (T20/290120 sigue sin mergear/poblar con datos reales de
    # SAP), así que se degrada con gracia: kardex_disponible=False y cada mes
    # queda en None hasta que la tabla exista.
    kardex_disponible = _tabla_existe(db, "kardex_diario")
    kardex_por_linea: dict[tuple[str, str], list[tuple[str, float]]] = {}
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

    def demanda_mensual(material_id: str, plant: str, n_meses: int) -> float:
        puntos = serie.get((material_id, plant), [])[-n_meses:]
        if not puntos:
            return 0.0
        return sum(v for _, v in puntos) / len(puntos)

    # Info por (material,plant) para resolver transferencias intra-corredor (RN-02).
    info_por_linea = {}
    for r in candidatos:
        key = (r["material_id"], r["plant"])
        disp_neto = round((r["disponible"] or 0) + (r["transito"] or 0) - (r["comprometido"] or 0), 2)
        dem = demanda_mensual(r["material_id"], r["plant"], MESES_DEMANDA)
        cobertura = calc_cobertura_meses(disp_neto, dem)
        info_por_linea[key] = {
            "row": r,
            "disponible_neto": disp_neto,
            "demanda_mensual": dem,
            "cobertura": cobertura,
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

        faltante_bruto = round((objetivo - cobertura) * dem, 2)

        # RN-02: transferencia antes que compra, dentro del mismo corredor.
        cantidad_transferir = 0.0
        detalle_transferencias = []
        if r["corredor"]:
            hermanos_keys = [
                k for k in plants_por_material_corredor.get((r["material_id"], r["corredor"]), [])
                if k[1] != r["plant"]
            ]
            hermanos_keys.sort(key=lambda k: -_excedente_disponible(*k))
            restante = faltante_bruto
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

        cantidad_comprar_bruta = round(max(0.0, faltante_bruto - cantidad_transferir), 2)

        cantidad_tras_moq = calc_redondeo_moq(cantidad_comprar_bruta, int(r["moq_cajas"]))
        cantidad_final = calc_redondeo_pallet(cantidad_tras_moq, int(r["cajas_por_pallet"]))

        serie_pts = serie.get(key, [])[-MESES_HISTORIA:]
        tendencia = calc_tendencia([v for _, v in serie_pts])
        meses_con_venta = sum(1 for _, v in serie_pts if v > 0)
        confianza = calc_confianza(meses_con_venta, MESES_HISTORIA)

        capa = "C3" if (cantidad_transferir > 0 or cantidad_final != cantidad_comprar_bruta) else "C2"

        costo_unitario = r["costo"] or 0
        costo_estimado = round(cantidad_final * costo_unitario, 2)

        partes_explicacion = [
            f"Cobertura actual {cobertura:.1f} meses vs objetivo {objetivo:.1f} meses "
            f"(demanda promedio {dem:.0f} cajas/mes, disponible neto {info['disponible_neto']:.0f} cajas)."
        ]
        if cantidad_transferir > 0:
            origenes = ", ".join(f"{d['desde_plant']} ({d['cantidad']:.0f})" for d in detalle_transferencias)
            partes_explicacion.append(f"Se cubren {cantidad_transferir:.0f} cajas por transferencia desde {origenes} antes de comprar (RN-02).")
        if cantidad_comprar_bruta > 0:
            partes_explicacion.append(f"Faltante a comprar: {cantidad_comprar_bruta:.0f} cajas, redondeado a {cantidad_final} cajas por MOQ/pallet del proveedor {r['proveedor'] or 's/proveedor'}.")
        if tendencia == "alza":
            partes_explicacion.append("La demanda muestra tendencia al alza en el último mes.")
        elif tendencia == "baja":
            partes_explicacion.append("La demanda muestra tendencia a la baja en el último mes.")
        explicacion = " ".join(partes_explicacion)

        saldos_fin_mes = _saldos_fin_mes(
            kardex_por_linea.get(key, []), [anio_mes for anio_mes, _ in serie_pts]
        )

        datos_decision = build_datos_decision(
            serie_pts=serie_pts,
            demanda_promedio_3m=dem,
            meses_con_venta=meses_con_venta,
            meses_historia=MESES_HISTORIA,
            meses_demanda=MESES_DEMANDA,
            inventario_fin_mes=saldos_fin_mes,
            kardex_disponible=kardex_disponible,
            disponible=r["disponible"],
            transito=r["transito"],
            comprometido=r["comprometido"],
            disponible_neto=info["disponible_neto"],
            cobertura_actual=cobertura,
            meses_objetivo=objetivo,
            faltante_bruto=faltante_bruto,
            proveedor=r["proveedor"],
            moq_cajas=int(r["moq_cajas"]),
            cajas_por_pallet=int(r["cajas_por_pallet"]),
            lead_time_dias=r["lead_time_dias"],
            m2_por_caja=r["m2_por_caja"],
            costo_unitario=costo_unitario,
            cantidad_transferir=cantidad_transferir,
            detalle_transferencias=detalle_transferencias,
            cantidad_comprar_bruta=cantidad_comprar_bruta,
            cantidad_tras_moq=cantidad_tras_moq,
            cantidad_final=cantidad_final,
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
            "_faltante_bruto": faltante_bruto,
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
    rows = db.execute(
        f"""SELECT * FROM sugeridos_generados {where} ORDER BY actualizado DESC""",
        params,
    ).fetchall()
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
