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
