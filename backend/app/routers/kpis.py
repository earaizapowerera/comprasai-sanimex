from typing import Optional

from fastapi import APIRouter, Depends, Query
import sqlite3

from app.core.db import get_db

router = APIRouter(prefix="/api/kpis", tags=["kpis"])


@router.get("")
def get_kpis(
    organizacion: Optional[str] = None,
    canal: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db),
):
    """
    KPIs agregados de inventario/abasto:
      - fill_rate_pct: % de pares material-sucursal SIN quiebre (disponible_neto > 0)
      - cobertura_promedio_meses: disponible_neto / demanda promedio mensual (últimos 3 meses)
      - dias_inventario_promedio: cobertura_promedio_meses * 30
      - valor_inventario_total: sum(disponible * costo)
      - compras_urgentes: pares donde cobertura_actual < meses_objetivo del material
    """
    where = []
    params: list = []
    if organizacion:
        where.append("s.organizacion = ?")
        params.append(organizacion)
    if canal:
        where.append("s.canal = ?")
        params.append(canal)
    where_sql = f"AND {' AND '.join(where)}" if where else ""

    # Demanda promedio mensual (últimos 3 meses con datos) por par material-plant
    demanda_sql = f"""
        WITH ultimos_meses AS (
            SELECT DISTINCT anio_mes FROM ventas_mensuales ORDER BY anio_mes DESC LIMIT 3
        ),
        demanda AS (
            SELECT v.material_id, v.plant, AVG(v.cantidad_m2) AS demanda_prom
            FROM ventas_mensuales v
            WHERE v.anio_mes IN (SELECT anio_mes FROM ultimos_meses)
            GROUP BY v.material_id, v.plant
        )
        SELECT
            i.material_id, i.plant,
            (i.disponible + i.transito - i.comprometido) AS disponible_neto,
            i.disponible, m.costo,
            COALESCE(d.demanda_prom, 0) AS demanda_prom,
            c.meses_objetivo
        FROM inventarios i
        JOIN materiales m ON m.material_id = i.material_id
        JOIN sucursales s ON s.plant = i.plant
        LEFT JOIN demanda d ON d.material_id = i.material_id AND d.plant = i.plant
        LEFT JOIN coberturas_objetivo c ON c.material_id = i.material_id
        WHERE 1=1 {where_sql}
    """
    rows = db.execute(demanda_sql, params).fetchall()

    n_pares = len(rows)
    if n_pares == 0:
        return {
            "fill_rate_pct": 0, "cobertura_promedio_meses": 0, "dias_inventario_promedio": 0,
            "valor_inventario_total": 0, "compras_urgentes": 0, "pares_material_plant": 0,
            "pares_en_quiebre": 0,
        }

    en_quiebre = sum(1 for r in rows if r["disponible_neto"] <= 0)
    fill_rate = round(100 * (n_pares - en_quiebre) / n_pares, 2)

    coberturas = []
    urgentes = 0
    for r in rows:
        demanda = r["demanda_prom"]
        cobertura = (r["disponible_neto"] / demanda) if demanda and demanda > 0 else 0.0
        coberturas.append(max(cobertura, 0.0))
        objetivo = r["meses_objetivo"] if r["meses_objetivo"] is not None else 2.0
        if demanda and demanda > 0 and cobertura < objetivo:
            urgentes += 1

    cobertura_prom = round(sum(coberturas) / len(coberturas), 2) if coberturas else 0.0
    valor_inventario = round(sum((r["disponible"] or 0) * (r["costo"] or 0) for r in rows), 2)

    return {
        "fill_rate_pct": fill_rate,
        "cobertura_promedio_meses": cobertura_prom,
        "dias_inventario_promedio": round(cobertura_prom * 30, 1),
        "valor_inventario_total": valor_inventario,
        "compras_urgentes": urgentes,
        "pares_material_plant": n_pares,
        "pares_en_quiebre": en_quiebre,
    }


@router.get("/compras-urgentes")
def list_compras_urgentes(
    limit: int = Query(50, ge=1, le=500),
    db: sqlite3.Connection = Depends(get_db),
):
    """Detalle de los pares material-sucursal que requieren compra urgente
    (cobertura actual por debajo de la cobertura objetivo del material)."""
    sql = """
        WITH ultimos_meses AS (
            SELECT DISTINCT anio_mes FROM ventas_mensuales ORDER BY anio_mes DESC LIMIT 3
        ),
        demanda AS (
            SELECT v.material_id, v.plant, AVG(v.cantidad_m2) AS demanda_prom
            FROM ventas_mensuales v
            WHERE v.anio_mes IN (SELECT anio_mes FROM ultimos_meses)
            GROUP BY v.material_id, v.plant
        )
        SELECT
            i.material_id, m.descripcion, i.plant, s.nombre AS nombre_sucursal,
            ROUND(i.disponible + i.transito - i.comprometido, 2) AS disponible_neto,
            ROUND(COALESCE(d.demanda_prom, 0), 2) AS demanda_prom,
            c.meses_objetivo,
            ROUND(
                CASE WHEN d.demanda_prom > 0
                     THEN (i.disponible + i.transito - i.comprometido) / d.demanda_prom
                     ELSE 0 END, 2
            ) AS cobertura_actual_meses,
            p.proveedor, p.lead_time_dias, p.moq_cajas
        FROM inventarios i
        JOIN materiales m ON m.material_id = i.material_id
        JOIN sucursales s ON s.plant = i.plant
        LEFT JOIN demanda d ON d.material_id = i.material_id AND d.plant = i.plant
        LEFT JOIN coberturas_objetivo c ON c.material_id = i.material_id
        LEFT JOIN proveedores p ON p.material_id = i.material_id
        WHERE d.demanda_prom > 0
          AND ((i.disponible + i.transito - i.comprometido) / d.demanda_prom) < COALESCE(c.meses_objetivo, 2.0)
        ORDER BY cobertura_actual_meses ASC
        LIMIT ?
    """
    rows = db.execute(sql, [limit]).fetchall()
    return {"items": rows, "count": len(rows)}
