"""Lotes de Compra (waykee 292251) -- configuración de negocio que restringe
qué clasificaciones comerciales (REM, PET52, OUTLET01, ...) entran al motor
de Sugeridos en un rango de fechas.

Modelo:
  lotes_compra                 1 fila por rango (nombre, fecha_inicio, fecha_fin, activo)
  lotes_compra_clasificacion   N clasificaciones habilitadas por lote

Regla del filtro (ver clasificaciones_vigentes / material_en_lote):
  - Para una fecha dada se juntan las clasificaciones de TODOS los lotes
    activos cuyo rango [fecha_inicio, fecha_fin] la cubre (unión).
  - Si NINGÚN lote activo cubre la fecha -> None = no se filtra (el flujo de
    Sugeridos se comporta exactamente como antes de este cambio).
  - Si hay lote vigente, un material entra solo si su categoría vigente al mes
    de esa fecha (categorias_mensuales, misma resolución que
    sugeridos._categoria_para_linea) está en la unión. Material sin categoría
    cargada -> queda FUERA (no pertenece a ninguna clase habilitada).

Es configuración propia de la app (no dato extraído de HANA): vive en la BD de
la app con el mismo acceso sqlite3 que el resto de motores (core/db.py).
"""

from __future__ import annotations

import calendar
import sqlite3
from datetime import date, datetime, timezone
from typing import Annotated, Callable, Iterable, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.core import sqlserver
from app.core.db import get_db

router = APIRouter(prefix="/api/engines/sugeridos/lotes", tags=["engines:sugeridos:lotes"])

SEED_CREADO_POR = "seed-292251"


# ---------------------------------------------------------------------------
# Funciones puras (sin I/O)
# ---------------------------------------------------------------------------

def normalizar_clasificacion(valor: Optional[str]) -> str:
    return (valor or "").strip()


def clasificaciones_vigentes(lotes: Iterable[dict], fecha: str) -> Optional[set[str]]:
    """Unión de clasificaciones de los lotes activos que cubren `fecha`
    (ISO 'YYYY-MM-DD'). None si ningún lote activo la cubre -> no filtrar."""
    vigentes = [
        lote for lote in lotes
        if lote.get("activo") and lote["fecha_inicio"] <= fecha <= lote["fecha_fin"]
    ]
    if not vigentes:
        return None
    return {c for lote in vigentes for c in lote.get("clasificaciones", [])}


def material_en_lote(categoria: Optional[str], habilitadas: Optional[set[str]]) -> bool:
    if habilitadas is None:
        return True
    return categoria is not None and categoria in habilitadas


def filtrar_por_lote(
    filas: list[dict],
    habilitadas: Optional[set[str]],
    categoria_de: Callable[[str], Optional[str]],
) -> list[dict]:
    """Filtra filas con `material_id` según las clasificaciones habilitadas."""
    if habilitadas is None:
        return filas
    return [f for f in filas if material_en_lote(categoria_de(f["material_id"]), habilitadas)]


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------

def _tabla_existe(db: sqlite3.Connection, tabla: str) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", [tabla]
    ).fetchone() is not None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_tables(db: sqlite3.Connection) -> None:
    """Crea las tablas UNA vez al arranque (fuera del hot path, mismo patrón que
    remates/balanceos). El seed de ejemplo solo corre cuando la tabla nace, para
    no resucitarlo si el usuario borra todos sus lotes."""
    # En SQL Server la tabla nace en ensure_app_schema (antes de este punto).
    nueva = not _tabla_existe(db, "lotes_compra") or sqlserver.born_this_run("lotes_compra")
    db.execute(
        """CREATE TABLE IF NOT EXISTS lotes_compra (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre        TEXT NOT NULL,
            fecha_inicio  TEXT NOT NULL,
            fecha_fin     TEXT NOT NULL,
            activo        INTEGER NOT NULL DEFAULT 1,
            creado_por    TEXT,
            creado_en     TEXT NOT NULL,
            actualizado_en TEXT NOT NULL,
            CHECK (fecha_fin >= fecha_inicio)
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS lotes_compra_clasificacion (
            lote_id       INTEGER NOT NULL REFERENCES lotes_compra(id) ON DELETE CASCADE,
            clasificacion TEXT NOT NULL,
            PRIMARY KEY (lote_id, clasificacion)
        )"""
    )
    if nueva:
        _seed_ejemplo(db)
    db.commit()


