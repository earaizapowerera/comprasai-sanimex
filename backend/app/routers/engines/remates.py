"""Motor C1 · Remates (minuta GAM) — pantalla S10 Balanceos & Remates (T10).

Puerto Python 1:1 del motor de referencia en JS que dejó T10
(frontend/src/lib/remateEngine.js, ver ese archivo para el razonamiento de
negocio completo). Fuente de verdad: minuta GAM confirmada por el PM
(waykee 290066, hilo T14-QA, msg 61809).

Detecta remanentes reales desde `inventarios.cajas_remanentes` (candidato a
remate) cruzado con "días sin venta" calculado a partir de la última venta
registrada en `ventas_mensuales` — no es un mock, corre contra el dataset
completo (18,206 inventarios de T1).

Tablas de escalas/rutas/plazas de excepción viven en BD (aditivas al
esquema de T3, CREATE TABLE IF NOT EXISTS) y son editables vía
GET/PUT /api/remates/config/* sin tocar código.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Query
import sqlite3

from app.core.db import get_db
from fastapi import Depends

router = APIRouter(prefix="/api/remates", tags=["engines:remates"])

# ---------------------------------------------------------------------------
# Defaults de negocio (minuta GAM) — se siembran en BD la primera vez y desde
# ahí son editables; estos valores solo aplican si las tablas están vacías.
# ---------------------------------------------------------------------------
ESCALAS_DEFAULT = [
    (1, 3, 70.0, 0),    # 1-3 cajas -> $70, liquida en sitio (traslada=0)
    (4, 10, 80.0, 0),   # 4-10 cajas -> $80, liquida en sitio
    (11, 14, 120.0, 1), # 11-14 cajas -> $120, se traslada
    (15, 30, 140.0, 1), # 15-30 cajas -> $140, se traslada
]
PRECIO_ECONOMICO_30MAS = 120.0   # Económico + 30 cajas o más -> remate directo
PRECIO_EXTENSION_30MAS = 140.0   # No-económico + >30 cajas -> supuesto, validar

RUTAS_GAM_DEFAULT = {
    "Corredor Noreste": ("CEDIS Monterrey Centro", "Sanimex Saltillo Centro"),
    "Corredor Bajío": ("CEDIS León Centro", "Sanimex Celaya Centro"),
    "Corredor Centro": ("CEDIS CDMX Iztapalapa", "Sanimex Pachuca Centro"),
    "Corredor Occidente": ("CEDIS Guadalajara Zapopan", "Sanimex Colima Centro"),
    "default": ("CEDIS Regional", "Sucursal de Remate Regional"),
}
PLAZAS_EXCEPCION_DEFAULT = ["Juchitán", "Tlapa", "San Andrés", "Cd. Valles", "Putla", "Toluca"]

DIAS_SIN_VENTA_DEFAULT_UMBRAL = 60
DIAS_SIN_VENTA_NUNCA = 730  # sin registro de venta en toda la ventana de 24 meses


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Tablas editables (aditivas, CREATE TABLE IF NOT EXISTS) — RN: "tablas de
# ruteo/escalas en BD, editables" del mandato de T4.
# ---------------------------------------------------------------------------

def _ensure_tables(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS remate_escalas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cajas_min INTEGER NOT NULL,
            cajas_max INTEGER NOT NULL,
            precio_caja REAL NOT NULL,
            traslada INTEGER NOT NULL DEFAULT 0
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS remate_rutas_gam (
            corredor TEXT PRIMARY KEY,
            cedis TEXT NOT NULL,
            sucursal_remate TEXT NOT NULL
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS remate_plazas_excepcion (
            nombre TEXT PRIMARY KEY
        )"""
    )
    if db.execute("SELECT COUNT(*) AS n FROM remate_escalas").fetchone()["n"] == 0:
        db.executemany(
            "INSERT INTO remate_escalas (cajas_min, cajas_max, precio_caja, traslada) VALUES (?,?,?,?)",
            ESCALAS_DEFAULT,
        )
    if db.execute("SELECT COUNT(*) AS n FROM remate_rutas_gam").fetchone()["n"] == 0:
        db.executemany(
            "INSERT INTO remate_rutas_gam (corredor, cedis, sucursal_remate) VALUES (?,?,?)",
            [(k, v[0], v[1]) for k, v in RUTAS_GAM_DEFAULT.items()],
        )
    if db.execute("SELECT COUNT(*) AS n FROM remate_plazas_excepcion").fetchone()["n"] == 0:
        db.executemany(
            "INSERT INTO remate_plazas_excepcion (nombre) VALUES (?)",
            [(p,) for p in PLAZAS_EXCEPCION_DEFAULT],
        )
    db.commit()


