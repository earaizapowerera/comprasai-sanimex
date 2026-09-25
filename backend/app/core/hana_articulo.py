"""Lecturas EN VIVO de HANA CAR para UN artículo (waykee 292300).

Mismas fuentes y reglas que los extractores del snapshot, para que el valor en
vivo y el del snapshot sean comparables campo a campo:
  - posición (disponible / tránsito / comprometido): data/extract_v2_stock_real.py
  - pedidos de compra pendientes (EKKO/EKPO + EKET + LFA1): data/extract_v5_detalle.py
  - backorder de ventas = entregas abiertas (LIPS/LIKP sin PGI + KNA1): idem
  - venta del mes en curso (BI/ZVTA_BONO, ZMETROS): data/extract_real_car.py

Todo filtrado a UN material (y opcionalmente un centro): 0.1-0.3 s por
consulta medido contra PRD. Se lee con UN solo cursor (una conexión por
apertura de artículo). Errores -> hana_live.HanaNoDisponible.
"""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from app.core.hana_live import CV, MANDT, SCHEMA_SAP, cursor

_Q_STOCK = f"""
    SELECT "Location", SUM("UnresUseStockQuantity"),
           SUM("InTransitStockQuantity") + SUM("InTransferStockQuantity")
    FROM {CV.format("InventoryVisibilityStockQuantities")}
    WHERE "SAPClient" = ? AND "Article" = ? {{plant}}
    GROUP BY "Location"
"""
_Q_RESERVADO = f"""
    SELECT "Location", SUM("ReservedQuantity")
    FROM {CV.format("InventoryVisibilityWithSalesOrderReservedQuantity")}
    WHERE "SAPClient" = ? AND "Article" = ? {{plant}}
    GROUP BY "Location"
"""
# Líneas abiertas: ELIKZ vacío y cabecera no borrada; EKPO.LOEKZ NO se filtra
# (así lo hace el snapshot, ver extract_v5_detalle.extract_pedidos_compra).
_Q_PO = f"""
    SELECT p.WERKS, p.EBELN, p.EBELP, p.MENGE, k.BEDAT, k.AEDAT,
           COALESCE(NULLIF(TRIM(l.NAME1), ''), k.LIFNR)
    FROM {SCHEMA_SAP}.EKPO p
    JOIN {SCHEMA_SAP}.EKKO k ON k.MANDT = p.MANDT AND k.EBELN = p.EBELN
    LEFT JOIN {SCHEMA_SAP}.LFA1 l ON l.MANDT = k.MANDT AND l.LIFNR = k.LIFNR
    WHERE p.MANDT = ? AND p.MATNR = ? {{plant}}
      AND (p.ELIKZ IS NULL OR p.ELIKZ = '')
      AND (k.LOEKZ IS NULL OR k.LOEKZ = '')
"""
_Q_EKET = f"""
    SELECT e.EBELN, e.EBELP, e.EINDT, e.MENGE, e.WEMNG
    FROM {SCHEMA_SAP}.EKET e
    JOIN {SCHEMA_SAP}.EKPO p ON p.MANDT = e.MANDT AND p.EBELN = e.EBELN AND p.EBELP = e.EBELP
    JOIN {SCHEMA_SAP}.EKKO k ON k.MANDT = p.MANDT AND k.EBELN = p.EBELN
    WHERE e.MANDT = ? AND p.MATNR = ? {{plant}}
      AND (p.ELIKZ IS NULL OR p.ELIKZ = '')
      AND (k.LOEKZ IS NULL OR k.LOEKZ = '')
    ORDER BY e.EBELN, e.EBELP, e.EINDT
"""
_Q_BACKORDER = f"""
    SELECT p.WERKS, p.VBELN, p.POSNR, p.LFIMG,
           COALESCE(NULLIF(TRIM(c.NAME1), ''), h.KUNNR), h.KODAT, h.LFDAT
    FROM {SCHEMA_SAP}.LIPS p
    JOIN {SCHEMA_SAP}.LIKP h ON h.MANDT = p.MANDT AND h.VBELN = p.VBELN
    LEFT JOIN {SCHEMA_SAP}.KNA1 c ON c.MANDT = h.MANDT AND c.KUNNR = h.KUNNR
    WHERE p.MANDT = ? AND p.MATNR = ? {{plant}}
      AND (h.WADAT_IST IS NULL OR h.WADAT_IST = '' OR h.WADAT_IST = '00000000')
      AND p.LFIMG > 0
"""
_Q_VENTA_MES = """
    SELECT PLANT, SUM(ZMETROS)
    FROM "_SYS_BIC"."BI/ZVTA_BONO"
    WHERE MATERIALNUMBER = ? AND ZANIO_MES = ? {plant}
    GROUP BY PLANT
"""


