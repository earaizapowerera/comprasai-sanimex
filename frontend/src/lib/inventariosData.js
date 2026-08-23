import { apiGet } from './api.js'

// ---------------------------------------------------------------------------
// Datos para la pantalla "Inventarios & Cobertura" (T8 · waykee 290096).
// Consume las APIs reales de /api/inventarios/cobertura* (T3), sin fallback a
// mock: el motor de cobertura ya existe en el backend.
// ---------------------------------------------------------------------------

export const ORGANIZACIONES = ['GAM', 'GSA', 'SA', 'GAMN']
export const CANALES = ['Mayoreo', 'Menudeo', 'Remates']
export const ABCS = ['A', 'B', 'C']

export const ESTADOS = [
  { value: 'quiebre', label: 'Quiebre', dotClass: 'sem--stop' },
  { value: 'riesgo', label: 'Riesgo', dotClass: 'sem--warn' },
  { value: 'ok', label: 'OK', dotClass: 'sem--ok' },
  { value: 'exceso', label: 'Exceso', dotClass: 'sem--info' },
  { value: 'sin_dato', label: 'Sin dato', dotClass: 'sem--neutral' },
]

export function fetchCobertura(filters = {}, { page = 1, pageSize = 50, sort = 'cobertura_asc' } = {}) {
  return apiGet('/inventarios/cobertura', { ...cleanFilters(filters), page, page_size: pageSize, sort })
}

export function fetchResumen(filters = {}) {
  return apiGet('/inventarios/cobertura/resumen', cleanFilters(filters))
}

export function fetchPriorizadas(filters = {}, limit = 8) {
  const { organizacion, canal } = filters
  return apiGet('/inventarios/cobertura/priorizadas', { organizacion, canal, limit })
}

export function fetchFamilias() {
  return apiGet('/materiales/familias')
}

export function fetchCorredores() {
  return apiGet('/sucursales/corredores')
}

export async function fetchSucursales() {
  const data = await apiGet('/sucursales', { page_size: 100 })
  return data.items ?? []
}

export function fetchMaterialDetail(materialId) {
  return apiGet(`/materiales/${encodeURIComponent(materialId)}`)
}

export async function fetchVentasSerie(materialId, plant) {
  const data = await apiGet('/ventas', { material_id: materialId, plant, page_size: 36 })
  // El backend regresa DESC (más reciente primero); la serie cronológica la
  // queremos ascendente para graficar de izquierda (pasado) a derecha (hoy).
  return [...(data.items ?? [])].reverse()
}

/**
 * Forecast simple client-side: promedio móvil de 3 meses + tendencia lineal
 * de los últimos 6 meses, proyectado 3 meses adelante. Suficiente para el
 * drill-down — el forecast "real" (C2/ML) vive en el motor de T4/T5.
 */
export function calcularForecast(serie, mesesAdelante = 3) {
  if (!serie.length) return []
  const ultimos = serie.slice(-6)
  const n = ultimos.length
  const xs = ultimos.map((_, i) => i)
  const ys = ultimos.map((p) => p.cantidad_m2)
  const xMean = xs.reduce((a, b) => a + b, 0) / n
  const yMean = ys.reduce((a, b) => a + b, 0) / n
  let num = 0
  let den = 0
  xs.forEach((x, i) => {
    num += (x - xMean) * (ys[i] - yMean)
    den += (x - xMean) ** 2
  })
  const pendiente = den === 0 ? 0 : num / den
  const intercepto = yMean - pendiente * xMean

  const ultimoMes = serie[serie.length - 1]?.anio_mes
  const out = []
  for (let i = 1; i <= mesesAdelante; i++) {
    const valor = Math.max(0, intercepto + pendiente * (n - 1 + i))
    out.push({ anio_mes: siguienteMes(ultimoMes, i), cantidad_m2: Math.round(valor * 100) / 100, forecast: true })
  }
  return out
}

function siguienteMes(anioMes, offset) {
  if (!anioMes) return `+${offset}`
  const [anio, mes] = anioMes.split('-').map(Number)
  const total = anio * 12 + (mes - 1) + offset
  const nuevoAnio = Math.floor(total / 12)
  const nuevoMes = (total % 12) + 1
  return `${nuevoAnio}-${String(nuevoMes).padStart(2, '0')}`
}

/**
 * Descarga un CSV con todas las filas que cumplan el filtro actual (recorre
 * páginas de hasta 500 hasta un tope de seguridad de 20 páginas / 10,000
 * filas — más que suficiente para el universo de 2,680 pares).
 */
export async function exportarCoberturaCSV(filters, sort, filename = 'inventarios-cobertura.csv') {
  const pageSize = 500
  const maxPages = 20
  let rows = []
  let page = 1
  // eslint-disable-next-line no-constant-condition
  while (page <= maxPages) {
    const data = await fetchCobertura(filters, { page, pageSize, sort })
    rows = rows.concat(data.items ?? [])
    if (rows.length >= data.total || (data.items ?? []).length < pageSize) break
    page += 1
  }
  if (!rows.length) return 0

  const cols = [
    'material_id', 'descripcion', 'familia', 'abc', 'plant', 'nombre_sucursal',
    'organizacion', 'canal', 'corredor', 'disponible', 'transito', 'comprometido',
    'disponible_neto', 'demanda_prom_mensual', 'meses_objetivo', 'cobertura_meses', 'estado',
  ]
  const escape = (v) => {
    if (v === null || v === undefined) return ''
    const s = String(v)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const csv = [cols.join(','), ...rows.map((r) => cols.map((c) => escape(r[c])).join(','))].join('\n')

  const blob = new Blob([`﻿${csv}`], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
  return rows.length
}

function cleanFilters(filters) {
  const out = {}
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '' && v !== 'todas' && v !== 'todos') out[k] = v
  })
  return out
}
