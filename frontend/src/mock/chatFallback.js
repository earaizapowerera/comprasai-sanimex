/**
 * Respuestas locales grounded en datos reales (T3 · /api/*) para cuando el
 * agente conversacional (T6, capa C3, POST /api/chat con streaming SSE) aún
 * no está disponible. useChatStream cae aquí automáticamente si el fetch al
 * endpoint del agente falla, no responde, o no viene con stream.
 *
 * Importante: estas respuestas son consultas deterministas (capa C1) contra
 * la API real — no simulan razonamiento del agente. Se etiquetan con layer
 * 'C1' (nunca 'C3') para no aparentar ser algo que no son; cuando T6 publique
 * el endpoint real, estas respuestas se sustituyen automáticamente sin tocar
 * este componente.
 */
import { apiGet } from '../lib/api.js'

const GREETING =
  'Aún estoy conectando mi motor conversacional completo (capa C3), pero ya puedo ' +
  'consultar los datos reales de inventario, ventas y cobertura por ti. Prueba una de ' +
  'las sugerencias de abajo o pregúntame por quiebres, excesos, top de ventas o un SKU en particular.'

export async function answerLocally(question) {
  const q = (question || '').toLowerCase()

  if (/quiebre|falt|urgente|debo comprar|qué comprar|que comprar|comprar/.test(q)) {
    return answerComprasUrgentes()
  }
  if (/exceso|sobreinvent|sobrestock|sobre stock/.test(q)) {
    return answerExcesos()
  }
  if (/gana|top|más vend|mas vend|mejor vend/.test(q)) {
    return answerTopVentas()
  }
  if (/hola|ayuda|qué puedes|que puedes|quien eres|quién eres/.test(q)) {
    return { text: GREETING, table: null, sources: [], layer: null }
  }
  return answerExplicacion(question)
}

async function answerComprasUrgentes() {
  try {
    const data = await apiGet('/kpis/compras-urgentes', { limit: 6 })
    const items = data.items ?? []
    if (!items.length) {
      return {
        text: 'No encuentro pares material-sucursal con cobertura por debajo del objetivo en este momento. El motor de compras (C1) no detecta urgencias.',
        table: null,
        sources: [{ label: 'Motor de cobertura vs. objetivo · datos en vivo', layer: 'C1' }],
        layer: 'C1',
      }
    }
    const table = {
      columns: ['SKU', 'Descripción', 'Sucursal', 'Cobertura (m)', 'Objetivo (m)'],
      rows: items.map((r) => [
        r.material_id,
        truncate(r.descripcion, 28),
        r.nombre_sucursal,
        r.cobertura_actual_meses?.toFixed?.(1) ?? r.cobertura_actual_meses,
        r.meses_objetivo?.toFixed?.(1) ?? r.meses_objetivo,
      ]),
    }
    return {
      text: `Encontré ${data.count} pares material-sucursal por debajo de su cobertura objetivo. Estos son los más urgentes:`,
      table,
      sources: [{ label: 'Cobertura actual vs. objetivo · inventario + demanda últimos 3 meses', layer: 'C1' }],
      layer: 'C1',
    }
  } catch {
    return fallbackError()
  }
}

async function answerExcesos() {
  try {
    const data = await apiGet('/inventarios', { page_size: 500 })
    const items = data.items ?? []
    const conDemanda = items.filter((r) => r.disponible_neto > 0)
    const ranked = conDemanda
      .map((r) => ({
        ...r,
        objetivo: r.meses_objetivo ?? 2,
      }))
      .sort((a, b) => (b.disponible_neto ?? 0) - (a.disponible_neto ?? 0))
      .slice(0, 6)
    if (!ranked.length) return fallbackError()
    const table = {
      columns: ['SKU', 'Descripción', 'Sucursal', 'Disp. neto (m²)'],
      rows: ranked.map((r) => [r.material_id, truncate(r.descripcion, 28), r.nombre_sucursal, r.disponible_neto]),
    }
    return {
      text:
        'Estos son los pares material-sucursal con mayor disponible neto (candidatos a revisar por posible exceso; ' +
        'el cálculo exacto de exceso vs. cobertura objetivo lo entrega el motor de balanceos en /balanceos):',
      table,
      sources: [{ label: 'Inventario disponible en tiempo real', layer: 'C1' }],
      layer: 'C1',
    }
  } catch {
    return fallbackError()
  }
}

async function answerTopVentas() {
  try {
    const data = await apiGet('/ventas', { group_by: 'material', page_size: 2000 })
    const rows = data.items ?? []
    const totals = new Map()
    for (const r of rows) {
      totals.set(r.clave, (totals.get(r.clave) ?? 0) + (r.importe ?? 0))
    }
    const top = [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5)
    if (!top.length) return fallbackError()
    const table = {
      columns: ['SKU', 'Ventas acumuladas'],
      rows: top.map(([sku, importe]) => [sku, formatMXN(importe)]),
    }
    return {
      text: 'Estos son los SKU con mayor venta acumulada en el histórico disponible:',
      table,
      sources: [{ label: 'Ventas mensuales agregadas por material', layer: 'C1' }],
      layer: 'C1',
    }
  } catch {
    return fallbackError()
  }
}

async function answerExplicacion(question) {
  const skuMatch = (question || '').match(/[A-Z]{2,}[- ]?[A-Z0-9]{2,}/)
  if (skuMatch) {
    try {
      const data = await apiGet('/materiales', { search: skuMatch[0], page_size: 1 })
      const material = data.items?.[0]
      if (material) {
        return {
          text:
            `${material.descripcion} (${material.material_id}, familia ${material.familia}, clase ${material.abc}). ` +
            'La explicación completa del sugerido (demanda, cobertura, MOQ y por qué se recomienda comprar) la genera ' +
            'el motor conversacional (C3) — está terminando de integrarse. Con estos datos ya puedo ubicar el SKU; ' +
            'pregúntame por su cobertura o revísalo en Sugeridos de Compra.',
          table: null,
          sources: [{ label: `Catálogo de materiales · ${material.material_id}`, layer: 'C1' }],
          layer: 'C1',
        }
      }
    } catch {
      /* sigue al mensaje genérico */
    }
  }
  return {
    text:
      'Mi motor de explicabilidad completo (capa C3) está terminando de integrarse, así que aún no puedo razonar ' +
      'libremente sobre cualquier pregunta. Sí puedo consultar datos reales: pregúntame por quiebres, excesos, ' +
      'top de ventas, o el nombre/SKU de un material.',
    table: null,
    sources: [],
    layer: null,
  }
}

function fallbackError() {
  return {
    text: 'No pude consultar los datos en este momento. Intenta de nuevo en unos segundos.',
    table: null,
    sources: [],
    layer: null,
  }
}

function truncate(s, n) {
  if (!s) return s
  return s.length > n ? `${s.slice(0, n - 1)}…` : s
}

function formatMXN(n) {
  return new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN', maximumFractionDigits: 0 }).format(
    n || 0,
  )
}