def _fecha(x) -> Optional[str]:
    """SAP DATS (YYYYMMDD) -> YYYY-MM-DD, tolerante a nulos/ceros."""
    s = str(x or "").strip()
    if len(s) == 8 and s.isdigit() and s != "00000000":
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return None


def _s(x) -> str:
    return (x or "").strip()


def _run(cur, sql: str, params: list, plant: Optional[str], col: str) -> list:
    filtro = f"AND {col} = ?" if plant else ""
    cur.execute(sql.format(plant=filtro), params + ([plant] if plant else []))
    return cur.fetchall()


def _posicion(cur, material_id: str, plant: Optional[str]) -> dict:
    pos: dict = defaultdict(lambda: {"disponible": 0.0, "transito": 0.0, "comprometido": 0.0})
    for loc, disp, trans in _run(cur, _Q_STOCK, [MANDT, material_id], plant, '"Location"'):
        pos[_s(loc)].update(disponible=float(disp or 0), transito=float(trans or 0))
    for loc, res in _run(cur, _Q_RESERVADO, [MANDT, material_id], plant, '"Location"'):
        pos[_s(loc)]["comprometido"] = float(res or 0)
    return dict(pos)


def _pedidos_compra(cur, material_id: str, plant: Optional[str]) -> list[dict]:
    lineas = _run(cur, _Q_PO, [MANDT, material_id], plant, "p.WERKS")
    recibido: dict = defaultdict(float)
    entrega: dict = {}
    for ebeln, ebelp, eindt, menge, wemng in _run(cur, _Q_EKET, [MANDT, material_id], plant, "p.WERKS"):
        k = (_s(ebeln), _s(ebelp))
        recibido[k] += float(wemng or 0)
        if float(menge or 0) - float(wemng or 0) > 0.001 and k not in entrega and _fecha(eindt):
            entrega[k] = _fecha(eindt)  # primera schedule line con pendiente
    docs = []
    for werks, ebeln, ebelp, menge, bedat, aedat, proveedor in lineas:
        k = (_s(ebeln), _s(ebelp))
        pendiente = max(0.0, float(menge or 0) - recibido.get(k, 0.0))
        if pendiente <= 0.001:
            continue  # ya recibida por completo
        docs.append({
            "plant": _s(werks), "po": k[0], "posicion": k[1], "proveedor": _s(proveedor) or None,
            "cantidad_pendiente": round(pendiente, 3), "cantidad_pedida": round(float(menge or 0), 3),
            "fecha_po": _fecha(bedat) or _fecha(aedat), "fecha_entrega_estimada": entrega.get(k),
        })
    return sorted(docs, key=lambda d: (d["fecha_entrega_estimada"] or "9999", d["po"]))


def _backorder(cur, material_id: str, plant: Optional[str]) -> list[dict]:
    docs = [{
        "plant": _s(werks), "documento": _s(vbeln), "posicion": _s(posnr), "cliente": _s(cliente) or None,
        "cantidad_pendiente": round(float(lfimg or 0), 3),
        "fecha_documento": _fecha(kodat), "fecha_entrega_comprometida": _fecha(lfdat),
    } for werks, vbeln, posnr, lfimg, cliente, kodat, lfdat
        in _run(cur, _Q_BACKORDER, [MANDT, material_id], plant, "p.WERKS")]
    return sorted(docs, key=lambda d: (d["fecha_entrega_comprometida"] or "9999", d["documento"]))


def _venta_mes(cur, material_id: str, plant: Optional[str], anio_mes: str) -> dict:
    rows = _run(cur, _Q_VENTA_MES, [material_id, anio_mes.replace("-", "")], plant, "PLANT")
    return {_s(p): round(float(m2 or 0), 2) for p, m2 in rows}


def leer(material_id: str, plant: Optional[str] = None, partes=("posicion", "pedidos", "backorder", "venta_mes")) -> dict:
    """Lee en una sola conexión las partes pedidas del artículo."""
    anio_mes = datetime.now(timezone.utc).strftime("%Y-%m")
    lectores = {
        "posicion": lambda c: _posicion(c, material_id, plant),
        "pedidos": lambda c: _pedidos_compra(c, material_id, plant),
        "backorder": lambda c: _backorder(c, material_id, plant),
        "venta_mes": lambda c: {"anio_mes": anio_mes, "m2_por_plant": _venta_mes(c, material_id, plant, anio_mes)},
    }
    with cursor() as cur:
        return {p: lectores[p](cur) for p in partes}