def _load_config(db: sqlite3.Connection):
    _ensure_tables(db)
    escalas = [
        (r["cajas_min"], r["cajas_max"], r["precio_caja"], bool(r["traslada"]))
        for r in db.execute("SELECT * FROM remate_escalas ORDER BY cajas_min").fetchall()
    ]
    rutas = {
        r["corredor"]: {"cedis": r["cedis"], "remate": r["sucursal_remate"]}
        for r in db.execute("SELECT * FROM remate_rutas_gam").fetchall()
    }
    plazas = [r["nombre"] for r in db.execute("SELECT nombre FROM remate_plazas_excepcion").fetchall()]
    return escalas, rutas, plazas


# ---------------------------------------------------------------------------
# Funciones puras (C1) — mismo contrato que remateEngine.js.
# ---------------------------------------------------------------------------

def precio_remate(cajas: float, economico: bool, escalas: list) -> tuple[float, bool, bool, Optional[str]]:
    if economico and cajas >= 30:
        return PRECIO_ECONOMICO_30MAS, False, True, "Económico con 30+ cajas → remate directo (regla explícita de la minuta)."
    if not economico and cajas > 30:
        return (
            PRECIO_EXTENSION_30MAS,
            True,
            True,
            "La minuta no define escala > 30 cajas para producto no económico; se extiende el último rango (15-30 → $140). Validar con Sanimex.",
        )
    for cmin, cmax, precio, _traslada in escalas:
        if cmin <= cajas <= cmax:
            return precio, False, False, None
    # cajas fuera de cualquier escala conocida (p.ej. 0 o negativo defensivo)
    cmin0, _cmax0, precio0, _t0 = escalas[0]
    return precio0, False, False, None


def _traslada_por_escala(cajas: float, economico: bool, escalas: list) -> bool:
    if economico and cajas >= 30:
        return True
    if not economico and cajas > 30:
        return True
    for cmin, cmax, _precio, traslada in escalas:
        if cmin <= cajas <= cmax:
            return traslada
    return False


def es_plaza_excepcion(nombre: Optional[str], plazas: list) -> bool:
    if not nombre:
        return False
    return any(p in nombre for p in plazas)


def compute_ruteo_remate(cajas: float, economico: bool, organizacion: str, plant: str, nombre: str,
                          corredor: Optional[str], escalas: list, rutas_gam: dict, plazas: list) -> dict:
    excepcion_plaza = es_plaza_excepcion(nombre, plazas)
    en_escala_alta = _traslada_por_escala(cajas, economico, escalas)
    trasladar = (not excepcion_plaza) and en_escala_alta and organizacion != "GAMN"

    if not trasladar:
        motivo = (
            f"Plaza de excepción: {nombre} remata siempre en sitio (sin traslado)."
            if excepcion_plaza
            else "Organización GAMN: remata en la misma plaza." if organizacion == "GAMN" and en_escala_alta
            else "Escala 1-3 / 4-10 cajas: se liquida en sitio (sin traslado)."
        )
        return {
            "ruta": [{"tipo": "origen", "nombre": nombre, "plant": plant}],
            "enSitio": True,
            "excepcionPlaza": excepcion_plaza,
            "motivoEnSitio": motivo,
        }

    ruta = [{"tipo": "origen", "nombre": nombre, "plant": plant}]
    if organizacion == "GAM":
        r = rutas_gam.get(corredor) or rutas_gam.get("default")
        ruta.append({"tipo": "cedis", "nombre": r["cedis"]})
        destino_final = r["remate"]
    elif organizacion == "GSA":
        destino_final = "R1"
    elif organizacion == "SA":
        destino_final = "Tienda 4"
    else:
        destino_final = nombre  # defensivo, no debería alcanzarse
    ruta.append({"tipo": "remate", "nombre": destino_final})
    return {"ruta": ruta, "enSitio": False, "excepcionPlaza": False, "motivoEnSitio": None}


# ---------------------------------------------------------------------------
# Endpoint principal
# ---------------------------------------------------------------------------

