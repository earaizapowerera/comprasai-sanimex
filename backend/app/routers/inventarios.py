from typing import Optional

from fastapi import APIRouter, Depends, Query
import sqlite3

from app.core.constants import EPS_DEMANDA
from app.core.db import get_db

router = APIRouter(prefix="/api/inventarios", tags=["inventarios"])

# disponible_neto = existencia física + tránsito - comprometido
# (los pedidos_abiertos NO se suman: son compras aún no llegadas a tránsito
#  y se exponen aparte para que los motores de compra los consideren).
SELECT_BASE = """
    SELECT i.material_id, i.plant, m.descripcion, s.nombre AS nombre_sucursal,
           i.disponible, i.transito, i.comprometido, i.pedidos_abiertos, i.cajas_remanentes,
           ROUND(i.disponible + i.transito - i.comprometido, 2) AS disponible_neto,
           c.meses_objetivo
    FROM inventarios i
    JOIN materiales m ON m.material_id = i.material_id
    JOIN sucursales s ON s.plant = i.plant
    LEFT JOIN coberturas_objetivo c ON c.material_id = i.material_id
"""


@router.get("")
def list_inventarios(
    material_id: Optional[str] = None,
    plant: Optional[str] = None,
    organizacion: Optional[str] = None,
    canal: Optional[str] = None,
    solo_quiebre: bool = Query(False, description="Solo pares con disponible_neto <= 0"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: sqlite3.Connection = Depends(get_db),
):
    where = []
    params: list = []
    if material_id:
        where.append("i.material_id = ?")
        params.append(material_id)
    if plant:
        where.append("i.plant = ?")
        params.append(plant)
    if organizacion:
        where.append("s.organizacion = ?")
        params.append(organizacion)
    if canal:
        where.append("s.canal = ?")
        params.append(canal)
    if solo_quiebre:
        where.append("(i.disponible + i.transito - i.comprometido) <= 0")

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    count_sql = f"""SELECT COUNT(*) AS n FROM inventarios i
                     JOIN sucursales s ON s.plant = i.plant
                     {where_sql}"""
    total = db.execute(count_sql, params).fetchone()["n"]

    rows = db.execute(
        f"{SELECT_BASE} {where_sql} ORDER BY i.material_id, i.plant LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()

    return {"total": total, "page": page, "page_size": page_size, "items": rows}


# ---------------------------------------------------------------------------
# COBERTURA — vista enriquecida para T8 (pantalla Inventarios & Cobertura).
# Reutiliza el mismo cálculo de demanda/cobertura que kpis.py (demanda
# promedio de los últimos 3 meses con datos), pero expuesto por PAR
# material-sucursal con filtros/orden/paginación pensados para un explorador
# tipo tabla, y clasifica cada par en un estado de semáforo:
#   quiebre  -> disponible_neto <= 0, o cobertura < 50% del objetivo
#   riesgo   -> cobertura por debajo del objetivo (pero no en quiebre)
#   ok       -> cobertura dentro de rango objetivo
#   exceso   -> cobertura > 2.5x el objetivo (candidato a balanceo/remate)
#   sin_dato -> sin ventas en los últimos 3 meses (no se puede calcular cobertura)
# ---------------------------------------------------------------------------

COBERTURA_CTE = f"""
    WITH ultimos_meses AS (
        SELECT DISTINCT anio_mes FROM ventas_mensuales ORDER BY anio_mes DESC LIMIT 3
    ),
    demanda AS (
        SELECT v.material_id, v.plant, AVG(v.cantidad_m2) AS demanda_prom
        FROM ventas_mensuales v
        WHERE v.anio_mes IN (SELECT anio_mes FROM ultimos_meses)
        GROUP BY v.material_id, v.plant
    ),
    ultima_venta AS (
        SELECT material_id, plant, MAX(anio_mes) AS ultima_venta
        FROM ventas_mensuales
        GROUP BY material_id, plant
    ),
    base AS (
        SELECT
            i.material_id, m.descripcion, m.familia, m.abc,
            i.plant, s.nombre AS nombre_sucursal, s.organizacion, s.canal, s.corredor,
            i.disponible, i.transito, i.comprometido,
            ROUND(i.disponible + i.transito - i.comprometido, 2) AS disponible_neto,
            ROUND(COALESCE(d.demanda_prom, 0), 2) AS demanda_prom_mensual,
            COALESCE(c.meses_objetivo, 2.0) AS meses_objetivo,
            CASE WHEN d.demanda_prom >= {EPS_DEMANDA}
                 THEN ROUND((i.disponible + i.transito - i.comprometido) / d.demanda_prom, 2)
                 ELSE NULL END AS cobertura_meses,
            uv.ultima_venta
        FROM inventarios i
        JOIN materiales m ON m.material_id = i.material_id
        JOIN sucursales s ON s.plant = i.plant
        LEFT JOIN demanda d ON d.material_id = i.material_id AND d.plant = i.plant
        LEFT JOIN coberturas_objetivo c ON c.material_id = i.material_id
        LEFT JOIN ultima_venta uv ON uv.material_id = i.material_id AND uv.plant = i.plant
    ),
    scored AS (
        SELECT *,
            CASE
                WHEN disponible_neto <= 0 THEN 'quiebre'
                WHEN cobertura_meses IS NULL THEN 'sin_dato'
                WHEN cobertura_meses < meses_objetivo * 0.5 THEN 'quiebre'
                WHEN cobertura_meses < meses_objetivo THEN 'riesgo'
                WHEN cobertura_meses > meses_objetivo * 2.5 THEN 'exceso'
                ELSE 'ok'
            END AS estado
        FROM base
    )
"""

ORDER_COLUMNS = {
    "cobertura_asc": "(cobertura_meses IS NULL) ASC, cobertura_meses ASC",
    "cobertura_desc": "(cobertura_meses IS NULL) ASC, cobertura_meses DESC",
    "disponible_neto_asc": "disponible_neto ASC",
    "disponible_neto_desc": "disponible_neto DESC",
    "material_id": "material_id ASC, plant ASC",
}


def _cobertura_filters(
    organizacion: Optional[str],
    canal: Optional[str],
    corredor: Optional[str],
    familia: Optional[str],
    abc: Optional[str],
    search: Optional[str],
    estado: Optional[str],
    plant: Optional[str] = None,
) -> tuple[list[str], list]:
    where: list[str] = []
    params: list = []
    if organizacion:
        where.append("organizacion = ?")
        params.append(organizacion)
    if canal:
        where.append("canal = ?")
        params.append(canal)
    if corredor:
        where.append("corredor = ?")
        params.append(corredor)
    if plant:
        where.append("plant = ?")
        params.append(plant)
    if familia:
        where.append("familia = ?")
        params.append(familia)
    if abc:
        where.append("abc = ?")
        params.append(abc)
    if search:
        where.append("(material_id LIKE ? OR descripcion LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like])
    if estado:
        where.append("estado = ?")
        params.append(estado)
    return where, params


@router.get("/cobertura")
def list_cobertura(
    organizacion: Optional[str] = None,
    canal: Optional[str] = None,
    corredor: Optional[str] = None,
    plant: Optional[str] = None,
    familia: Optional[str] = None,
    abc: Optional[str] = Query(None, pattern="^[ABC]$"),
    estado: Optional[str] = Query(None, pattern="^(quiebre|riesgo|ok|exceso|sin_dato)$"),
    search: Optional[str] = None,
    sort: str = Query("cobertura_asc", description=f"Uno de: {list(ORDER_COLUMNS)}"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: sqlite3.Connection = Depends(get_db),
):
    order_sql = ORDER_COLUMNS.get(sort, ORDER_COLUMNS["cobertura_asc"])
    where, params = _cobertura_filters(organizacion, canal, corredor, familia, abc, search, estado, plant)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    total = db.execute(
        f"{COBERTURA_CTE} SELECT COUNT(*) AS n FROM scored {where_sql}", params
    ).fetchone()["n"]

    rows = db.execute(
        f"{COBERTURA_CTE} SELECT * FROM scored {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()

    return {"total": total, "page": page, "page_size": page_size, "items": rows}


@router.get("/cobertura/resumen")
def cobertura_resumen(
    organizacion: Optional[str] = None,
    canal: Optional[str] = None,
    corredor: Optional[str] = None,
    plant: Optional[str] = None,
    familia: Optional[str] = None,
    abc: Optional[str] = Query(None, pattern="^[ABC]$"),
    search: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db),
):
    """3 KPIs de resumen (mismo universo filtrado que /cobertura, sin filtrar por estado)."""
    where, params = _cobertura_filters(organizacion, canal, corredor, familia, abc, search, None, plant)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    row = db.execute(
        f"""{COBERTURA_CTE}
            SELECT
                COUNT(*) AS total_pares,
                SUM(CASE WHEN estado = 'quiebre' THEN 1 ELSE 0 END) AS en_quiebre,
                SUM(CASE WHEN estado = 'exceso' THEN 1 ELSE 0 END) AS en_exceso,
                ROUND(AVG(cobertura_meses), 2) AS cobertura_media_meses
            FROM scored {where_sql}""",
        params,
    ).fetchone()
    return row


@router.get("/cobertura/priorizadas")
def cobertura_priorizadas(
    limit: int = Query(15, ge=1, le=100),
    organizacion: Optional[str] = None,
    canal: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db),
):
    """Dos listas priorizadas: mayor riesgo de quiebre primero, mayor sobreinventario primero."""
    where, params = _cobertura_filters(organizacion, canal, None, None, None, None, None)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    quiebre = db.execute(
        f"""{COBERTURA_CTE} SELECT * FROM scored {where_sql}
            {"AND" if where else "WHERE"} estado IN ('quiebre', 'riesgo')
            ORDER BY (cobertura_meses IS NULL) ASC, cobertura_meses ASC LIMIT ?""",
        [*params, limit],
    ).fetchall()

    exceso = db.execute(
        f"""{COBERTURA_CTE} SELECT * FROM scored {where_sql}
            {"AND" if where else "WHERE"} estado = 'exceso'
            ORDER BY cobertura_meses DESC LIMIT ?""",
        [*params, limit],
    ).fetchall()

    return {"riesgo_quiebre": quiebre, "sobreinventario": exceso}
