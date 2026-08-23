"""Manifest autodescriptivo para el agente Waykee (ticket T24, waykee
290122): endpoints permitidos, sus parámetros, y la plantilla de deep-links
a pantallas del frontend, pensado para inyectarse en el system prompt del
bot de Waykee que va a consultar esta API y proponer compras.

Requiere `X-Api-Key` válida (ver app/core/agent_scope.py) -- si
COMPRASAI_AGENT_KEY no está configurada, responde 503 (modo agente
deshabilitado)."""

from fastapi import APIRouter, Depends

from app.core.agent_scope import ALLOWED_AGENT_WRITE_PATHS, require_agent_key

router = APIRouter(prefix="/api/agent", tags=["agent"])

# NOTA sobre el frontend (verificado en frontend/src/main.jsx + App.jsx,
# 23-ago-2026): usa react-router `BrowserRouter` con `basename="/comprasAI/"`
# -- NO `HashRouter`. Los deep-links son rutas normales bajo /comprasAI/,
# SIN "#/". (El ticket original asumía "#/<pantalla>"; se corrige aquí a la
# ruta real del router.)
DEEP_LINK_BASE = "https://comprassanimexai.powerera.com/comprasAI"

PANTALLAS = {
    "dashboard": {"path": "/", "descripcion": "KPIs generales, resumen de cobertura y compras urgentes."},
    "inventarios": {"path": "/inventarios", "descripcion": "Explorador de inventario y cobertura por material/sucursal."},
    "sugeridos": {"path": "/sugeridos", "descripcion": "Sugeridos de compra generados (vista Planeador/Gerente: proponer, editar, aprobar/rechazar)."},
    "balanceos": {"path": "/balanceos", "descripcion": "Propuestas de transferencia entre sucursales del mismo corredor (RN-02)."},
    "semaforo": {"path": "/semaforo", "descripcion": "Semáforo de pedidos abiertos en tránsito (verde/amarillo/rojo por atraso)."},
    "chat": {"path": "/chat", "descripcion": "Chat interno del planeador (uso humano; el chat del agente Waykee es independiente de esta pantalla)."},
}


def _endpoint(method: str, path: str, descripcion: str, params: list[dict] | None = None, pantalla: str | None = None, generacion: bool = False) -> dict:
    return {
        "metodo": method,
        "path": path,
        "descripcion": descripcion,
        "parametros": params or [],
        "pantalla_relacionada": PANTALLAS[pantalla]["path"] if pantalla else None,
        "genera_propuesta": generacion,
    }


def _p(nombre: str, descripcion: str, requerido: bool = False) -> dict:
    return {"nombre": nombre, "descripcion": descripcion, "requerido": requerido}


