import { apiGet } from './api.js'

// ---------------------------------------------------------------------------
// Datos para la pantalla "Semáforo de Cumplimiento (Lite)" (T11 · waykee 290099).
// Consume /api/semaforo/* (backorders con estado de cumplimiento simulado
// a partir de pedidos_abiertos + lead_time_dias del proveedor).
// ---------------------------------------------------------------------------

export const ORGANIZACIONES = ['GAM', 'GSA', 'SA', 'GAMN']
export const CANALES = ['Mayoreo', 'Menudeo', 'Remates']

export const ESTADOS = [
  { value: 'rojo', label: 'Vencido', dotClass: 'sem--stop' },
  { value: 'amarillo', label: 'Próximo a vencer', dotClass: 'sem--warn' },
  { value: 'verde', label: 'En tiempo', dotClass: 'sem--ok' },
]

export function estadoMeta(value) {
  return ESTADOS.find((e) => e.value === value) ?? ESTADOS[ESTADOS.length - 1]
}

function cleanFilters(filters = {}) {
  const out = {}
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== '' && v !== undefined && v !== null) out[k] = v
  })
  return out
}

export function fetchResumen(filters = {}, umbralDias) {
  return apiGet('/semaforo/resumen', { ...cleanFilters(filters), umbral_dias: umbralDias })
}

export function fetchDetalle(filters = {}, umbralDias, { estado, sort = 'atraso_desc', page = 1, pageSize = 50 } = {}) {
  return apiGet('/semaforo/detalle', {
    ...cleanFilters(filters),
    umbral_dias: umbralDias,
    estado: estado || undefined,
    sort,
    page,
    page_size: pageSize,
  })
}

export function fetchProveedores() {
  return apiGet('/semaforo/proveedores')
}

export function fetchCorredores() {
  return apiGet('/sucursales/corredores')
}

export function fmtMoney(n) {
  if (n === null || n === undefined) return '—'
  return Number(n).toLocaleString('es-MX', { style: 'currency', currency: 'MXN', maximumFractionDigits: 0 })
}

export function fmtNum(n) {
  if (n === null || n === undefined) return '—'
  return Number(n).toLocaleString('es-MX', { maximumFractionDigits: 1 })
}
