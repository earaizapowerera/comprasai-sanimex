"""Propuestas de transferencia dentro de corredor (RF-014/015, RN-02) y su
cache en memoria, más la agrupación para la navegación Zona -> Artículos."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone

from app.core import sucursal_compra
from app.routers.engines.sugeridos import calc_cobertura_meses, calc_m2_a_cajas

from .constantes import COSTO_CAJA_TRASLADO_DEFAULT, DEFAULT_OBJETIVO_MESES, MESES_DEMANDA
from .persistencia import _costo_traslado_por_corredor, _sin_plantas_fuera_de_universo

# Cache en memoria del cómputo completo (todas las propuestas, sin filtro de
# corredor ni límite). El cálculo es CPU-bound (loops en Python sobre miles
# de renglones) y bajo concurrencia varias requests se serializan por el GIL
# -> se vio en vivo (T4, 23-ago) tomar 30+ segundos con solo 6 requests
# concurrentes. El dataset de la demo es estático ("congelado", ver
# redeploy.sh), así que cachear es seguro: se invalida solo si cambia la
# tabla editable de costos por corredor (ver put_config).
_cache_lock = threading.Lock()
_cache: dict = {"propuestas": None, "costo_por_corredor_snapshot": None, "generado": None, "duracion_ms": None}


def _demanda_promedio(serie: dict, key) -> float:
    """Promedio de los últimos MESES_DEMANDA puntos (cajas) de la serie."""
    puntos = serie.get(key, [])[-MESES_DEMANDA:]
    if not puntos:
        return 0.0
    return sum(v for _, v in puntos) / len(puntos)


def _cargar_candidatos(db: sqlite3.Connection) -> list[dict]:
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
    return _sin_plantas_fuera_de_universo(db, candidatos)


def _serie_cajas(db: sqlite3.Connection, candidatos: list[dict]) -> dict:
    """Serie mensual en cajas por (material_id, plant)."""
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
    return serie


def _info_por_material(candidatos: list[dict], serie: dict) -> dict[str, list[dict]]:
    """info por (material, plant): cobertura, déficit, excedente."""
    info_por_material: dict[str, list[dict]] = {}
    for r in candidatos:
        disp_neto = round((r["disponible"] or 0) + (r["transito"] or 0) - (r["comprometido"] or 0), 2)
        dem = _demanda_promedio(serie, (r["material_id"], r["plant"]))
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
    return info_por_material


def _propuesta(material_id: str, destino: dict, origen: dict, transferir: float, costo_por_corredor: dict) -> dict:
    comprar = max(0.0, destino["deficit"] - transferir)
    row = destino["row"]
    costo_caja = costo_por_corredor.get(row["corredor"], COSTO_CAJA_TRASLADO_DEFAULT)
    cajas_transferir = round(transferir)
    costo_traslado = round(cajas_transferir * costo_caja)
    ahorro = round(cajas_transferir * (row["costo"] or 0) - costo_traslado)
    return {
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


def _propuestas_material(material_id: str, lineas: list[dict], costo_por_corredor: dict) -> list[dict]:
    """Empareja destinos deficitarios (mayor déficit primero) con el origen
    de mayor excedente aún no usado para ese material."""
    if len(lineas) < 2:
        return []
    deficitarias = [l for l in lineas if l["deficit"] > 0]
    excedentarias = sorted([l for l in lineas if l["excedente"] > 0], key=lambda l: l["excedente"], reverse=True)
    if not deficitarias or not excedentarias:
        return []

    out = []
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
        out.append(_propuesta(material_id, destino, origen, transferir, costo_por_corredor))
    return out


def _compute_all_propuestas(db: sqlite3.Connection, costo_por_corredor: dict) -> list[dict]:
    """Cómputo completo (todos los corredores, sin límite) — CPU-bound,
    pensado para llamarse una vez y cachearse (ver _cache)."""
    candidatos = _cargar_candidatos(db)
    if not candidatos:
        return []

    serie = _serie_cajas(db, candidatos)
    propuestas = []
    for material_id, lineas in _info_por_material(candidatos, serie).items():
        propuestas.extend(_propuestas_material(material_id, lineas, costo_por_corredor))

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
