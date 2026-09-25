"""Motor C1 · Sugeridos de Compra (backend de la pantalla estrella S8).

Implementa el contrato descrito en README_MOTORES.py:
  - disponible neto, cobertura actual vs objetivo (RN-01)
  - transferencia antes que compra dentro del corredor (RN-02)
  - redondeo a MOQ / múltiplo de empaque / pallet (RF-011 / RF-016)
  - workflow Planeador (propone) -> Gerente (aprueba/rechaza) (RF-008)
  - exportación de plantilla de carga masiva a SAP (RF-009)

Este motor nació como parte de T9 (pantalla Sugeridos) porque T4 (dueño
formal de motores_c1.py) todavía no había arrancado cuando el deadline de
la demo obligaba a tener el flujo estrella funcionando end-to-end. Las
funciones puras de esta capa (prefijo `calc_`) están aisladas y son fáciles
de mover/fusionar a `motores_c1.py` sin tocar el contrato HTTP si T4 entrega
su propia versión — ver mensaje de coordinación en waykee 290092.

Casos golden validados a mano por T14 (waykee 290102, msg 61807):
  G1/G2/G3 -> RN-01 (ver calc_cobertura_meses + regla de no-sugerir)
  G4/G5    -> RN-02 (ver transferencias.AsignadorTransferencias)
  G6/G7/G8 -> redondeo MOQ/empaque/m2 (ver calc_redondeo_moq y calc_m2_a_cajas)

Paquete (ticket 292259, modularidad): el antiguo sugeridos.py de ~1550
líneas se dividió en módulos de <300 líneas. Este __init__ registra las
rutas en el MISMO orden que antes y re-exporta la superficie pública que
importan main.py, balanceos, tests y analysis/backtest_forecast.py.

  constantes      parámetros del motor (MOQ, pallet, ventanas, ratios)
  calculos        funciones puras calc_* de unidades/cobertura/promedios/compra
  estadistica     mediana/MAD/outlier, tendencia y confianza
  datos_decision  payload del popup de decisión (build_datos_decision, _a_m2)
  persistencia    tablas del workflow, _now, _tabla_existe
  series          meses contiguos, saldos fin de mes, días sin inventario
  cargas          categorías, stats POS, salidas kardex, ajuste de pico, sucursales
  demanda         ContextoDemanda: carga batch + motor de 3 promedios por línea
  transferencias  RN-02 (excedente intra-corredor)
  linea           evaluación de una línea candidata -> item sugerido
  generar         GET /generar
  consultas       opciones, lista, drill-downs, exportar-sap
  workflow        editar, meses objetivo, decidir
"""

from __future__ import annotations

from fastapi import APIRouter

from .calculos import (  # noqa: F401
    calc_cobertura_meses,
    calc_compra_sugerida,
    calc_consumo_mes_referencia_corregido,
    calc_factor_m2_por_pieza,
    calc_m2_a_cajas,
    calc_motivo_redondeo_pallet,
    calc_promedio_general,
    calc_promedio_simple,
    calc_promedio_ultimos_n,
    calc_redondeo_moq,
    calc_redondeo_pallet,
    calc_redondeo_pallets_completos,
    calc_valor_mes_ajustado,
)
from .cargas import (  # noqa: F401
    _ajuste_pico_mes,
    _cargar_categorias_tabla,
    _cargar_salidas_diarias,
    _cargar_stats_mensuales,
    _categoria_para_linea,
    _filtrar_sucursales_que_compran,
    _modo_promedio3,
)
from .constantes import (  # noqa: F401
    DEFAULT_MOQ,
    DEFAULT_OBJETIVO_MESES,
    DEFAULT_PALLET,
    MESES_HISTORIA,
    MESES_SERIE_DISPLAY,
    PROMEDIO2_MESES,
    PROMEDIO3_CAMPO_STATS,
    RATIO_M2_POR_PIEZA_FALLBACK,
)
from .consultas import backorder_detalle, exportar_sap, lista_sugeridos, opciones, pedidos_detalle
from .datos_decision import _a_m2, build_datos_decision  # noqa: F401
from .estadistica import (  # noqa: F401
    calc_confianza,
    calc_es_outlier_venta_dia,
    calc_mad,
    calc_mediana,
    calc_tendencia,
)
from .generar import generar_sugeridos
from .persistencia import _ensure_tables, _now, _tabla_existe  # noqa: F401
from .series import (  # noqa: F401
    _cargar_dias_sin_inventario_tabla,
    _dias_calendario_mes,
    _fusionar_dias_sin_inventario_tabla,
    _meses_contiguos,
    _saldos_fin_mes,
    calc_dias_sin_inventario_por_mes,
)
from .workflow import borrar_excepcion_meses_objetivo, decidir_sugeridos, editar_meses_objetivo, editar_sugerido

router = APIRouter(prefix="/api/engines/sugeridos", tags=["engines:sugeridos"])

# Mismo orden de registro que el módulo original (afecta el matching y el openapi).
router.get("/opciones")(opciones)
router.get("/generar")(generar_sugeridos)
router.get("/lista")(lista_sugeridos)
router.get("/backorder-detalle")(backorder_detalle)
router.get("/pedidos-detalle")(pedidos_detalle)
router.put("/{sugerido_id}/editar")(editar_sugerido)
router.put("/objetivo")(editar_meses_objetivo)
router.delete("/objetivo/excepcion")(borrar_excepcion_meses_objetivo)
router.post("/decidir")(decidir_sugeridos)
router.get("/exportar-sap")(exportar_sap)