def _clasificacion_pet_ejemplo(db: sqlite3.Connection) -> Optional[str]:
    """PET* más frecuente en el mes más reciente con categorías (la vigente
    hoy); si ese mes no trae PET, la PET más frecuente de toda la historia."""
    if not _tabla_existe(db, "categorias_mensuales"):
        return None
    row = db.execute(
        """SELECT categoria FROM categorias_mensuales
           WHERE categoria LIKE 'PET%'
             AND anio_mes = (SELECT MAX(anio_mes) FROM categorias_mensuales)
           GROUP BY categoria ORDER BY COUNT(*) DESC, categoria LIMIT 1"""
    ).fetchone() or db.execute(
        """SELECT categoria FROM categorias_mensuales WHERE categoria LIKE 'PET%'
           GROUP BY categoria ORDER BY COUNT(*) DESC, categoria LIMIT 1"""
    ).fetchone()
    return row["categoria"] if row else None


def _seed_ejemplo(db: sqlite3.Connection, hoy: Optional[date] = None) -> Optional[int]:
    """Seed pedido por Enrique: un lote del mes actual con UNA clasificación PET."""
    clasif = _clasificacion_pet_ejemplo(db)
    if not clasif:
        return None
    hoy = hoy or datetime.now(timezone.utc).date()
    inicio = hoy.replace(day=1)
    fin = hoy.replace(day=calendar.monthrange(hoy.year, hoy.month)[1])
    return _crear_lote(db, f"Lote {inicio:%Y-%m} · {clasif}", inicio.isoformat(), fin.isoformat(), True, [clasif], SEED_CREADO_POR)


