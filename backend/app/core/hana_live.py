"""Conexión EN VIVO a SAP HANA CAR PRD (solo lectura).

Ruta operativa, separada de la analítica: los motores (sugeridos, balanceos,
cobertura...) leen SIEMPRE el snapshot diario (SQL Server / SQLite) para que
sus resultados sean reproducibles y consistentes entre sí -- son los "papeles
de trabajo". Lo que se muestra al ABRIR un artículo sale de aquí, del
instante (waykee 292300; ver app.core.articulo_vivo).

Credenciales solo por entorno (mismas que los extractores):
SANIMEX_CAR_HOST / _PORT / _USER / _PASS. Sin ellas -> no configurado.
En prod el host es el túnel inverso desde la Mac con VPN
(deploy/hana-tunnel), porque el VM no tiene ruta propia a HANA.

Timeouts cortos: COMPRASAI_HANA_TIMEOUT_MS (conexión, default 3000) y
COMPRASAI_HANA_QUERY_TIMEOUT_MS (por consulta, default 8000). Si la conexión
falla, un cortacircuito evita reintentar durante COMPRASAI_HANA_REINTENTO_S
(default 30): mientras el túnel esté caído cada clic responde el snapshot al
instante en vez de esperar el timeout.
"""

import os
import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional

MANDT = "110"
SCHEMA_SAP = "SAPS4H"  # réplica S/4HANA dentro de CAR (mismo que data/extract_v5_detalle.py)
CV = '"_SYS_BIC"."sap.is.retail.car_s4h/{}"'
CV_STOCK = CV.format("InventoryVisibilityCurrentStock")
_ENV = ("SANIMEX_CAR_HOST", "SANIMEX_CAR_PORT", "SANIMEX_CAR_USER", "SANIMEX_CAR_PASS")

_breaker_lock = threading.Lock()
_breaker = {"hasta": 0.0, "motivo": ""}


class HanaNoDisponible(Exception):
    """HANA no configurado, sin driver, inalcanzable o sin respuesta a tiempo."""


def configurado() -> bool:
    return all(os.environ.get(k) for k in _ENV)


def _env_int(nombre: str, default: int) -> int:
    return int(os.environ.get(nombre) or default)


def _abrir_breaker(motivo: str) -> None:
    with _breaker_lock:
        _breaker["hasta"] = time.monotonic() + _env_int("COMPRASAI_HANA_REINTENTO_S", 30)
        _breaker["motivo"] = motivo


def reset_breaker() -> None:
    with _breaker_lock:
        _breaker["hasta"] = 0.0
        _breaker["motivo"] = ""


def _conectar():
    if not configurado():
        raise HanaNoDisponible("hana_no_configurado")
    with _breaker_lock:
        if time.monotonic() < _breaker["hasta"]:
            raise HanaNoDisponible(f"{_breaker['motivo']} (reintento en espera)")
    try:
        from hdbcli import dbapi
    except ImportError as exc:  # imagen sin driver
        raise HanaNoDisponible("hdbcli_no_instalado") from exc
    try:
        return dbapi.connect(
            address=os.environ["SANIMEX_CAR_HOST"], port=int(os.environ["SANIMEX_CAR_PORT"]),
            user=os.environ["SANIMEX_CAR_USER"], password=os.environ["SANIMEX_CAR_PASS"],
            connectTimeout=_env_int("COMPRASAI_HANA_TIMEOUT_MS", 3000),
            communicationTimeout=_env_int("COMPRASAI_HANA_QUERY_TIMEOUT_MS", 8000),
        )
    except Exception as exc:
        motivo = f"conexion: {type(exc).__name__}"
        _abrir_breaker(motivo)
        raise HanaNoDisponible(motivo) from exc


@contextmanager
def cursor() -> Iterator:
    """Cursor de una conexión nueva; cualquier error de consulta sale como
    HanaNoDisponible para que el llamador caiga al snapshot."""
    conn = _conectar()
    try:
        yield conn.cursor()
    except HanaNoDisponible:
        raise
    except Exception as exc:
        raise HanaNoDisponible(f"consulta: {type(exc).__name__}") from exc
    finally:
        conn.close()


def stock_actual(material_id: str, plant: str) -> Optional[float]:
    """Stock libre utilización actual. None si HANA no tiene el par."""
    with cursor() as cur:
        cur.execute(
            f'SELECT "UnresUseStockQuantity" FROM {CV_STOCK} '
            'WHERE "SAPClient" = ? AND "Article" = ? AND "Location" = ?',
            (MANDT, material_id, plant),
        )
        row = cur.fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0])
