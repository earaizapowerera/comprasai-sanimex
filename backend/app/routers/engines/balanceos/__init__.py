"""Motor C1 · Balanceos — propuestas de transferencia dentro de corredor
(RF-014/015, RN-02) para la pantalla S10 Balanceos & Remates (T10).

Reusa las funciones puras de `engines/sugeridos` (fuente única de verdad
acordada con T9, ver waykee 290092) para cobertura/demanda; aquí se agrega
la parte que sugeridos NO expone como listado propio: un catálogo
independiente de "qué transferir antes de comprar" a nivel corredor, con
costo-beneficio (costo de traslado vs. costo evitado de comprar).

Paquete (ticket 292259, antes un solo balanceos.py de ~1050 líneas):
  constantes        -- constantes y _now
  persistencia      -- DDL de tablas, costo por corredor, umbral, descartes,
                       prioridad efectiva y universo de sucursales (292252)
  triggers          -- funciones puras del motor de triggers v2 (292187)
  propuestas        -- cómputo de propuestas + cache en memoria + agrupación
  grid              -- Grid 1, backorder de compra y sugerencia de cantidad
  rutas_propuestas  -- endpoints zonas/articulos/recalcular/propuestas/config
  pendientes        -- descartes y Grid 2 (pendientes/traslados)
  config            -- umbral de días de pedido y prioridad

Este __init__ re-exporta la superficie pública (main.py, tests) y registra
las rutas en el MISMO orden que el módulo original.
"""

from fastapi import APIRouter

from .config import (
    delete_prioridad_excepcion,
    get_prioridad,
    get_umbral_dias,
    put_prioridad,
    put_umbral_dias,
)
from .constantes import (  # noqa: F401
    COSTO_CAJA_TRASLADO_DEFAULT,
    DEFAULT_OBJETIVO_MESES,
    UMBRAL_DIAS_PEDIDO_DEFAULT,
    _now,
)
from .grid import _compute_grid1, grid1, grid1_backorder_detalle, sugerencia_cantidad  # noqa: F401
from .pendientes import (  # noqa: F401
    _postear_traslado_sap,
    agregar_pendiente,
    crear_descarte,
    generar_traslado,
    listar_pendientes,
    marcar_entregado,
)
from .persistencia import (  # noqa: F401
    _costo_traslado_por_corredor,
    _descartes_activos,
    _ensure_tables,
    _prioridad_efectiva,
    _sin_plantas_fuera_de_universo,
    _umbral_dias_pedido,
    init_tables,
)
from .propuestas import (  # noqa: F401
    _cache,
    _cache_lock,
    _compute_all_propuestas,
    _get_cached_propuestas,
    agrupar_por_articulo,
    agrupar_por_zona,
    recalcular_propuestas,
    warm_cache,
)
from .rutas_propuestas import (
    articulos_balanceo,
    get_config,
    propuestas_balanceo,
    put_config,
    recalcular_balanceo,
    zonas_balanceo,
)
from .triggers import (  # noqa: F401
    calc_cajas_a_m2,
    calc_cantidad_sugerida_balanceo,
    calc_dias_desde_pedido,
    es_rojo,
    estado_semaforo_balanceo,
    evaluar_trigger,
    permite_transferencia_por_prioridad,
    resumir_pedidos_compra,
)

router = APIRouter(prefix="/api/balanceos", tags=["engines:balanceos"])

router.get("/zonas")(zonas_balanceo)
router.get("/articulos")(articulos_balanceo)
router.post("/recalcular")(recalcular_balanceo)
router.get("/propuestas")(propuestas_balanceo)
router.get("/config")(get_config)
router.put("/config")(put_config)
router.get("/grid")(grid1)
router.get("/grid/backorder-detalle")(grid1_backorder_detalle)
router.get("/sugerencia-cantidad")(sugerencia_cantidad)
router.post("/descartes")(crear_descarte)
router.post("/pendientes")(agregar_pendiente)
router.get("/pendientes")(listar_pendientes)
router.post("/pendientes/generar-traslado")(generar_traslado)
router.post("/pendientes/marcar-entregado")(marcar_entregado)
router.get("/config/umbral-dias")(get_umbral_dias)
router.put("/config/umbral-dias")(put_umbral_dias)
router.get("/config/prioridad")(get_prioridad)
router.put("/config/prioridad")(put_prioridad)
router.delete("/config/prioridad/excepcion")(delete_prioridad_excepcion)
