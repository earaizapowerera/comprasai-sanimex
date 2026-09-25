"""Consulta EN VIVO del stock actual en SAP HANA CAR PRD (solo lectura).

Ruta operativa, separada de la analítica: los motores (sugeridos, balanceos,
cobertura...) leen SIEMPRE el snapshot diario (SQL Server / SQLite) para que
sus resultados sean reproducibles y consistentes entre sí. Esto solo sirve
para mostrar "cuánto hay AHORA" de un par material-centro puntual.

Fuente: CV InventoryVisibilityCurrentStock.UnresUseStockQuantity -- la misma
ancla con la que se reconstruye kardex_diario, así que es comparable 1:1 con
inventarios.disponible del snapshot.

Credenciales solo por entorno (mismas que los extractores):
SANIMEX_CAR_HOST / _PORT / _USER / _PASS. Sin ellas -> no configurado.
Timeout corto (COMPRASAI_HANA_TIMEOUT_MS, default 3000): si HANA no responde,
el llamador cae al snapshot.
"""

import os
from typing import Optional

MANDT = "110"
CV_STOCK = '"_SYS_BIC"."sap.is.retail.car_s4h/InventoryVisibilityCurrentStock"'
_ENV = ("SANIMEX_CAR_HOST", "SANIMEX_CAR_PORT", "SANIMEX_CAR_USER", "SANIMEX_CAR_PASS")


class HanaNoDisponible(Exception):
    """HANA no configurado, sin driver, inalcanzable o sin respuesta a tiempo."""


def configurado() -> bool:
    return all(os.environ.get(k) for k in _ENV)


def _timeout_ms() -> int:
    return int(os.environ.get("COMPRASAI_HANA_TIMEOUT_MS", "3000"))


def _conectar():
    if not configurado():
        raise HanaNoDisponible("hana_no_configurado")
    try:
        from hdbcli import dbapi
    except ImportError as exc:  # imagen sin driver
        raise HanaNoDisponible("hdbcli_no_instalado") from exc
    ms = _timeout_ms()
    try:
        return dbapi.connect(
            address=os.environ["SANIMEX_CAR_HOST"], port=int(os.environ["SANIMEX_CAR_PORT"]),
            user=os.environ["SANIMEX_CAR_USER"], password=os.environ["SANIMEX_CAR_PASS"],
            connectTimeout=ms, communicationTimeout=ms,
        )
    except Exception as exc:
        raise HanaNoDisponible(f"conexion: {type(exc).__name__}") from exc


def stock_actual(material_id: str, plant: str) -> Optional[float]:
    """Stock libre utilización actual. None si HANA no tiene el par."""
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute(
            f'SELECT "UnresUseStockQuantity" FROM {CV_STOCK} '
            'WHERE "SAPClient" = ? AND "Article" = ? AND "Location" = ?',
            (MANDT, material_id, plant),
        )
        row = cur.fetchone()
    except Exception as exc:
        raise HanaNoDisponible(f"consulta: {type(exc).__name__}") from exc
    finally:
        conn.close()
    if row is None or row[0] is None:
        return None
    return float(row[0])