@router.get("/detectar")
def detectar_remates(
    organizacion: Optional[str] = Query(None, description="GAM|GSA|SA|GAMN"),
    dias_min: int = Query(DIAS_SIN_VENTA_DEFAULT_UMBRAL, ge=0, le=730),
    limit: int = Query(40, ge=1, le=200),
    db: sqlite3.Connection = Depends(get_db),
):
    escalas, rutas_gam, plazas = _load_config(db)

    where = ["i.cajas_remanentes > 0"]
    params: list = []
    if organizacion:
        where.append("s.organizacion = ?")
        params.append(organizacion)
    where_sql = " AND ".join(where)

    candidatos = db.execute(
        f"""SELECT i.material_id, i.plant, i.cajas_remanentes,
                   m.descripcion, m.abc, m.economico, m.precio_venta,
                   s.nombre, s.organizacion, s.corredor
            FROM inventarios i
            JOIN materiales m ON m.material_id = i.material_id
            JOIN sucursales s ON s.plant = i.plant
            WHERE {where_sql}
            ORDER BY (i.cajas_remanentes * m.precio_venta) DESC
            LIMIT 600""",
        params,
    ).fetchall()

    if not candidatos:
        return {"total": 0, "items": [], "generado": _now()}

    material_ids = sorted({r["material_id"] for r in candidatos})
    plants = sorted({r["plant"] for r in candidatos})
    ph_mat = ",".join("?" * len(material_ids))
    ph_plant = ",".join("?" * len(plants))

    ultima_venta_rows = db.execute(
        f"""SELECT material_id, plant, MAX(anio_mes) AS ultimo_mes
            FROM ventas_mensuales
            WHERE material_id IN ({ph_mat}) AND plant IN ({ph_plant}) AND cantidad_m2 > 0
            GROUP BY material_id, plant""",
        material_ids + plants,
    ).fetchall()
    ultima_venta = {(r["material_id"], r["plant"]): r["ultimo_mes"] for r in ultima_venta_rows}

    ref_row = db.execute("SELECT MAX(anio_mes) AS m FROM ventas_mensuales").fetchone()
    ref_anio_mes = ref_row["m"] if ref_row and ref_row["m"] else datetime.now(timezone.utc).strftime("%Y-%m")
    ref_year, ref_month = (int(x) for x in ref_anio_mes.split("-"))
    ref_date = datetime(ref_year, ref_month, 28, tzinfo=timezone.utc)

    def dias_sin_venta(material_id: str, plant: str) -> int:
        ultimo = ultima_venta.get((material_id, plant))
        if not ultimo:
            return DIAS_SIN_VENTA_NUNCA
        y, m = (int(x) for x in ultimo.split("-"))
        ult_date = datetime(y, m, 28, tzinfo=timezone.utc)
        return max(0, (ref_date - ult_date).days)

    items = []
    for r in candidatos:
        dsv = dias_sin_venta(r["material_id"], r["plant"])
        if dsv < dias_min:
            continue
        cajas = r["cajas_remanentes"]
        economico = bool(r["economico"])
        precio, es_supuesto, es_excepcion, motivo = precio_remate(cajas, economico, escalas)
        ruteo = compute_ruteo_remate(
            cajas, economico, r["organizacion"], r["plant"], r["nombre"], r["corredor"], escalas, rutas_gam, plazas
        )
        importe = round(precio * cajas)
        valor_en_riesgo = round(cajas * (r["precio_venta"] or 0))
        items.append(
            {
                "material_id": r["material_id"],
                "plant": r["plant"],
                "descripcion": r["descripcion"],
                "abc": r["abc"],
                "economico": economico,
                "organizacion": r["organizacion"],
                "nombre": r["nombre"],
                "corredor": r["corredor"],
                "diasSinVenta": dsv,
                "cajas": cajas,
                "precioPorCaja": precio,
                "importe": importe,
                "valorEnRiesgo": valor_en_riesgo,
                "esSupuestoPrecio": es_supuesto,
                "esExcepcionPrecio": es_excepcion,
                "motivoPrecio": motivo,
                "estado": "pendiente",
                **ruteo,
            }
        )

    items.sort(key=lambda x: x["valorEnRiesgo"], reverse=True)
    total = len(items)
    items = items[:limit]
    for i, it in enumerate(items, start=1):
        it["id"] = f"REM-{i:03d}"

    return {"total": total, "items": items, "generado": _now(), "referenciaFecha": ref_anio_mes, "diasMin": dias_min}


# ---------------------------------------------------------------------------
# Config editable (escalas / rutas / plazas) — sin tocar código.
# ---------------------------------------------------------------------------

@router.get("/config")
def get_config(db: sqlite3.Connection = Depends(get_db)):
    escalas, rutas_gam, plazas = _load_config(db)
    return {
        "escalas": [{"cajasMin": a, "cajasMax": b, "precioCaja": c, "traslada": d} for a, b, c, d in escalas],
        "rutasGam": rutas_gam,
        "plazasExcepcion": plazas,
    }


@router.put("/config/escalas")
def put_escalas(escalas: list[dict] = Body(...), db: sqlite3.Connection = Depends(get_db)):
    _ensure_tables(db)
    db.execute("DELETE FROM remate_escalas")
    db.executemany(
        "INSERT INTO remate_escalas (cajas_min, cajas_max, precio_caja, traslada) VALUES (?,?,?,?)",
        [(e["cajasMin"], e["cajasMax"], e["precioCaja"], int(bool(e.get("traslada", True)))) for e in escalas],
    )
    db.commit()
    return get_config(db)


@router.put("/config/rutas")
def put_rutas(rutas: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    _ensure_tables(db)
    db.execute("DELETE FROM remate_rutas_gam")
    db.executemany(
        "INSERT INTO remate_rutas_gam (corredor, cedis, sucursal_remate) VALUES (?,?,?)",
        [(k, v["cedis"], v["remate"]) for k, v in rutas.items()],
    )
    db.commit()
    return get_config(db)
