import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiGet } from '../lib/api.js'

/**
 * Dashboard Ejecutivo — versión provisional.
 * La pantalla completa (KPIs + sparklines, gráfica venta vs forecast, banda de
 * atención IA, cobertura por corredor) es entregable de T7 (waykee 290095).
 * Esta versión consume /api/kpis real (T3) para no dejar el home vacío
 * mientras T7 construye la pantalla definitiva — reemplazar sin miedo.
 */
export default function Dashboard() {
  const [kpis, setKpis] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    apiGet('/kpis')
      .then((data) => !cancelled && setKpis(data))
      .catch((err) => !cancelled && setError(err))
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <>
      <header className="app-page-header">
        <h1 className="h1 app-page-header__title">Dashboard Ejecutivo</h1>
        <p className="app-page-header__subtitle">¿Cómo está el negocio hoy y qué requiere mi atención?</p>
      </header>

      <div className="card" style={{ display: 'grid', gap: 'var(--space-5)', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        {!kpis && !error && (
          <>
            <div className="skeleton skeleton--kpi" />
            <div className="skeleton skeleton--kpi" />
            <div className="skeleton skeleton--kpi" />
            <div className="skeleton skeleton--kpi" />
          </>
        )}
        {error && (
          <p className="footnote text-tertiary">
            No se pudo cargar /api/kpis todavía ({error.message}). El motor completo llega con T7.
          </p>
        )}
        {kpis && (
          <>
            <Kpi label="Fill rate" value={`${kpis.fill_rate_pct?.toFixed?.(1) ?? '—'}%`} />
            <Kpi label="Cobertura promedio" value={`${kpis.cobertura_promedio_meses?.toFixed?.(1) ?? '—'} m`} />
            <Kpi label="Valor de inventario" value={formatMXN(kpis.valor_inventario_total)} />
            <Kpi label="Compras urgentes" value={kpis.compras_urgentes ?? '—'} />
          </>
        )}
      </div>

      <div className="card" style={{ marginTop: 'var(--space-5)' }}>
        <p className="footnote text-tertiary" style={{ margin: 0 }}>
          Vista provisional — la pantalla definitiva del Dashboard (sparklines, banda de atención IA,
          cobertura por corredor, top movimientos) es entregable de T7. Mientras tanto, prueba el{' '}
          <Link to="/chat">Chat del Planeador ✨</Link>.
        </p>
      </div>
    </>
  )
}

function Kpi({ label, value }) {
  return (
    <div className="kpi">
      <span className="eyebrow kpi__label">{label}</span>
      <span className="kpi__value tnum">{value}</span>
    </div>
  )
}

function formatMXN(n) {
  if (n === undefined || n === null) return '—'
  return new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN', maximumFractionDigits: 0 }).format(n)
}
