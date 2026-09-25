"""Motor C1 · Balanceos — propuestas de transferencia dentro de corredor
(RF-014/015, RN-02) para la pantalla S10 Balanceos & Remates (T10).

Reusa las funciones puras de `engines/sugeridos.py` (fuente única de verdad
acordada con T9, ver waykee 290092) para cobertura/demanda; aquí se agrega
la parte que sugeridos.py NO expone como listado propio: un catálogo
independiente de "qué transferir antes de comprar" a nivel corredor, con
costo-beneficio (costo de traslado vs. costo evitado de comprar).
"""

from __future__ import annotations

import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
import sqlite3

from app.core import sucursal_compra
from app.core.db import get_db
from app.routers.engines.sugeridos import calc_cobertura_meses, calc_m2_a_cajas, _tabla_existe
from app.routers.semaforo import _fecha_pedido_simulada

router = APIRouter(prefix="/api/balanceos", tags=["engines:balanceos"])

MESES_DEMANDA = 3
DEFAULT_OBJETIVO_MESES = 2.0
COSTO_CAJA_TRASLADO_DEFAULT = 20.0

# --- Balanceos v2 (waykee 292187): motor de triggers + Grid pendientes -----
# Umbral de días desde el pedido de compra pendiente a partir del cual, aun
# con pedido en curso, sí se sugiere balanceo (Trigger 2). NO modela lead
# time real por proveedor -- Enrique lo descartó explícitamente ("muy
# indefinido"); es un umbral fijo, configurable en BD (balanceo_umbral_dias_pedido).
UMBRAL_DIAS_PEDIDO_DEFAULT = 30

