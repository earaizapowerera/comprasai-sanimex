"""GET /generar — clic 1 del flujo estrella: C1 (reglas) + C2 (forecast
simple) + C3 (explicación), persistiendo cada línea como 'propuesto'."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime, timezone
from typing import Annotated, Optional

from fastapi import Depends, Query

from app.core.db import get_db
from app.routers.engines import lotes_compra

from .cargas import _cargar_categorias_tabla, _categoria_para_linea, _filtrar_sucursales_que_compran
from .constantes import DEFAULT_MOQ, DEFAULT_OBJETIVO_MESES, DEFAULT_PALLET
from .demanda import ContextoDemanda
from .linea import evaluar_linea
from .persistencia import _ensure_tables, _now
from .transferencias import AsignadorTransferencias, construir_info_por_linea


def generar_sugeridos(
    familia: Optional[str] = None,
    proveedor: Optional[str] = None,
    corredor: Optional[str] = None,
    plant: Optional[str] = None,
    abc: Optional[str] = Query(None, pattern="^[ABC]$"),
    solo_criticos: bool = Query(False, description="Solo líneas con cobertura actual = 0"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    fecha: Annotated[Optional[date], Query(description="Fecha de compra para resolver el Lote de Compra vigente (default: hoy UTC)")] = None,
    db: sqlite3.Connection = Depends(get_db),
):
    """Clic 1 del flujo estrella: corre C1 (reglas) + C2 (forecast simple) +
    C3 (explicación) y persiste cada línea como 'propuesto'."""
    _ensure_tables(db)
    # Waykee 292251: Lote de Compra vigente a `fecha` -> solo entran materiales
    # cuya categoría del mes de `fecha` esté habilitada. Sin lote -> sin filtro.
    fecha_iso = (fecha or datetime.now(timezone.utc).date()).isoformat()
    filtro_lote = lotes_compra.resolver_filtro(db, fecha_iso)
    habilitadas = filtro_lote.pop("_habilitadas")

    candidatos = _cargar_candidatos(db, familia, proveedor, corredor, plant, abc)
    material_ids = sorted({r["material_id"] for r in candidatos})
    # T29 (punto 5): categoría mensual por material (Excel hoy, SAP/HANA mañana).
    # Se carga antes del filtro de lote (292251), que la necesita.
    tabla_categorias = _cargar_categorias_tabla(db, material_ids, _placeholders(material_ids))
    if habilitadas is not None:
        candidatos = _aplicar_lote(candidatos, habilitadas, tabla_categorias, fecha_iso[:7], filtro_lote)
    # Waykee 292252: solo sucursales de COMPRA_DIRECTA generan sugeridos de
    # compra; esporádicas/no-compra se abastecen por traslado (Balanceos).
    candidatos, filtro_sucursal = _filtrar_sucursales_que_compran(db, candidatos)
    material_ids = sorted({r["material_id"] for r in candidatos})

    if not candidatos:
        return {"total": 0, "page": page, "page_size": page_size, "items": [], "generado": _now(),
                "lote": filtro_lote, "sucursal_compra": filtro_sucursal}

    demanda = ContextoDemanda(db, candidatos, material_ids, _placeholders(material_ids))
    info_por_linea = construir_info_por_linea(candidatos, demanda)
    asignador = AsignadorTransferencias(info_por_linea)
    items = []
    for r in candidatos:
        item = evaluar_linea(r, info_por_linea[(r["material_id"], r["plant"])], demanda, asignador,
                             tabla_categorias, solo_criticos)
        if item is not None:
            items.append(item)

    # Prioriza lo más crítico (menor cobertura primero); el orden/total
    # corren sobre TODO el universo filtrado para que el ranking sea correcto,
    # pero solo se PERSISTE/devuelve la página pedida (fix QA 23-ago: antes se
    # insertaba el universo completo -~9.8k filas- en cada click, ignorando
    # page_size y sin limpiar la tabla -> DB de 184MB y locks bajo concurrencia).
    items.sort(key=lambda x: x["cobertura_actual"])
    start = (page - 1) * page_size
    pagina = items[start:start + page_size]
    now = _persistir_pagina(db, pagina)
    return {
        "total": len(items),
        "page": page,
        "page_size": page_size,
        "items": pagina,
        "generado": now,
        "lote": filtro_lote,
        "sucursal_compra": filtro_sucursal,
    }


def _placeholders(material_ids: list[str]) -> str:
    return ",".join("?" * len(material_ids))


def _cargar_candidatos(db: sqlite3.Connection, familia, proveedor, corredor, plant, abc) -> list:
    where = ["1=1"]
    params: list = []
    for valor, condicion in (
        (familia, "m.familia = ?"),
        (proveedor, "pr.proveedor = ?"),
        (corredor, "s.corredor = ?"),
        (plant, "i.plant = ?"),
        (abc, "m.abc = ?"),
    ):
        if valor:
            where.append(condicion)
            params.append(valor)
    where_sql = " AND ".join(where)

    # T29 (waykee 291788, punto 1): la EXCEPCIÓN (material+sucursal) manda
    # SIEMPRE que exista; el DEFAULT (material) solo aplica en su ausencia.
    # CASE explícito para `meses_objetivo_fuente` en vez de inferirlo después
    # comparando floats (dos meses_objetivo podrían coincidir por casualidad
    # con distinta fuente).
    return db.execute(
        f"""SELECT i.material_id, i.plant, i.disponible, i.transito, i.comprometido,
                   m.descripcion, m.abc, m.m2_por_caja, m.precio_venta, m.costo,
                   s.corredor, s.organizacion, s.canal,
                   COALESCE(mox.meses, mod.meses, {DEFAULT_OBJETIVO_MESES}) AS meses_objetivo,
                   CASE
                       WHEN mox.meses IS NOT NULL THEN 'excepcion'
                       WHEN mod.meses IS NOT NULL THEN 'default'
                       ELSE 'fallback'
                   END AS meses_objetivo_fuente,
                   COALESCE(pr.moq_cajas, {DEFAULT_MOQ}) AS moq_cajas,
                   COALESCE(pr.cajas_por_pallet, {DEFAULT_PALLET}) AS cajas_por_pallet,
                   pr.proveedor, COALESCE(pr.lead_time_dias, 15) AS lead_time_dias
            FROM inventarios i
            JOIN materiales m ON m.material_id = i.material_id
            JOIN sucursales s ON s.plant = i.plant
            LEFT JOIN meses_objetivo_excepcion mox
                   ON mox.material_id = i.material_id AND mox.plant = i.plant
            LEFT JOIN meses_objetivo_default mod ON mod.material_id = i.material_id
            LEFT JOIN proveedores pr ON pr.material_id = i.material_id
            WHERE {where_sql}
            ORDER BY i.material_id, i.plant""",
        params,
    ).fetchall()


def _aplicar_lote(candidatos: list, habilitadas, tabla_categorias: dict, mes_lote: str, filtro_lote: dict) -> list:
    antes = len(candidatos)
    candidatos = lotes_compra.filtrar_por_lote(
        candidatos, habilitadas,
        lambda mid: (_categoria_para_linea(tabla_categorias, mid, mes_lote) or {}).get("valor"),
    )
    filtro_lote["lineas_excluidas"] = antes - len(candidatos)
    return candidatos


def _persistir_pagina(db: sqlite3.Connection, pagina: list[dict]) -> str:
    """DELETE previo (solo 'propuesto' — 'aprobado'/'rechazado' quedan como
    historial/auditoría intactos) + executemany en UNA sola transacción.
    Asigna id/estado a cada item y le quita las llaves internas."""
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
            # se elimina; la columna queda vacía ("[]") solo por compatibilidad
            # de esquema con filas históricas. datos_decision_json es la fuente real.
            "[]",
            json.dumps(it["datos_decision"], ensure_ascii=False),
            "propuesto", now, now,
        ))
        del it["_faltante_bruto"], it["_costo_unitario"]

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
    return now