def _crear_lote(
    db: sqlite3.Connection, nombre: str, fecha_inicio: str, fecha_fin: str,
    activo: bool, clasificaciones: list[str], creado_por: Optional[str],
) -> int:
    now = _now()
    cur = db.execute(
        """INSERT INTO lotes_compra (nombre, fecha_inicio, fecha_fin, activo, creado_por, creado_en, actualizado_en)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [nombre, fecha_inicio, fecha_fin, int(activo), creado_por, now, now],
    )
    lote_id = cur.lastrowid
    _reemplazar_clasificaciones(db, lote_id, clasificaciones)
    return lote_id


def _reemplazar_clasificaciones(db: sqlite3.Connection, lote_id: int, clasificaciones: list[str]) -> None:
    db.execute("DELETE FROM lotes_compra_clasificacion WHERE lote_id = ?", [lote_id])
    limpias = sorted({normalizar_clasificacion(c) for c in clasificaciones} - {""})
    db.executemany(
        "INSERT INTO lotes_compra_clasificacion (lote_id, clasificacion) VALUES (?, ?)",
        [(lote_id, c) for c in limpias],
    )


def cargar_lotes(db: sqlite3.Connection) -> list[dict]:
    if not _tabla_existe(db, "lotes_compra"):
        return []
    lotes = [dict(r) for r in db.execute("SELECT * FROM lotes_compra ORDER BY fecha_inicio DESC, id DESC")]
    por_lote: dict[int, list[str]] = {}
    for r in db.execute("SELECT lote_id, clasificacion FROM lotes_compra_clasificacion ORDER BY clasificacion"):
        por_lote.setdefault(r["lote_id"], []).append(r["clasificacion"])
    for lote in lotes:
        lote["activo"] = bool(lote["activo"])
        lote["clasificaciones"] = por_lote.get(lote["id"], [])
    return lotes


def resolver_filtro(db: sqlite3.Connection, fecha: str) -> dict:
    """Lo que consume el motor de Sugeridos: clasificaciones habilitadas (o None)
    y los lotes que las aportan, para reportarlo en la respuesta."""
    lotes = cargar_lotes(db)
    habilitadas = clasificaciones_vigentes(lotes, fecha)
    return {
        "fecha": fecha,
        "aplicado": habilitadas is not None,
        "clasificaciones": sorted(habilitadas) if habilitadas is not None else [],
        "lotes": [
            {"id": l["id"], "nombre": l["nombre"], "fecha_inicio": l["fecha_inicio"], "fecha_fin": l["fecha_fin"]}
            for l in lotes if l["activo"] and l["fecha_inicio"] <= fecha <= l["fecha_fin"]
        ],
        "_habilitadas": habilitadas,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _validar_fechas(fecha_inicio: str, fecha_fin: str) -> None:
    try:
        ini, fin = date.fromisoformat(fecha_inicio), date.fromisoformat(fecha_fin)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Fechas deben ser ISO YYYY-MM-DD")
    if fin < ini:
        raise HTTPException(status_code=422, detail="fecha_fin debe ser >= fecha_inicio")


def _lote_o_404(db: sqlite3.Connection, lote_id: int) -> dict:
    lote = next((l for l in cargar_lotes(db) if l["id"] == lote_id), None)
    if lote is None:
        raise HTTPException(status_code=404, detail=f"Lote {lote_id} no existe")
    return lote


@router.get("")
def listar_lotes(db: sqlite3.Connection = Depends(get_db)):
    return {"items": cargar_lotes(db)}


@router.get("/clasificaciones")
def catalogo_clasificaciones(db: sqlite3.Connection = Depends(get_db)):
    """Clasificaciones reales del dataset (categorias_mensuales) con el número
    de materiales que la traen en el mes más reciente, para el selector."""
    if not _tabla_existe(db, "categorias_mensuales"):
        return {"anio_mes": None, "items": []}
    ultimo = db.execute("SELECT MAX(anio_mes) AS m FROM categorias_mensuales").fetchone()["m"]
    rows = db.execute(
        """SELECT categoria AS clasificacion,
                  SUM(CASE WHEN anio_mes = ? THEN 1 ELSE 0 END) AS materiales_mes,
                  COUNT(DISTINCT material_id) AS materiales_hist
           FROM categorias_mensuales WHERE categoria IS NOT NULL AND TRIM(categoria) <> ''
           GROUP BY categoria ORDER BY materiales_mes DESC, materiales_hist DESC, categoria""",
        [ultimo],
    ).fetchall()
    return {"anio_mes": ultimo, "items": rows}


@router.get("/vigentes")
def lotes_vigentes(fecha: Annotated[Optional[date], Query()] = None, db: sqlite3.Connection = Depends(get_db)):
    fecha_iso = (fecha or datetime.now(timezone.utc).date()).isoformat()
    filtro = resolver_filtro(db, fecha_iso)
    filtro.pop("_habilitadas")
    return filtro


@router.post("", status_code=201)
def crear_lote(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    nombre = (payload.get("nombre") or "").strip()
    fecha_inicio, fecha_fin = payload.get("fecha_inicio"), payload.get("fecha_fin")
    _validar_fechas(fecha_inicio, fecha_fin)
    if not nombre:
        nombre = f"Lote {fecha_inicio} a {fecha_fin}"
    lote_id = _crear_lote(
        db, nombre, fecha_inicio, fecha_fin, bool(payload.get("activo", True)),
        list(payload.get("clasificaciones") or []), payload.get("creado_por") or "planeador",
    )
    db.commit()
    return _lote_o_404(db, lote_id)


@router.put("/{lote_id}")
def actualizar_lote(lote_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """Actualización parcial: nombre, fechas, activo y/o el set completo de
    clasificaciones (la UI manda el set resultante al agregar/quitar una)."""
    actual = _lote_o_404(db, lote_id)
    fecha_inicio = payload.get("fecha_inicio", actual["fecha_inicio"])
    fecha_fin = payload.get("fecha_fin", actual["fecha_fin"])
    _validar_fechas(fecha_inicio, fecha_fin)
    nombre = (payload.get("nombre") if payload.get("nombre") is not None else actual["nombre"]).strip() or actual["nombre"]
    activo = bool(payload.get("activo", actual["activo"]))
    db.execute(
        """UPDATE lotes_compra SET nombre = ?, fecha_inicio = ?, fecha_fin = ?, activo = ?, actualizado_en = ?
           WHERE id = ?""",
        [nombre, fecha_inicio, fecha_fin, int(activo), _now(), lote_id],
    )
    if "clasificaciones" in payload:
        _reemplazar_clasificaciones(db, lote_id, list(payload.get("clasificaciones") or []))
    db.commit()
    return _lote_o_404(db, lote_id)


@router.delete("/{lote_id}")
def borrar_lote(lote_id: int, db: sqlite3.Connection = Depends(get_db)):
    _lote_o_404(db, lote_id)
    db.execute("DELETE FROM lotes_compra_clasificacion WHERE lote_id = ?", [lote_id])
    db.execute("DELETE FROM lotes_compra WHERE id = ?", [lote_id])
    db.commit()
    return {"borrado": lote_id}