# Cache en memoria del cómputo completo (todas las propuestas, sin filtro de
# corredor ni límite). El cálculo es CPU-bound (loops en Python sobre miles
# de renglones) y bajo concurrencia varias requests se serializan por el GIL
# -> se vio en vivo (T4, 23-ago) tomar 30+ segundos con solo 6 requests
# concurrentes. El dataset de la demo es estático ("congelado", ver
# redeploy.sh), así que cachear es seguro: se invalida solo si cambia la
# tabla editable de costos por corredor (ver put_config).
_cache_lock = threading.Lock()
_cache: dict = {"propuestas": None, "costo_por_corredor_snapshot": None, "generado": None, "duracion_ms": None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_tables(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS balanceo_costo_corredor (
            corredor TEXT PRIMARY KEY,
            costo_caja_traslado REAL NOT NULL
        )"""
    )
    # categoria='__default__' es el único valor usado por ahora (umbral
    # global). La columna categoria queda lista para "por categoría" (spec
    # lo deja abierto: "global o por categoría si aplica") sin rediseñar la
    # tabla cuando se necesite.
    db.execute(
        """CREATE TABLE IF NOT EXISTS balanceo_umbral_dias_pedido (
            categoria TEXT PRIMARY KEY,
            umbral_dias INTEGER NOT NULL
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS balanceo_descarte (
            material_id TEXT NOT NULL,
            plant TEXT NOT NULL,
            hasta_fecha TEXT NOT NULL,
            motivo TEXT,
            creado TEXT NOT NULL,
            PRIMARY KEY (material_id, plant)
        )"""
    )
    # Mismo patrón default/excepción que meses_objetivo_default/_excepcion
    # en sugeridos.py: excepción (material_id+plant) siempre gana sobre
    # default (material_id); si ninguna existe, el llamador usa demanda
    # como proxy (ver _prioridad_efectiva).
    db.execute(
        """CREATE TABLE IF NOT EXISTS balanceo_prioridad_default (
            material_id TEXT PRIMARY KEY,
            prioridad REAL NOT NULL
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS balanceo_prioridad_excepcion (
            material_id TEXT NOT NULL,
            plant TEXT NOT NULL,
            prioridad REAL NOT NULL,
            PRIMARY KEY (material_id, plant)
        )"""
    )
    # Renglones individuales creados por "Agregar" en el modal de Grid 1.
    # Grid 2 los agrupa por ruta (origen_plant, destino_plant) mientras
    # estado='pendiente'; "Generar Traslado" los pasa a 'posteado' con un
    # traslado_ref compartido; "Marcar entregado" los pasa a 'entregado'.
    db.execute(
        """CREATE TABLE IF NOT EXISTS balanceo_pendiente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id TEXT NOT NULL,
            origen_plant TEXT NOT NULL,
            destino_plant TEXT NOT NULL,
            cajas REAL NOT NULL,
            estado TEXT NOT NULL DEFAULT 'pendiente',
            traslado_ref TEXT,
            creado TEXT NOT NULL,
            posteado_en TEXT,
            entregado_en TEXT
        )"""
    )
    db.commit()


def _costo_traslado_por_corredor(db: sqlite3.Connection) -> dict:
    # NO llama _ensure_tables aquí (hot path de GET /propuestas): causaba
    # "database is locked" bajo concurrencia. La tabla se crea UNA vez en
    # el startup de la app vía init_tables() (ver main.py).
    rows = db.execute("SELECT corredor, costo_caja_traslado FROM balanceo_costo_corredor").fetchall()
    return {r["corredor"]: r["costo_caja_traslado"] for r in rows}


def init_tables(db: sqlite3.Connection) -> None:
    """Llamado UNA vez desde el startup de la app (main.py)."""
    _ensure_tables(db)


# ---------------------------------------------------------------------------
# Balanceos v2 (waykee 292187) -- funciones puras del motor de triggers.
# Sin I/O: reciben los números ya calculados (mismo criterio de
# disponible_neto/demanda/cobertura que _compute_all_propuestas arriba y que
# COBERTURA_CTE en routers/inventarios.py) y devuelven una decisión. Full
# unit-test coverage en tests/test_balanceos_triggers.py.
# ---------------------------------------------------------------------------


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


def _sin_plantas_fuera_de_universo(db: sqlite3.Connection, filas: list[dict]) -> list[dict]:
    """292252: sucursales SIN_OPERACION (sin OCs ni inventario) no participan
    en Balanceos. Esporádicas y no-compra sí: su abasto ES el traslado."""
    fuera = sucursal_compra.plantas_sin_operacion(db)
    return [f for f in filas if f["plant"] not in fuera] if fuera else filas


def _compute_all_propuestas(db: sqlite3.Connection, costo_por_corredor: dict) -> list[dict]:
    """Cómputo completo (todos los corredores, sin límite) — CPU-bound,
    pensado para llamarse una vez y cachearse (ver _cache)."""
    candidatos = db.execute(
        f"""SELECT i.material_id, i.plant, i.disponible, i.transito, i.comprometido,
                   m.descripcion, m.abc, m.m2_por_caja, m.precio_venta, m.costo,
                   s.corredor, s.nombre,
                   COALESCE(c.meses_objetivo, {DEFAULT_OBJETIVO_MESES}) AS meses_objetivo
            FROM inventarios i
            JOIN materiales m ON m.material_id = i.material_id
            JOIN sucursales s ON s.plant = i.plant
            LEFT JOIN coberturas_objetivo c ON c.material_id = i.material_id
            WHERE s.corredor IS NOT NULL"""
    ).fetchall()
    candidatos = _sin_plantas_fuera_de_universo(db, candidatos)

    if not candidatos:
        return []

    material_ids = sorted({r["material_id"] for r in candidatos})
    ph = ",".join("?" * len(material_ids))
    ventas_rows = db.execute(
        f"""SELECT material_id, plant, anio_mes, SUM(cantidad_m2) AS m2
            FROM ventas_mensuales
            WHERE material_id IN ({ph})
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

    def demanda_mensual(material_id: str, plant: str) -> float:
        puntos = serie.get((material_id, plant), [])[-MESES_DEMANDA:]
        if not puntos:
            return 0.0
        return sum(v for _, v in puntos) / len(puntos)

    # info por (material, plant): cobertura, déficit, excedente
    info_por_material: dict[str, list[dict]] = {}
    for r in candidatos:
        disp_neto = round((r["disponible"] or 0) + (r["transito"] or 0) - (r["comprometido"] or 0), 2)
        dem = demanda_mensual(r["material_id"], r["plant"])
        cobertura = calc_cobertura_meses(disp_neto, dem)
        objetivo = r["meses_objetivo"]

        deficit = 0.0
        excedente = 0.0
        if dem > 0 and cobertura is not None:
            if cobertura < objetivo:
                deficit = round((objetivo - cobertura) * dem, 2)
            elif cobertura > objetivo:
                excedente = round(disp_neto - objetivo * dem, 2)

        info_por_material.setdefault(r["material_id"], []).append(
            {"row": r, "disponible_neto": disp_neto, "demanda": dem, "cobertura": cobertura,
             "deficit": max(0.0, deficit), "excedente": max(0.0, excedente)}
        )

    propuestas = []
    for material_id, lineas in info_por_material.items():
        if len(lineas) < 2:
            continue
        deficitarias = [l for l in lineas if l["deficit"] > 0]
        excedentarias = sorted([l for l in lineas if l["excedente"] > 0], key=lambda l: l["excedente"], reverse=True)
        if not deficitarias or not excedentarias:
            continue

        usados: set[str] = set()
        for destino in sorted(deficitarias, key=lambda l: l["deficit"], reverse=True):
            origen = next(
                (e for e in excedentarias
                 if e["row"]["plant"] != destino["row"]["plant"] and e["row"]["plant"] not in usados),
                None,
            )
            if origen is None:
                continue
            transferir = min(destino["deficit"], origen["excedente"])
            if transferir <= 0:
                continue
            usados.add(origen["row"]["plant"])
            comprar = max(0.0, destino["deficit"] - transferir)
            row = destino["row"]
            costo_caja = costo_por_corredor.get(row["corredor"], COSTO_CAJA_TRASLADO_DEFAULT)
            cajas_transferir = round(transferir)
            costo_traslado = round(cajas_transferir * costo_caja)
            ahorro = round(cajas_transferir * (row["costo"] or 0) - costo_traslado)
            propuestas.append(
                {
                    "material_id": material_id,
                    "descripcion": row["descripcion"],
                    "abc": row["abc"],
                    "corredor": row["corredor"],
                    "origen": {"plant": origen["row"]["plant"], "nombre": origen["row"]["nombre"]},
                    "destino": {"plant": row["plant"], "nombre": row["nombre"]},
                    "deficit": destino["deficit"],
                    "excedenteCorredor": origen["excedente"],
                    "cajasTransferir": cajas_transferir,
                    "cajasComprar": round(comprar),
                    "cubreCompleto": comprar <= 0,
                    "costoTraslado": costo_traslado,
                    "ahorroEstimado": max(0, ahorro),
                    "precioVenta": row["precio_venta"],
                    "costoCajaTraslado": costo_caja,
                    "estado": "pendiente",
                    "layer": "C3",
                }
            )

    propuestas.sort(key=lambda p: p["ahorroEstimado"], reverse=True)
    for i, p in enumerate(propuestas, start=1):
        p["id"] = f"BAL-{i:03d}"
    return propuestas


def _get_cached_propuestas(db: sqlite3.Connection, force: bool = False) -> list[dict]:
    costo_por_corredor = _costo_traslado_por_corredor(db)
    snapshot = tuple(sorted(costo_por_corredor.items()))
    # El lock envuelve TODO el cómputo (no solo el check) — si se libera
    # antes de terminar de calcular, N requests concurrentes con cache fría
    # ven "propuestas is None" a la vez y las N recalculan en paralelo
    # (thundering herd), exactamente el problema de performance original
    # (visto en vivo: 8 concurrentes -> 25s+ cada una). Con el lock
    # cerrado durante el cálculo, la 2a..Na request simplemente esperan y
    # reciben el resultado ya cacheado de la 1a.
    with _cache_lock:
        if not force and _cache["propuestas"] is not None and _cache["costo_por_corredor_snapshot"] == snapshot:
            return _cache["propuestas"]
        t0 = datetime.now(timezone.utc)
        propuestas = _compute_all_propuestas(db, costo_por_corredor)
        t1 = datetime.now(timezone.utc)
        _cache["propuestas"] = propuestas
        _cache["costo_por_corredor_snapshot"] = snapshot
        _cache["generado"] = t1.isoformat()
        _cache["duracion_ms"] = int((t1 - t0).total_seconds() * 1000)
        return propuestas


def warm_cache(db: sqlite3.Connection) -> None:
    """Precalienta la cache en el startup de la app para que la primera
    request real de un usuario (o de QA) no pague el costo del cómputo."""
    _get_cached_propuestas(db)


def recalcular_propuestas(db: sqlite3.Connection) -> dict:
    """Recalcula (forzado) el cache de propuestas. Punto de enganche único
    (waykee 292197) para: (a) el job diario de snapshot (292194) al terminar
    de cargar datos nuevos, y (b) el botón "Recalcular ahora" de la UI.
    No hay scheduler propio aquí a propósito: el disparo lo da el job de
    snapshot, que es quien sabe cuándo cambiaron los datos."""
    sucursal_compra.recalcular(db)  # 292252: la clase de sucursal define el universo
    propuestas = _get_cached_propuestas(db, force=True)
    return {
        "total": len(propuestas),
        "zonas": len({p["corredor"] for p in propuestas}),
        "generado": _cache["generado"],
        "duracionMs": _cache["duracion_ms"],
    }


def agrupar_por_zona(propuestas: list[dict]) -> list[dict]:
    """Nivel 1 de la navegación (Zona): conteo y totales por corredor."""
    zonas: dict[str, dict] = {}
    for p in propuestas:
        z = zonas.setdefault(
            p["corredor"],
            {"corredor": p["corredor"], "propuestas": 0, "materiales": set(),
             "ahorroTotal": 0, "cajasTransferir": 0, "costoTraslado": 0},
        )
        z["propuestas"] += 1
        z["materiales"].add(p["material_id"])
        z["ahorroTotal"] += p["ahorroEstimado"]
        z["cajasTransferir"] += p["cajasTransferir"]
        z["costoTraslado"] += p["costoTraslado"]
    out = [{**z, "materiales": len(z["materiales"])} for z in zonas.values()]
    out.sort(key=lambda z: z["ahorroTotal"], reverse=True)
    return out


def agrupar_por_articulo(propuestas: list[dict], corredor: str) -> list[dict]:
    """Nivel 2 de la navegación (Artículos): propuestas de UN corredor
    agrupadas por material (un material puede tener varios destinos)."""
    arts: dict[str, dict] = {}
    for p in propuestas:
        if p["corredor"] != corredor:
            continue
        a = arts.setdefault(
            p["material_id"],
            {"material_id": p["material_id"], "descripcion": p["descripcion"], "abc": p["abc"],
             "propuestas": 0, "deficit": 0.0, "cajasTransferir": 0, "cajasComprar": 0,
             "ahorroEstimado": 0, "destinos": []},
        )
        a["propuestas"] += 1
        a["deficit"] = round(a["deficit"] + p["deficit"], 2)
        a["cajasTransferir"] += p["cajasTransferir"]
        a["cajasComprar"] += p["cajasComprar"]
        a["ahorroEstimado"] += p["ahorroEstimado"]
        a["destinos"].append({"origen": p["origen"], "destino": p["destino"], "cajas": p["cajasTransferir"]})
    out = list(arts.values())
    out.sort(key=lambda a: a["ahorroEstimado"], reverse=True)
    return out


@router.get("/zonas")
def zonas_balanceo(db: sqlite3.Connection = Depends(get_db)):
    todas = _get_cached_propuestas(db)
    return {"total": len(todas), "items": agrupar_por_zona(todas), "generado": _cache["generado"]}


@router.get("/articulos")
def articulos_balanceo(corredor: str = Query(...), db: sqlite3.Connection = Depends(get_db)):
    items = agrupar_por_articulo(_get_cached_propuestas(db), corredor)
    return {"corredor": corredor, "total": len(items), "items": items, "generado": _cache["generado"]}


@router.post("/recalcular")
def recalcular_balanceo(db: sqlite3.Connection = Depends(get_db)):
    return recalcular_propuestas(db)


@router.get("/propuestas")
def propuestas_balanceo(
    corredor: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    db: sqlite3.Connection = Depends(get_db),
):
    todas = _get_cached_propuestas(db)
    filtradas = [p for p in todas if not corredor or p["corredor"] == corredor]
    return {"total": len(filtradas), "items": filtradas[:limit], "generado": _cache["generado"] or _now()}


@router.get("/config")
def get_config(db: sqlite3.Connection = Depends(get_db)):
    return {"costoTrasladoPorCorredor": _costo_traslado_por_corredor(db), "costoDefault": COSTO_CAJA_TRASLADO_DEFAULT}


@router.put("/config")
def put_config(costos: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    _ensure_tables(db)
    db.execute("DELETE FROM balanceo_costo_corredor")
    db.executemany(
        "INSERT INTO balanceo_costo_corredor (corredor, costo_caja_traslado) VALUES (?,?)",
        list(costos.items()),
    )
    db.commit()
    return get_config(db)


# ===========================================================================
# Balanceos v2 (waykee 292187) -- Grid 1 (triggers por ubicación), modal de
# backorder de compra, sugerencia de cantidad, Grid 2 (pendientes/traslados),
# descartes (snooze) y config (umbral días / prioridad).
#
# NO toca el tab "Remates" ni remates.py (fuera de alcance de este ticket).
# Reemplaza, para el tab "Balanceos" del frontend, al listado simple
# /propuestas de arriba (que se deja intacto por compatibilidad, pero deja
# de ser consumido por Balanceos.jsx tras este ticket).
# ===========================================================================


def _umbral_dias_pedido(db: sqlite3.Connection) -> int:
    row = db.execute(
        "SELECT umbral_dias FROM balanceo_umbral_dias_pedido WHERE categoria = '__default__'"
    ).fetchone()
    return row["umbral_dias"] if row else UMBRAL_DIAS_PEDIDO_DEFAULT


def _descartes_activos(db: sqlite3.Connection, material_id: str, hoy: date) -> set:
    rows = db.execute(
        "SELECT plant FROM balanceo_descarte WHERE material_id = ? AND hasta_fecha >= ?",
        (material_id, hoy.isoformat()),
    ).fetchall()
    return {r["plant"] for r in rows}


def _prioridad_efectiva(db: sqlite3.Connection, material_id: str, plant: str, demanda_fallback: float):
    """Mismo patrón default/excepción que meses_objetivo en sugeridos.py.
    Sin override configurado, usa demanda mensual como proxy (ver
    permite_transferencia_por_prioridad)."""
    row = db.execute(
        "SELECT prioridad FROM balanceo_prioridad_excepcion WHERE material_id = ? AND plant = ?",
        (material_id, plant),
    ).fetchone()
    if row is not None:
        return row["prioridad"], "excepcion"
    row = db.execute(
        "SELECT prioridad FROM balanceo_prioridad_default WHERE material_id = ?",
        (material_id,),
    ).fetchone()
    if row is not None:
        return row["prioridad"], "default"
    return demanda_fallback, "demanda_proxy"


def _compute_grid1(db: sqlite3.Connection, material_id: str, corredor: Optional[str] = None, hoy: Optional[date] = None) -> list[dict]:
    """Grid 1 (waykee 292187): una fila por ubicación para el material
    seleccionado, con el trigger evaluado por fila. "Zona" == corredor (el
    ticket no define zona aparte; Balanceos ya trabaja "dentro de corredor"
    desde RN-02, así que se reusa esa agrupación -- supuesto documentado)."""
    hoy = hoy or datetime.now(timezone.utc).date()
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
    rows = _sin_plantas_fuera_de_universo(db, rows)
    if not rows:
        return []

    ventas_rows = db.execute(
        """SELECT plant, anio_mes, SUM(cantidad_m2) AS m2 FROM ventas_mensuales
           WHERE material_id = ? GROUP BY plant, anio_mes ORDER BY anio_mes""",
        (material_id,),
    ).fetchall()
    m2_por_caja = rows[0]["m2_por_caja"]
    serie: dict[str, list[tuple[str, float]]] = {}
    for r in ventas_rows:
        cajas = calc_m2_a_cajas(r["m2"] or 0.0, m2_por_caja)
        serie.setdefault(r["plant"], []).append((r["anio_mes"], cajas))

    def demanda_mensual(plant: str) -> float:
        puntos = serie.get(plant, [])[-MESES_DEMANDA:]
        if not puntos:
            return 0.0
        return sum(v for _, v in puntos) / len(puntos)

    umbral_dias = _umbral_dias_pedido(db)
    descartes = _descartes_activos(db, material_id, hoy)
    docs_compra = None
    if _tabla_existe(db, "pedidos_compra_detalle"):
        docs_compra = db.execute(
            """SELECT plant, po, cantidad_pendiente, fecha_po FROM pedidos_compra_detalle
               WHERE material_id = ?""",
            (material_id,),
        ).fetchall()

    lineas = []
    for r in rows:
        disp_neto = round((r["disponible"] or 0) + (r["transito"] or 0) - (r["comprometido"] or 0), 2)
        dem = demanda_mensual(r["plant"])
        cobertura = calc_cobertura_meses(disp_neto, dem)
        estado = estado_semaforo_balanceo(disp_neto, cobertura, r["meses_objetivo"])
        lineas.append({"row": r, "disponible_neto": disp_neto, "demanda": dem, "cobertura": cobertura, "estado": estado})

    resultado = []
    for linea in lineas:
        r = linea["row"]
        if corredor and r["corredor"] != corredor:
            continue
        alternativa = any(
            o["row"]["plant"] != r["plant"] and o["row"]["corredor"] == r["corredor"] and not es_rojo(o["estado"])
            for o in lineas
        )
        if docs_compra is not None:
            compra = resumir_pedidos_compra(docs_compra, r["plant"], hoy)
        else:
            # Dataset sin detalle por OC: agregado + fecha simulada (292187).
            cajas_ag = r["pedidos_abiertos"] or 0
            compra = {
                "cajas": cajas_ag,
                "numeroPedidos": 1 if cajas_ag > 0 else 0,
                "diasDesdePedido": calc_dias_desde_pedido(material_id, r["plant"], hoy) if cajas_ag > 0 else None,
            }
        pedidos_abiertos = compra["cajas"]
        dias_desde_pedido = compra["diasDesdePedido"]
        trigger = evaluar_trigger(
            linea["disponible_neto"], linea["cobertura"], r["meses_objetivo"],
            pedidos_abiertos, dias_desde_pedido, umbral_dias, alternativa,
        )
        descartado = r["plant"] in descartes
        if trigger and not descartado:
            orden = 0 if trigger["trigger"] == "sin_pedido" else 1
        else:
            orden = 2

        comprometido = r["comprometido"] or 0
        resultado.append({
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
                "diasDesdePedido": dias_desde_pedido,
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
        })

    resultado.sort(key=lambda x: (x["corredor"] or "", x["orden"], x["plant"]))
    return resultado


@router.get("/grid")
def grid1(
    material_id: str = Query(...),
    corredor: Optional[str] = Query(None),
    db: sqlite3.Connection = Depends(get_db),
):
    return {"items": _compute_grid1(db, material_id, corredor), "generado": _now()}


@router.get("/grid/backorder-detalle")
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


@router.get("/sugerencia-cantidad")
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


# --- Descartes (snooze) ----------------------------------------------------

@router.post("/descartes")
def crear_descarte(
    material_id: str = Body(...),
    plant: str = Body(...),
    dias: int = Body(..., gt=0),
    motivo: Optional[str] = Body(None),
    db: sqlite3.Connection = Depends(get_db),
):
    _ensure_tables(db)
    hasta = (datetime.now(timezone.utc).date() + timedelta(days=dias)).isoformat()
    db.execute(
        """INSERT INTO balanceo_descarte (material_id, plant, hasta_fecha, motivo, creado)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(material_id, plant) DO UPDATE SET
               hasta_fecha = excluded.hasta_fecha, motivo = excluded.motivo, creado = excluded.creado""",
        (material_id, plant, hasta, motivo, _now()),
    )
    db.commit()
    return {"ok": True, "hastaFecha": hasta}


# --- Grid 2: pendientes / generar traslado / marcar entregado --------------

def _postear_traslado_sap(origen_plant: str, destino_plant: str, cajas_total: float) -> str:
    """Stub de posteo a SAP como "Pedido de traslado" (waykee 292187).
    Interfaz separada A PROPÓSITO para conectar el conector SAP real después
    sin tocar el resto del endpoint -- por ahora NO hay integración real,
    solo genera una referencia única."""
    return f"SAP-STUB-{uuid.uuid4().hex[:10].upper()}"


@router.post("/pendientes")
def agregar_pendiente(
    material_id: str = Body(...),
    origen_plant: str = Body(...),
    destino_plant: str = Body(...),
    cajas: float = Body(..., gt=0),
    db: sqlite3.Connection = Depends(get_db),
):
    _ensure_tables(db)
    db.execute(
        """INSERT INTO balanceo_pendiente (material_id, origen_plant, destino_plant, cajas, estado, creado)
           VALUES (?, ?, ?, ?, 'pendiente', ?)""",
        (material_id, origen_plant, destino_plant, cajas, _now()),
    )
    db.commit()
    return {"ok": True}


@router.get("/pendientes")
def listar_pendientes(estado: str = Query("pendiente"), db: sqlite3.Connection = Depends(get_db)):
    """Grid 2: agrupado por ruta (origen->destino) mientras estado='pendiente'
    (suma de todos los "Agregar" hechos desde Grid 1); agrupado por
    traslado_ref para 'posteado'/'entregado' (un traslado ya generado)."""
    _ensure_tables(db)
    if estado == "pendiente":
        rows = db.execute(
            """SELECT p.origen_plant, p.destino_plant, so.nombre AS origen_nombre, sd.nombre AS destino_nombre,
                      SUM(p.cajas) AS cajas, COUNT(*) AS items
               FROM balanceo_pendiente p
               JOIN sucursales so ON so.plant = p.origen_plant
               JOIN sucursales sd ON sd.plant = p.destino_plant
               WHERE p.estado = 'pendiente'
               GROUP BY p.origen_plant, p.destino_plant
               ORDER BY cajas DESC"""
        ).fetchall()
        return {"items": rows}

    rows = db.execute(
        """SELECT p.traslado_ref, p.origen_plant, p.destino_plant, so.nombre AS origen_nombre, sd.nombre AS destino_nombre,
                  SUM(p.cajas) AS cajas, COUNT(*) AS items, MIN(p.posteado_en) AS posteado_en
           FROM balanceo_pendiente p
           JOIN sucursales so ON so.plant = p.origen_plant
           JOIN sucursales sd ON sd.plant = p.destino_plant
           WHERE p.estado = ?
           GROUP BY p.traslado_ref
           ORDER BY posteado_en DESC""",
        (estado,),
    ).fetchall()
    return {"items": rows}


@router.post("/pendientes/generar-traslado")
def generar_traslado(
    origen_plant: str = Body(...),
    destino_plant: str = Body(...),
    db: sqlite3.Connection = Depends(get_db),
):
    _ensure_tables(db)
    rows = db.execute(
        "SELECT id, cajas FROM balanceo_pendiente WHERE origen_plant = ? AND destino_plant = ? AND estado = 'pendiente'",
        (origen_plant, destino_plant),
    ).fetchall()
    if not rows:
        return {"error": "No hay pendientes en esa ruta"}
    cajas_total = sum(r["cajas"] for r in rows)
    ref = _postear_traslado_sap(origen_plant, destino_plant, cajas_total)
    ids = [r["id"] for r in rows]
    ph = ",".join("?" * len(ids))
    db.execute(
        f"UPDATE balanceo_pendiente SET estado = 'posteado', traslado_ref = ?, posteado_en = ? WHERE id IN ({ph})",
        [ref, _now(), *ids],
    )
    db.commit()
    return {"trasladoRef": ref, "cajasTotal": cajas_total, "items": len(ids)}


@router.post("/pendientes/marcar-entregado")
def marcar_entregado(traslado_ref: str = Body(..., embed=True), db: sqlite3.Connection = Depends(get_db)):
    """Transición Posteado -> Entregado. Por ahora manual (no definido en el
    ticket cómo se auto-detecta la entrega)."""
    _ensure_tables(db)
    db.execute(
        "UPDATE balanceo_pendiente SET estado = 'entregado', entregado_en = ? WHERE traslado_ref = ? AND estado = 'posteado'",
        (_now(), traslado_ref),
    )
    db.commit()
    return {"ok": True}


# --- Config: umbral días de pedido / prioridad ------------------------------

@router.get("/config/umbral-dias")
def get_umbral_dias(db: sqlite3.Connection = Depends(get_db)):
    _ensure_tables(db)
    return {"umbralDias": _umbral_dias_pedido(db), "default": UMBRAL_DIAS_PEDIDO_DEFAULT}


@router.put("/config/umbral-dias")
def put_umbral_dias(umbral_dias: int = Body(..., embed=True, gt=0), db: sqlite3.Connection = Depends(get_db)):
    _ensure_tables(db)
    db.execute(
        """INSERT INTO balanceo_umbral_dias_pedido (categoria, umbral_dias) VALUES ('__default__', ?)
           ON CONFLICT(categoria) DO UPDATE SET umbral_dias = excluded.umbral_dias""",
        (umbral_dias,),
    )
    db.commit()
    return get_umbral_dias(db)


@router.get("/config/prioridad")
def get_prioridad(db: sqlite3.Connection = Depends(get_db)):
    _ensure_tables(db)
    defaults = db.execute("SELECT material_id, prioridad FROM balanceo_prioridad_default").fetchall()
    excepciones = db.execute("SELECT material_id, plant, prioridad FROM balanceo_prioridad_excepcion").fetchall()
    return {"defaults": defaults, "excepciones": excepciones}


@router.put("/config/prioridad")
def put_prioridad(
    material_id: str = Body(...),
    prioridad: float = Body(...),
    plant: Optional[str] = Body(None),
    db: sqlite3.Connection = Depends(get_db),
):
    """Mismo patrón que PUT /objetivo en sugeridos.py: sin plant edita el
    DEFAULT (material_id); con plant crea/actualiza la EXCEPCIÓN
    (material_id+plant)."""
    _ensure_tables(db)
    if plant:
        db.execute(
            """INSERT INTO balanceo_prioridad_excepcion (material_id, plant, prioridad) VALUES (?, ?, ?)
               ON CONFLICT(material_id, plant) DO UPDATE SET prioridad = excluded.prioridad""",
            (material_id, plant, prioridad),
        )
    else:
        db.execute(
            """INSERT INTO balanceo_prioridad_default (material_id, prioridad) VALUES (?, ?)
               ON CONFLICT(material_id) DO UPDATE SET prioridad = excluded.prioridad""",
            (material_id, prioridad),
        )
    db.commit()
    return {"ok": True}


@router.delete("/config/prioridad/excepcion")
def delete_prioridad_excepcion(
    material_id: str = Query(...),
    plant: str = Query(...),
    db: sqlite3.Connection = Depends(get_db),
):
    db.execute(
        "DELETE FROM balanceo_prioridad_excepcion WHERE material_id = ? AND plant = ?", (material_id, plant)
    )
    db.commit()
    return {"ok": True}
