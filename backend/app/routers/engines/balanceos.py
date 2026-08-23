"""Motor C1 · Balanceos — propuestas de transferencia dentro de corredor
(RF-014/015, RN-02) para la pantalla S10 Balanceos & Remates (T10).

Reusa las funciones puras de `engines/sugeridos.py` (fuente única de verdad
acordada con T9, ver waykee 290092) para cobertura/demanda; aquí se agrega
la parte que sugeridos.py NO expone como listado propio: un catálogo
independiente de "qué transferir antes de comprar" a nivel corredor, con
costo-beneficio (costo de traslado vs. costo evitado de comprar).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
import sqlite3

from app.core.db import get_db
from app.routers.engines.sugeridos import calc_cobertura_meses, calc_m2_a_cajas

router = APIRouter(prefix="/api/balanceos", tags=["engines:balanceos"])

MESES_DEMANDA = 3
DEFAULT_OBJETIVO_MESES = 2.0
COSTO_CAJA_TRASLADO_DEFAULT = 20.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_tables(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS balanceo_costo_corredor (
            corredor TEXT PRIMARY KEY,
            costo_caja_traslado REAL NOT NULL
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


@router.get("/propuestas")
def propuestas_balanceo(
    corredor: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    db: sqlite3.Connection = Depends(get_db),
):
    costo_por_corredor = _costo_traslado_por_corredor(db)

    where = ["s.corredor IS NOT NULL"]
    params: list = []
    if corredor:
        where.append("s.corredor = ?")
        params.append(corredor)
    where_sql = " AND ".join(where)

    candidatos = db.execute(
        f"""SELECT i.material_id, i.plant, i.disponible, i.transito, i.comprometido,
                   m.descripcion, m.abc, m.m2_por_caja, m.precio_venta, m.costo,
                   s.corredor, s.nombre,
                   COALESCE(c.meses_objetivo, {DEFAULT_OBJETIVO_MESES}) AS meses_objetivo
            FROM inventarios i
            JOIN materiales m ON m.material_id = i.material_id
            JOIN sucursales s ON s.plant = i.plant
            LEFT JOIN coberturas_objetivo c ON c.material_id = i.material_id
            WHERE {where_sql}""",
        params,
    ).fetchall()

    if not candidatos:
        return {"total": 0, "items": [], "generado": _now()}

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
    total = len(propuestas)
    propuestas = propuestas[:limit]
    for i, p in enumerate(propuestas, start=1):
        p["id"] = f"BAL-{i:03d}"

    return {"total": total, "items": propuestas, "generado": _now()}


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