ENDPOINTS_PERMITIDOS = [
    _endpoint("GET", "/api/health", "Healthcheck de la API."),
    # --- Catálogos ---
    _endpoint("GET", "/api/materiales", "Lista materiales (filtros + paginación).", [
        _p("familia", "Filtra por familia de producto"), _p("abc", "Clasificación A|B|C"),
        _p("economico", "1=económico, 0=no económico"), _p("search", "Busca por material_id o descripción"),
        _p("page", "Página (default 1)"), _p("page_size", "Tamaño de página (default 50, máx 500)"),
    ]),
    _endpoint("GET", "/api/materiales/familias", "Lista de familias distintas."),
    _endpoint("GET", "/api/materiales/{material_id}", "Detalle de un material (incluye proveedor, MOQ, cobertura objetivo).", [_p("material_id", "Id del material", True)]),
    _endpoint("GET", "/api/sucursales", "Lista sucursales/plants (filtros + paginación).", [
        _p("organizacion", "GAM|GSA|SA|GAMN"), _p("canal", "Menudeo|Mayoreo|eCommerce|Outlet|Remates"),
        _p("corredor", "Corredor logístico"), _p("es_cedis", "1=CEDIS, 0=sucursal"), _p("search", "Busca por plant o nombre"),
        _p("page", "Página"), _p("page_size", "Tamaño de página"),
    ]),
    _endpoint("GET", "/api/sucursales/corredores", "Lista de corredores distintos."),
    _endpoint("GET", "/api/sucursales/{plant}", "Detalle de una sucursal.", [_p("plant", "Código de plant/sucursal", True)]),
    # --- Ventas / KPIs / Inventario y cobertura ---
    _endpoint("GET", "/api/ventas", "Histórico de ventas mensuales (m2/importe), opcionalmente agrupado.", [
        _p("material_id", ""), _p("plant", ""), _p("canal", ""), _p("anio_mes_desde", "YYYY-MM"), _p("anio_mes_hasta", "YYYY-MM"),
        _p("group_by", "material|plant|canal -- agrupa la serie por esta clave y por mes"), _p("page", ""), _p("page_size", ""),
    ]),
    _endpoint("GET", "/api/kpis", "KPIs agregados: fill_rate, cobertura promedio, valor de inventario, compras urgentes.", [
        _p("organizacion", ""), _p("canal", ""),
    ], pantalla="dashboard"),
    _endpoint("GET", "/api/kpis/compras-urgentes", "Detalle de pares material-sucursal con cobertura por debajo del objetivo.", [
        _p("limit", "Máximo de filas (default 50, máx 500)"),
    ], pantalla="dashboard"),
    _endpoint("GET", "/api/inventarios", "Inventario crudo por par material-sucursal (disponible/tránsito/comprometido).", [
        _p("material_id", ""), _p("plant", ""), _p("organizacion", ""), _p("canal", ""),
        _p("solo_quiebre", "true = solo pares con disponible_neto <= 0"), _p("page", ""), _p("page_size", ""),
    ], pantalla="inventarios"),
    _endpoint("GET", "/api/inventarios/cobertura", "Vista enriquecida de cobertura con semáforo (quiebre/riesgo/ok/exceso/sin_dato).", [
        _p("organizacion", ""), _p("canal", ""), _p("corredor", ""), _p("plant", ""), _p("familia", ""), _p("abc", ""),
        _p("estado", "quiebre|riesgo|ok|exceso|sin_dato"), _p("search", ""),
        _p("sort", "cobertura_asc|cobertura_desc|disponible_neto_asc|disponible_neto_desc|material_id"),
        _p("page", ""), _p("page_size", ""),
    ], pantalla="inventarios"),
    _endpoint("GET", "/api/inventarios/cobertura/resumen", "3 KPIs de resumen sobre el mismo universo filtrado que /cobertura.", [
        _p("organizacion", ""), _p("canal", ""), _p("corredor", ""), _p("plant", ""), _p("familia", ""), _p("abc", ""), _p("search", ""),
    ], pantalla="inventarios"),
    _endpoint("GET", "/api/inventarios/cobertura/priorizadas", "Top de mayor riesgo de quiebre y de mayor sobreinventario.", [
        _p("limit", "default 15, máx 100"), _p("organizacion", ""), _p("canal", ""),
    ], pantalla="inventarios"),
    # --- Semáforo de pedidos abiertos ---
    _endpoint("GET", "/api/semaforo/resumen", "Conteo + monto en riesgo por estado (verde/amarillo/rojo) de pedidos abiertos.", [
        _p("organizacion", ""), _p("canal", ""), _p("corredor", ""), _p("proveedor", ""), _p("search", ""),
        _p("umbral_dias", "Días para considerar amarillo/rojo, default según config"),
    ], pantalla="semaforo"),
    _endpoint("GET", "/api/semaforo/detalle", "Drill-down por proveedor/sucursal con días de atraso y monto en riesgo.", [
        _p("estado", "verde|amarillo|rojo"), _p("organizacion", ""), _p("canal", ""), _p("corredor", ""), _p("proveedor", ""),
        _p("search", ""), _p("umbral_dias", ""), _p("sort", "atraso_desc|monto_desc|proveedor|sucursal"), _p("page", ""), _p("page_size", ""),
    ], pantalla="semaforo"),
    _endpoint("GET", "/api/semaforo/proveedores", "Lista de proveedores con pedidos abiertos.", pantalla="semaforo"),
    # --- Motores C1: sugeridos, balanceos, remates ---
    _endpoint("GET", "/api/engines/status", "Estado del punto de montaje de motores (informativo)."),
    _endpoint("GET", "/api/engines/sugeridos/opciones", "Catálogos (familia/proveedor/corredor) para filtrar sugeridos.", pantalla="sugeridos"),
    _endpoint(
        "GET", "/api/engines/sugeridos/generar",
        "Corre el motor C1+C2+C3 y PERSISTE cada línea sugerida como 'propuesto' (no aprueba ni confirma).",
        [
            _p("familia", ""), _p("proveedor", ""), _p("corredor", ""), _p("plant", ""), _p("abc", ""),
            _p("solo_criticos", "true = solo líneas con cobertura actual = 0"), _p("page", ""), _p("page_size", ""),
        ],
        pantalla="sugeridos", generacion=True,
    ),
    _endpoint("GET", "/api/engines/sugeridos/lista", "Lista los sugeridos ya generados (estado propuesto/aprobado/rechazado).", [
        _p("estado", "propuesto|aprobado|rechazado"),
    ], pantalla="sugeridos"),
    _endpoint(
        "GET", "/api/balanceos/propuestas",
        "Genera/lista propuestas de transferencia entre sucursales del mismo corredor antes que comprar (RN-02).",
        [_p("corredor", ""), _p("limit", "default 25, máx 100")],
        pantalla="balanceos", generacion=True,
    ),
    _endpoint("GET", "/api/balanceos/config", "Costo de traslado por corredor usado por el motor de balanceos (solo lectura).", pantalla="balanceos"),
    _endpoint(
        "GET", "/api/remates/detectar",
        "Detecta candidatos a remate (slow movers / excedente) con precio y ruteo sugeridos según la minuta GAM.",
        [_p("organizacion", "GAM|GSA|SA|GAMN"), _p("dias_min", "Días mínimos sin venta"), _p("limit", "default 150, máx 200")],
        generacion=True,
    ),
    _endpoint("GET", "/api/remates/config", "Escalas de precio, rutas GAM y plazas de excepción del motor de remates (solo lectura)."),
    # --- C2 forecast / tendencias ---
    _endpoint("GET", "/api/tendencias/ganadores", "Productos con tendencia creciente significativa (RN-16). Alias de /api/engines/forecast/tendencias/ganadores.", [
        _p("canal", "Menudeo|Mayoreo|eCommerce"), _p("limit", "default 50, máx 500"),
    ]),
    _endpoint("GET", "/api/forecast/precision", "MAPE de backtest del último trimestre (detalle puntual o resumen muestral). Alias de /api/engines/forecast/precision.", [
        _p("material_id", "Junto con plant_o_canal, da el detalle puntual"), _p("plant_o_canal", ""), _p("sample_size", "default 100"),
    ]),
    _endpoint("GET", "/api/forecast/{material_id}/{plant_o_canal}", "Forecast + tendencia + backtest de un material en un canal/plant. Alias de /api/engines/forecast/{material_id}/{plant_o_canal}.", [
        _p("material_id", "Id del material", True), _p("plant_o_canal", "Canal (Menudeo/Mayoreo/eCommerce) o plant, se resuelve a canal", True),
    ]),
    # --- C3 explicabilidad ---
    _endpoint("GET", "/api/engines/chat_agente/explicar/{material_id}/{plant}", "Explicación en lenguaje natural (RN-12) de por qué se sugiere/no se sugiere comprar.", [
        _p("material_id", "Id del material", True), _p("plant", "Plant/sucursal", True),
    ], pantalla="sugeridos"),
]

