import { apiGet } from './api.js'
import { fetchResumen, fetchPriorizadas, fetchCorredores, calcularForecast } from './inventariosData.js'

/**
 * Fuente de datos para el Dashboard Ejecutivo (T7 · waykee 290095).
 *
 * Patrón "API-first con fallback" (mismo usado por T8/T10): cada sección
 * intenta primero el endpoint de motor "real" (C2/C3) cuando existe; si el
 * router aún no está mergeado (404) o falla la red, cae a un cómputo local
 * derivado de datos REALES (/api/kpis, /api/ventas, /api/materiales,
 * /api/inventarios/cobertura*) — nunca datos inventados. `source` en cada
 * respuesta indica 'api' | 'local' para que la UI marque el origen.
 */

async function tryFetch(path, params) {
  try {
    return await apiGet(path, params)
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------
// KPIs — 100% real, ya expuesto por T3 (/api/kpis)
// ---------------------------------------------------------------------------
export async function fetchKpis(filters = {}) {
  return apiGet('/kpis', filters)
}

// ---------------------------------------------------------------------------
// Venta real vs Forecast por canal
// El motor de forecast de T5 (/api/forecast/{material_id}/{plant_o_canal})
// trabaja a nivel material+canal, no expone un agregado histórico+forecast
// POR CANAL listo para graficar (y /api/tendencias/ganadores tampoco trae
// series de tiempo) — así que aquí NO hay un endpoint "real" razonable que
// intentar primero. Se construye la proyección localmente con
// calcularForecast() (regresión lineal de tendencia sobre los últimos 6
// meses reales de /api/ventas) — el mismo utilitario que ya usa T8 en el
// drill-down de Inventarios. Si T5/T6 exponen a futuro un agregado por
// canal, esta función es el único lugar que hay que tocar.
// ---------------------------------------------------------------------------
export async function fetchVentaVsForecast() {
  const data = await apiGet('/ventas', { group_by: 'canal' })
  const items = data.items ?? []
  const canales = [...new Set(items.map((i) => i.clave))].sort()
  const porCanal = canales.map((canal) => {
    const serie = items
      .filter((i) => i.clave === canal)
      .sort((a, b) => a.anio_mes.localeCompare(b.anio_mes))
    const historico = serie.slice(-6)
    const forecast = calcularForecast(serie, 3)
    const actual = historico[historico.length - 1]?.cantidad_m2 ?? 0
    const previo = historico[historico.length - 2]?.cantidad_m2 ?? 0
    const deltaPct = previo > 0 ? Math.round(((actual - previo) / previo) * 1000) / 10 : null
    return { canal, historico, forecast, deltaPct }
  })

  // Serie "Total" (suma de todos los canales por mes) — la gráfica principal
  // usa esta agregada de una sola escala; el desglose por canal (con montos
  // muy dispares entre Mayoreo y Remates) se muestra aparte en mini-tendencias
  // para no aplastar visualmente los canales chicos contra el eje.
  const porMes = new Map()
  for (const row of items) {
    porMes.set(row.anio_mes, (porMes.get(row.anio_mes) ?? 0) + row.cantidad_m2)
  }
  const serieTotal = [...porMes.entries()]
    .map(([anio_mes, cantidad_m2]) => ({ anio_mes, cantidad_m2 }))
    .sort((a, b) => a.anio_mes.localeCompare(b.anio_mes))
  const total = {
    historico: serieTotal.slice(-6),
    forecast: calcularForecast(serieTotal, 3),
  }

  return { canales: porCanal, total, source: 'local' }
}

// ---------------------------------------------------------------------------
// Top familias y productos ganadores
// Intenta /api/tendencias/ganadores (T5); si no existe, calcula "ganadores"
// comparando importe del último mes vs el penúltimo por material (dato real
// de /api/ventas), unido con /api/materiales para descripción/familia.
// ---------------------------------------------------------------------------
export async function fetchTopGanadores(limit = 6) {
  // El motor real (T5, /api/tendencias/ganadores) responde
  // { ganadores: [{material_id, descripcion, familia, crecimiento_pct, tendencia, ...}], total_ganadores, ... }
  // — normalizamos a la misma forma { items, familias, unit, source } que
  // usa la UI, sin importar cuál rama se haya resuelto.
  const real = await tryFetch('/tendencias/ganadores', { limit })
  if (real && Array.isArray(real.ganadores)) {
    const items = real.ganadores.slice(0, limit).map((g) => ({
      material_id: g.material_id,
      descripcion: g.descripcion,
      familia: g.familia ?? '—',
      crecimiento_pct: g.crecimiento_pct ?? 0,
    }))
    const porFamilia = new Map()
    for (const g of real.ganadores) {
      const acc = porFamilia.get(g.familia ?? '—') ?? { total: 0, n: 0 }
      acc.total += g.crecimiento_pct ?? 0
      acc.n += 1
      porFamilia.set(g.familia ?? '—', acc)
    }
    const familias = [...porFamilia.entries()]
      .map(([familia, { total, n }]) => ({ familia, valor: Math.round((total / n) * 10) / 10 }))
      .sort((a, b) => b.valor - a.valor)
      .slice(0, 5)
    return {
      items,
      familias,
      unit: 'pct',
      source: 'api',
      totalGanadores: real.total_ganadores,
    }
  }

  const [ventas, materialesResp] = await Promise.all([
    apiGet('/ventas', { group_by: 'material' }),
    apiGet('/materiales', { page_size: 500 }),
  ])
  const materiales = new Map((materialesResp.items ?? []).map((m) => [m.material_id, m]))
  const porMaterial = new Map()
  for (const row of ventas.items ?? []) {
    if (!porMaterial.has(row.clave)) porMaterial.set(row.clave, [])
    porMaterial.get(row.clave).push(row)
  }
  const meses = [...new Set((ventas.items ?? []).map((r) => r.anio_mes))].sort()
  const ultimoMes = meses[meses.length - 1]
  const penultimoMes = meses[meses.length - 2]

  const ranked = []
  for (const [materialId, serie] of porMaterial) {
    const actual = serie.find((s) => s.anio_mes === ultimoMes)?.importe ?? 0
    const previo = serie.find((s) => s.anio_mes === penultimoMes)?.importe ?? 0
    if (actual <= 0) continue
    const crecimientoPct = previo > 0 ? ((actual - previo) / previo) * 100 : 100
    const mat = materiales.get(materialId)
    ranked.push({
      material_id: materialId,
      descripcion: mat?.descripcion ?? materialId,
      familia: mat?.familia ?? '—',
      abc: mat?.abc ?? null,
      importe_actual: actual,
      crecimiento_pct: Math.round(crecimientoPct * 10) / 10,
    })
  }
  ranked.sort((a, b) => b.crecimiento_pct - a.crecimiento_pct || b.importe_actual - a.importe_actual)

  // Top familias por importe del mes actual (agregado real, no forecast)
  const porFamilia = new Map()
  for (const r of ranked) {
    porFamilia.set(r.familia, (porFamilia.get(r.familia) ?? 0) + r.importe_actual)
  }
  const familias = [...porFamilia.entries()]
    .map(([familia, importe]) => ({ familia, valor: importe }))
    .sort((a, b) => b.valor - a.valor)
    .slice(0, 5)

  return {
    items: ranked.slice(0, limit),
    familias,
    unit: 'currency',
    source: 'local',
    mesActual: ultimoMes,
    mesPrevio: penultimoMes,
  }
}

// ---------------------------------------------------------------------------
// Alertas — riesgo de quiebre / sobreinventario (real, /api/inventarios/cobertura/priorizadas)
// ---------------------------------------------------------------------------
export async function fetchAlertas(limit = 5) {
  return fetchPriorizadas({}, limit)
}

// ---------------------------------------------------------------------------
// Salud por corredor — real, agrega /api/inventarios/cobertura/resumen por
// cada corredor (de /api/sucursales/corredores).
// ---------------------------------------------------------------------------
export async function fetchSaludCorredores() {
  const corredores = await fetchCorredores()
  const resumenes = await Promise.all(
    corredores.map((corredor) => fetchResumen({ corredor }).then((r) => ({ corredor, ...r }))),
  )
  return resumenes
}
