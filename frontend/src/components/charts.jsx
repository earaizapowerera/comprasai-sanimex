import { useId, useMemo, useState } from 'react'

/**
 * Primitivas de gráficas ligeras en SVG puro (sin librería externa) — mantiene
 * el bundle mínimo y se ve consistente con el sistema de diseño (usa variables
 * CSS de design-tokens.css vía currentColor / props de color).
 * Usadas por el Dashboard Ejecutivo (T7); reutilizables por otras pantallas.
 */

// ---------------------------------------------------------------------------
// Sparkline — mini serie de una sola línea, para KPI cards
// ---------------------------------------------------------------------------
export function Sparkline({ values = [], width = 120, height = 36, color = 'var(--accent)' }) {
  const path = useMemo(() => buildPath(values, width, height), [values, width, height])
  if (values.length < 2) return null
  return (
    <svg className="kpi__spark" viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none">
      <path d={path.area} fill={color} opacity="0.12" stroke="none" />
      <path d={path.line} fill="none" stroke={color} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function buildPath(values, width, height) {
  const max = Math.max(...values)
  const min = Math.min(...values)
  const range = max - min || 1
  const step = width / (values.length - 1 || 1)
  const pts = values.map((v, i) => [i * step, height - ((v - min) / range) * (height - 4) - 2])
  const line = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const area = `${line} L${pts[pts.length - 1][0].toFixed(1)},${height} L0,${height} Z`
  return { line, area }
}

// ---------------------------------------------------------------------------
// TrendChart — múltiples series (histórico sólido + forecast punteado),
// con leyenda y tooltip simple al pasar el mouse por un punto.
// serie: { name, color, points: [{ label, value, forecast? }] }
// ---------------------------------------------------------------------------
export function TrendChart({ series = [], height = 220 }) {
  const gid = useId()
  const [hover, setHover] = useState(null)
  const width = 640
  const padTop = 12
  const padBottom = 24
  const padLeft = 4
  const padRight = 4

  const allValues = series.flatMap((s) => s.points.map((p) => p.value))
  const max = Math.max(1, ...allValues)
  const labels = series[0]?.points.map((p) => p.label) ?? []
  const n = labels.length
  const innerW = width - padLeft - padRight
  const innerH = height - padTop - padBottom
  const stepX = n > 1 ? innerW / (n - 1) : 0

  const scaleY = (v) => padTop + innerH - (v / max) * innerH
  const scaleX = (i) => padLeft + i * stepX

  const built = series.map((s) => {
    const solid = s.points.filter((p) => !p.forecast)
    const dashedStart = Math.max(0, solid.length - 1)
    const dashedPoints = s.points.slice(dashedStart)
    const pointsToPath = (pts, offset) =>
      pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${scaleX(offset + i).toFixed(1)},${scaleY(p.value).toFixed(1)}`).join(' ')
    return {
      ...s,
      solidPath: pointsToPath(solid, 0),
      dashedPath: dashedPoints.length > 1 ? pointsToPath(dashedPoints, dashedStart) : null,
    }
  })

  return (
    <div className="trend-chart">
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-label="Venta real vs forecast por canal">
        {/* gridlines horizontales sutiles */}
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line
            key={f}
            x1={padLeft}
            x2={width - padRight}
            y1={scaleY(max * f)}
            y2={scaleY(max * f)}
            stroke="var(--border-subtle)"
            strokeWidth="1"
          />
        ))}
        {built.map((s) => (
          <g key={s.name}>
            <path d={s.solidPath} fill="none" stroke={s.color} strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" />
            {s.dashedPath && (
              <path
                d={s.dashedPath}
                fill="none"
                stroke={s.color}
                strokeWidth="2.25"
                strokeDasharray="5 4"
                strokeLinecap="round"
                opacity="0.75"
              />
            )}
          </g>
        ))}
        {/* puntos invisibles para hover, en la última serie histórica de referencia */}
        {labels.map((label, i) => (
          <rect
            key={`${gid}-${i}`}
            x={scaleX(i) - stepX / 2}
            y={padTop}
            width={Math.max(stepX, 1)}
            height={innerH}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover((h) => (h === i ? null : h))}
          />
        ))}
        {hover !== null && (
          <line x1={scaleX(hover)} x2={scaleX(hover)} y1={padTop} y2={height - padBottom} stroke="var(--border-strong)" strokeWidth="1" />
        )}
      </svg>
      <div className="trend-chart__axis">
        {labels.map((label, i) => (
          <span key={label} className={`trend-chart__tick ${hover === i ? 'trend-chart__tick--active' : ''}`}>
            {label.slice(2).replace('-', '/')}
          </span>
        ))}
      </div>
      <div className="trend-chart__legend">
        {series.map((s) => (
          <span key={s.name} className="trend-chart__legend-item">
            <span className="trend-chart__dot" style={{ background: s.color }} />
            {s.name}
            {hover !== null && s.points[hover] && (
              <strong className="tnum"> · {formatNum(s.points[hover].value)}{s.points[hover].forecast ? ' (proy.)' : ''}</strong>
            )}
          </span>
        ))}
      </div>
    </div>
  )
}

function formatNum(n) {
  return new Intl.NumberFormat('es-MX', { maximumFractionDigits: 0 }).format(n)
}

// ---------------------------------------------------------------------------
// HeatGrid — grid de celdas coloreadas por severidad (mapa de salud)
// cells: [{ key, label, value, sublabel, tone: 'ok'|'warn'|'stop'|'neutral' }]
// ---------------------------------------------------------------------------
export function HeatGrid({ cells = [] }) {
  return (
    <div className="heat-grid">
      {cells.map((c) => (
        <div key={c.key} className={`heat-cell heat-cell--${c.tone}`} title={`${c.label}: ${c.sublabel}`}>
          <span className="heat-cell__label">{c.label}</span>
          <span className="heat-cell__value tnum">{c.value}</span>
          <span className="heat-cell__sublabel">{c.sublabel}</span>
        </div>
      ))}
    </div>
  )
}