ENDPOINTS_BLOQUEADOS = [
    {"metodo": "POST", "path": "/api/engines/sugeridos/decidir", "motivo": "Aprueba/rechaza sugeridos -- decisión humana."},
    {"metodo": "GET", "path": "/api/engines/sugeridos/exportar-sap", "motivo": "Exporta a SAP los sugeridos ya aprobados -- confirma el pedido."},
    {"metodo": "PUT", "path": "/api/engines/sugeridos/{sugerido_id}/editar", "motivo": "Edita manualmente la cantidad de un sugerido -- decisión humana (RN-08)."},
    {"metodo": "PUT", "path": "/api/balanceos/config", "motivo": "Cambia configuración global (costos de traslado) -- no es consulta ni propuesta."},
    {"metodo": "PUT", "path": "/api/remates/config/escalas", "motivo": "Cambia configuración global (escalas de precio de remate)."},
    {"metodo": "PUT", "path": "/api/remates/config/rutas", "motivo": "Cambia configuración global (rutas GAM de remate)."},
    {"metodo": "POST", "path": "/api/chat", "motivo": "Chat interno del planeador (uso humano en la app); el chat del agente vive en Waykee."},
    {"metodo": "POST", "path": "/api/engines/chat_agente/chat", "motivo": "Alias del chat interno del planeador (uso humano en la app)."},
]


@router.get("/manifest", dependencies=[Depends(require_agent_key)])
def manifest() -> dict:
    return {
        "sistema": "ComprasAI Sanimex",
        "descripcion": (
            "El agente puede CONSULTAR (todo GET) y PROPONER compras/transferencias/remates "
            "(endpoints marcados genera_propuesta=true). NUNCA puede confirmar ni aprobar pedidos "
            "-- eso lo hace un humano dentro de la app; para esas acciones, responde con el "
            "deep-link a la pantalla correspondiente en vez de intentar ejecutarlas."
        ),
        "auth": {"header": "X-Api-Key", "nota": "Misma key para todos los endpoints de esta API."},
        "deep_link_base": DEEP_LINK_BASE,
        "pantallas": {nombre: {**info, "url": f"{DEEP_LINK_BASE}{info['path']}"} for nombre, info in PANTALLAS.items()},
        "endpoints_permitidos": ENDPOINTS_PERMITIDOS,
        "endpoints_bloqueados": ENDPOINTS_BLOQUEADOS,
        "rutas_generacion_explicitas": sorted(ALLOWED_AGENT_WRITE_PATHS),
    }
