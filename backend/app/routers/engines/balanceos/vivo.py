"""Grid 1 de Balanceos con la posición EN VIVO del artículo (waykee 292300).

Grid 1 se arma al seleccionar UN material -> es "abrir un artículo": su
disponible / tránsito / comprometido y sus OCs pendientes salen de HANA en el
instante. Los parámetros analíticos (demanda, meses objetivo, prioridades)
siguen saliendo del snapshot, que es su fuente correcta.

Solo se sobrepone lo vivo cuando HANA respondió; si no, el grid corre igual
que antes sobre el snapshot y `fuente.live = false` lo dice.
"""

from __future__ import annotations

from app.core import articulo_vivo

from .constantes import DEFAULT_OBJETIVO_MESES

_CEROS = {"disponible": 0.0, "transito": 0.0, "comprometido": 0.0}


def leer(db, material_id: str) -> dict:
    return articulo_vivo.leer(db, material_id, partes=("posicion", "pedidos"))


def _filas_sin_snapshot(db, material_id: str, plants: set) -> list[dict]:
    """Centros con existencia/pedidos en HANA que el snapshot aún no tenía."""
    if not plants:
        return []
    ph = ",".join("?" * len(plants))
    rows = db.execute(
        f"""SELECT m.material_id, s.plant, m.descripcion, m.abc, m.m2_por_caja,
                   s.nombre, s.corredor, s.es_cedis,
                   COALESCE(c.meses_objetivo, ?) AS meses_objetivo
            FROM materiales m
            JOIN sucursales s ON s.plant IN ({ph})
            LEFT JOIN coberturas_objetivo c ON c.material_id = m.material_id
            WHERE m.material_id = ?""",
        [DEFAULT_OBJETIVO_MESES, *sorted(plants), material_id],
    ).fetchall()
    return [dict(r) for r in rows]


def sobreponer(db, material_id: str, filas: list, vivo: dict) -> list[dict]:
    """Filas del snapshot con disponible/tránsito/comprometido/pedidos de HANA.
    Un centro que HANA ya no reporta tiene hoy existencia cero."""
    pos = vivo["posicion"]
    pedidos: dict = {}
    for d in vivo["pedidos"]:
        pedidos[d["plant"]] = pedidos.get(d["plant"], 0.0) + (d["cantidad_pendiente"] or 0)
    conocidas = {f["plant"] for f in filas}
    con_algo = {p for p, v in pos.items() if any(v.values())} | set(pedidos)
    resultado = []
    for f in [dict(f) for f in filas] + _filas_sin_snapshot(db, material_id, con_algo - conocidas):
        f.update(pos.get(f["plant"], _CEROS))
        f["pedidos_abiertos"] = round(pedidos.get(f["plant"], 0.0), 3)
        resultado.append(f)
    return resultado
