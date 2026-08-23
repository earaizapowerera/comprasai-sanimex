// Base de la API: relativa al path donde se sirve la app (import.meta.env.BASE_URL).
// En local: '/api'. Detrás de nginx en /comprasAI: '/comprasAI/api'.
// Nunca usar rutas absolutas empezando en "/api" a secas: se rompen bajo el prefijo.
const BASE = import.meta.env.BASE_URL.replace(/\/$/, '')
export const API_BASE = `${BASE}/api`

export async function apiGet(path, params) {
  const url = new URL(`${API_BASE}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
    })
  }
  const res = await fetch(url.toString().replace(window.location.origin, ''))
  if (!res.ok) throw new Error(`GET ${path} -> HTTP ${res.status}`)
  return res.json()
}

// apiMutate: helper genérico para POST/PUT con body JSON (usado por T9/Sugeridos
// para editar/decidir). Reutiliza el mismo API_BASE relativo que apiGet para que
// funcione igual en dev y detrás de nginx en /comprasAI.
async function apiMutate(method, path, { body, params } = {}) {
  const url = new URL(`${API_BASE}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
    })
  }
  const res = await fetch(url.toString().replace(window.location.origin, ''), {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const data = await res.json()
      detail = data.detail || JSON.stringify(data)
    } catch {
      /* respuesta no-JSON */
    }
    throw new Error(`${method} ${path} -> HTTP ${res.status}: ${detail}`)
  }
  const contentType = res.headers.get('content-type') || ''
  if (contentType.includes('text/csv')) return res.blob()
  return res.json()
}

export const apiPost = (path, opts) => apiMutate('POST', path, opts)
export const apiPut = (path, opts) => apiMutate('PUT', path, opts)

// Namespace de la API del motor de Sugeridos de Compra (T9, C1/C2/C3).
export const api = {
  sugeridos: {
    opciones: () => apiGet('/engines/sugeridos/opciones'),
    generar: (params) => apiGet('/engines/sugeridos/generar', params),
    lista: (params) => apiGet('/engines/sugeridos/lista', params),
    editar: (id, cantidad_final, justificacion) =>
      apiPut(`/engines/sugeridos/${id}/editar`, { body: { cantidad_final, justificacion } }),
    decidir: (ids, accion, aprobado_por) =>
      apiPost('/engines/sugeridos/decidir', { body: { ids, accion, aprobado_por } }),
    exportarSapUrl: () => `${API_BASE}/engines/sugeridos/exportar-sap`,
  },
}
