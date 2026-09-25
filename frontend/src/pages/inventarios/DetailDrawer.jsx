import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { calcularForecast, fetchMaterialDetail, fetchVentasSerie } from '../../lib/inventariosData.js'

// ---------------------------------------------------------------------------
// Drill-down: panel lateral con detalle del material-sucursal
// ---------------------------------------------------------------------------
export default function DetailDrawer({ material_id, plant, onClose }) {
  const [material, setMaterial] = useState(null)
  const [serie, setSerie] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    setMaterial(null)
    setSerie(null)
    setError(null)
    Promise.all([fetchMaterialDetail(material_id), fetchVentasSerie(material_id, plant)])
      .then(([m, s]) => {
        if (!alive) return
        setMaterial(m)
        setSerie(s)
      })
      .catch((err) => alive && setError(err))
    return () => {
      alive = false
    }
  }, [material_id, plant])

  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const forecast = useMemo(() => (serie ? calcularForecast(serie, 3) : []), [serie])

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="pi-drawer" role="dialog" aria-label={`Detalle de ${material_id} en ${plant}`}>
        <div className="pi-drawer__head">
          <div>
            <p className="eyebrow">{plant}</p>
            <h3 className="h3" style={{ margin: 0 }}>{material?.descripcion ?? material_id}</h3>
            <p className="caption tnum text-tertiary">{material_id}</p>
          </div>
          <button type="button" className="app-icon-btn" onClick={onClose} aria-label="Cerrar">✕</button>
        </div>

        {error && <p className="footnote text-tertiary">No se pudo cargar el detalle ({error.message}).</p>}

        {!material && !error ? (
          <div className="pi-drawer__body">
            <span className="skeleton skeleton--text" style={{ width: '60%' }} />
            <span className="skeleton" style={{ width: '100%', height: 160, marginTop: 16 }} />
          </div>
        ) : material && (
          <div className="pi-drawer__body">
            <div className="pi-drawer__metrics">
              <MiniMetric label="Proveedor" value={material.proveedor ?? '—'} />
              <MiniMetric label="Lead time" value={material.lead_time_dias ? `${material.lead_time_dias} días` : '—'} />
              <MiniMetric label="MOQ" value={material.moq_cajas ? `${material.moq_cajas} cajas` : '—'} />
              <MiniMetric label="Cajas / pallet" value={material.cajas_por_pallet ?? '—'} />
              <MiniMetric label="Meses objetivo" value={material.meses_objetivo ? `${material.meses_objetivo} m` : '—'} />
              <MiniMetric label="Precio venta" value={material.precio_venta ? `$${material.precio_venta}` : '—'} />
            </div>

            <div className="pi-drawer__chart-head">
              <h4 className="footnote" style={{ fontWeight: 600, margin: 0 }}>Ventas mensuales (m²) y forecast</h4>
              <span className="layer layer--c2">C2</span>
            </div>
            {serie && serie.length > 0 ? (
              <VentasChart serie={serie} forecast={forecast} />
            ) : (
              <p className="footnote text-tertiary">Sin historial de ventas para este par.</p>
            )}

            <div className="ai-explain" style={{ marginTop: 'var(--space-5)' }}>
              <div className="ai-explain__head">✨ Explicación rápida</div>
              <p className="footnote" style={{ margin: 'var(--space-2) 0 0' }}>
                Forecast estimado con promedio y tendencia lineal de los últimos {Math.min(serie?.length ?? 0, 6)} meses.
                El motor de forecast definitivo (C2) puede ajustar por estacionalidad — ver módulo Sugeridos.
              </p>
            </div>

            <Link
              to={`/sugeridos?material=${encodeURIComponent(material_id)}&plant=${encodeURIComponent(plant)}`}
              className="btn btn--ai btn--lg pi-drawer__cta"
            >
              ✨ Generar sugerido de compra
            </Link>
          </div>
        )}
      </aside>
    </>
  )
}

function MiniMetric({ label, value }) {
  return (
    <div className="pi-mini-metric">
      <span className="caption text-tertiary">{label}</span>
      <span className="footnote tnum" style={{ fontWeight: 600 }}>{value}</span>
    </div>
  )
}

function VentasChart({ serie, forecast }) {
  const all = [...serie, ...forecast]
  const w = 460
  const h = 160
  const padL = 8
  const padR = 8
  const padT = 12
  const padB = 24
  const maxY = Math.max(...all.map((p) => p.cantidad_m2), 1)
  const stepX = (w - padL - padR) / Math.max(all.length - 1, 1)

  const pointX = (i) => padL + i * stepX
  const pointY = (v) => padT + (1 - v / maxY) * (h - padT - padB)

  const realPath = serie.map((p, i) => `${i === 0 ? 'M' : 'L'} ${pointX(i)} ${pointY(p.cantidad_m2)}`).join(' ')
  const forecastPts = [serie[serie.length - 1], ...forecast]
  const forecastPath = forecastPts
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${pointX(serie.length - 1 + i)} ${pointY(p.cantidad_m2)}`)
    .join(' ')

  return (
    <div className="pi-chart">
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} role="img" aria-label="Serie de ventas y forecast">
        <line x1={padL} y1={h - padB} x2={w - padR} y2={h - padB} stroke="var(--border-subtle)" strokeWidth="1" />
        <path d={realPath} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        <path d={forecastPath} fill="none" stroke="var(--ai)" strokeWidth="2" strokeDasharray="4 4" strokeLinejoin="round" strokeLinecap="round" />
        {serie.map((p, i) => (
          <circle key={`r${i}`} cx={pointX(i)} cy={pointY(p.cantidad_m2)} r="2.5" fill="var(--accent)" />
        ))}
        {forecast.map((p, i) => (
          <circle key={`f${i}`} cx={pointX(serie.length + i)} cy={pointY(p.cantidad_m2)} r="2.5" fill="var(--ai)" />
        ))}
      </svg>
      <div className="pi-chart__legend">
        <span className="footnote"><i className="pi-legend-dot pi-legend-dot--real" /> Real</span>
        <span className="footnote"><i className="pi-legend-dot pi-legend-dot--forecast" /> Forecast (C2)</span>
        <span className="caption text-tertiary">{serie[0]?.anio_mes} → {forecast[forecast.length - 1]?.anio_mes}</span>
      </div>
    </div>
  )
}
