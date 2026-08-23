import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  IconBox, IconCart, IconCoin, IconGauge, IconGrid, IconTrendUp, IconAlertTriangle,
} from '../components/icons.jsx'
import { Sparkline, TrendChart, HeatGrid } from '../components/charts.jsx'
import { fetchKpis, fetchVentaVsForecast, fetchTopGanadores, fetchAlertas, fetchSaludCorredores } from '../lib/dashboardData.js'
import './Dashboard.css'

/**
 * Dashboard Ejecutivo (T7 · waykee 290095).
 * ¿Cómo está el negocio hoy y qué requiere mi atención?
 *
 * Cada sección se carga y falla de forma independiente (Promise por sección,
 * no un solo Promise.all) para que un endpoint caído no tumbe toda la
 * pantalla — muestra su propio estado vacío/error y el resto sigue
 * funcionando. Fuente de datos real: /api/kpis, /api/ventas, /api/materiales,
 * /api/inventarios/cobertura* (T3). Venta-vs-forecast y top ganadores intentan
 * primero el motor C2/C3 (T5) y caen a un cómputo local sobre datos reales si
 * ese endpoint aún no existe — ver lib/dashboardData.js.
 */
export default function Dashboard() {
  const [kpis, setKpis] = useState(null)
  const [kpisError, setKpisError] = useState(null)

  const [trend, setTrend] = useState(null)
  const [trendError, setTrendError] = useState(null)

  const [ganadores, setGanadores] = useState(null)
  const [ganadoresError, setGanadoresError] = useState(null)

  const [alertas, setAlertas] = useState(null)
  const [alertasError, setAlertasError] = useState(null)

  const [salud, setSalud] = useState(null)
  const [saludError, setSaludError] = useState(null)

  useEffect(() => {
    let alive = true
    fetchKpis().then((d) => alive && setKpis(d)).catch((e) => alive && setKpisError(e))
    fetchVentaVsForecast().then((d) => alive && setTrend(d)).catch((e) => alive && setTrendError(e))
    fetchTopGanadores(6).then((d) => alive && setGanadores(d)).catch((e) => alive && setGanadoresError(e))
    fetchAlertas(5).then((d) => alive && setAlertas(d)).catch((e) => alive && setAlertasError(e))
    fetchSaludCorredores().then((d) => alive && setSalud(d)).catch((e) => alive && setSaludError(e))
    return () => {
      alive = false
    }
  }, [])

  const pctUrgentes = kpis?.pares_material_plant
    ? Math.round((kpis.compras_urgentes / kpis.pares_material_plant) * 1000) / 10
    : null

  return (
    <div className="page-dashboard">
      <header className="app-page-header">
        <div>
          <p className="eyebrow">Vista general</p>
          <h1 className="h1 app-page-header__title">Dashboard Ejecutivo</h1>
          <p className="app-page-header__subtitle">¿Cómo está el negocio hoy y qué requiere mi atención?</p>
        </div>
      </header>

      {/* --- KPIs --- */}
      <section className="dash-kpis" aria-label="Indicadores clave">
        {!kpis && !kpisError && Array.from({ length: 5 }).map((_, i) => (
          <div className="card dash-kpi" key={i}>
            <div className="skeleton skeleton--kpi" />
            <div className="skeleton skeleton--text" style={{ width: '40%' }} />
          </div>
        ))}
        {kpisError && (
          <div className="card" style={{ gridColumn: '1 / -1' }}>
            <p className="footnote text-tertiary">No se pudo cargar /api/kpis ({kpisError.message}).</p>
          </div>
        )}
        {kpis && (
          <>
            <KpiCard
              icon={<IconGauge />}
              label="Fill rate"
              value={`${fmt1(kpis.fill_rate_pct)}%`}
              foot={`${kpis.pares_en_quiebre?.toLocaleString('es-MX') ?? 0} pares en quiebre de ${kpis.pares_material_plant?.toLocaleString('es-MX') ?? 0}`}
              tone={kpis.fill_rate_pct >= 90 ? 'up' : 'down'}
            />
            <KpiCard
              icon={<IconBox />}
              label="Cobertura promedio"
              value={`${fmt1(kpis.cobertura_promedio_meses)} m`}
              foot="Meses de inventario disponible sobre demanda promedio"
            />
            <KpiCard
              icon={<IconGrid />}
              label="Días de inventario"
              value={`${fmt1(kpis.dias_inventario_promedio)} d`}
              foot="Cobertura promedio expresada en días"
            />
            <KpiCard
              icon={<IconCoin />}
              label="Valor de inventario"
              value={formatMXNCompact(kpis.valor_inventario_total)}
              foot="Disponible × costo, todo el universo filtrado"
            />
            <KpiCard
              icon={<IconCart />}
              label="Compras urgentes"
              iconTone={pctUrgentes > 15 ? 'danger' : null}
              value={kpis.compras_urgentes?.toLocaleString('es-MX') ?? '—'}
              foot={pctUrgentes !== null ? `${pctUrgentes}% de los pares material-sucursal` : ''}
              tone={pctUrgentes > 15 ? 'down' : 'up'}
              link="/inventarios"
            />
          </>
        )}
      </section>

      {/* --- Venta vs forecast + Alertas --- */}
      <section className="dash-row">
        <div className="card dash-card">
          <div className="dash-card__head">
            <div className="dash-card__title">
              <IconTrendUp />
              <h2 className="h3">Venta real vs forecast por canal</h2>
            </div>
            {trend && (
              <span className={`badge dash-badge-source ${trend.source === 'api' ? 'badge--ai' : 'badge--neutral'}`}>
                {trend.source === 'api' ? 'Motor C2 · ML' : 'Proyección local · SMA'}
              </span>
            )}
          </div>
          {!trend && !trendError && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              <div className="skeleton" style={{ height: 180 }} />
              <div className="skeleton skeleton--text" style={{ width: '50%' }} />
            </div>
          )}
          {trendError && <p className="footnote text-tertiary">No se pudo cargar la tendencia de venta ({trendError.message}).</p>}
          {trend && trend.total?.historico?.length > 0 && (
            <TrendChart
              series={[
                {
                  name: 'Total (todos los canales)',
                  color: 'var(--accent)',
                  points: [
                    ...trend.total.historico.map((p) => ({ label: p.anio_mes, value: p.cantidad_m2, forecast: false })),
                    ...trend.total.forecast.map((p) => ({ label: p.anio_mes, value: p.cantidad_m2, forecast: true })),
                  ],
                },
              ]}
            />
          )}
          {trend && trend.canales?.length > 0 && (
            <div className="dash-canal-grid">
              {trend.canales.map((c) => {
                const values = [...c.historico.map((p) => p.cantidad_m2), ...c.forecast.map((p) => p.cantidad_m2)]
                const actual = c.historico[c.historico.length - 1]?.cantidad_m2
                return (
                  <div className="dash-canal-mini" key={c.canal}>
                    <div className="dash-canal-mini__head">
                      <span className="footnote">{c.canal}</span>
                      {c.deltaPct !== null && (
                        <span className={`caption ${c.deltaPct >= 0 ? 'kpi__delta--up' : 'kpi__delta--down'}`}>
                          {c.deltaPct >= 0 ? '↑' : '↓'} {Math.abs(c.deltaPct)}%
                        </span>
                      )}
                    </div>
                    <Sparkline values={values} color="var(--accent)" />
                    <span className="caption text-tertiary tnum">{actual !== undefined ? formatNum(actual) : '—'} m² · último mes</span>
                  </div>
                )
              })}
            </div>
          )}
          {trend && trend.canales?.length === 0 && (
            <div className="empty">
              <p className="body">Aún no hay datos de venta suficientes para proyectar tendencia.</p>
            </div>
          )}
        </div>

        <div className="card dash-card">
          <div className="dash-card__head">
            <div className="dash-card__title">
              <IconAlertTriangle />
              <h2 className="h3">Alertas activas</h2>
            </div>
          </div>
          {!alertas && !alertasError && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              <div className="skeleton skeleton--text" />
              <div className="skeleton skeleton--text" />
              <div className="skeleton skeleton--text" />
            </div>
          )}
          {alertasError && <p className="footnote text-tertiary">No se pudieron cargar las alertas ({alertasError.message}).</p>}
          {alertas && (
            <div className="dash-alerts">
              {[...(alertas.riesgo_quiebre ?? []).slice(0, 3), ...(alertas.sobreinventario ?? []).slice(0, 2)].map((a, i) => (
                <Link to="/inventarios" className="dash-alert" key={`${a.material_id}-${a.plant}-${i}`}>
                  <span className={`sem ${a.estado === 'exceso' ? 'sem--info' : a.estado === 'quiebre' ? 'sem--stop' : 'sem--warn'}`}>
                    <span className="sem__dot" />
                    {a.estado === 'exceso' ? 'Exceso' : a.estado === 'quiebre' ? 'Quiebre' : 'Riesgo'}
                  </span>
                  <div className="dash-alert__info">
                    <p className="body">{a.descripcion}</p>
                    <p className="caption">{a.nombre_sucursal ?? a.plant} · {a.cobertura_meses ?? '—'} m cobertura</p>
                  </div>
                </Link>
              ))}
              {(alertas.riesgo_quiebre ?? []).length === 0 && (alertas.sobreinventario ?? []).length === 0 && (
                <div className="empty" style={{ padding: 'var(--space-8)' }}>
                  <p className="body">Sin alertas activas — todo dentro de rango objetivo.</p>
                </div>
              )}
              <Link to="/inventarios" className="btn btn--secondary footnote" style={{ marginTop: 'var(--space-2)' }}>
                Ver todo en Inventarios &amp; Cobertura →
              </Link>
            </div>
          )}
        </div>
      </section>

      {/* --- Top familias/ganadores + Salud por corredor --- */}
      <section className="dash-row">
        <div className="card dash-card">
          <div className="dash-card__head">
            <div className="dash-card__title">
              <IconTrendUp />
              <h2 className="h3">Top familias y productos ganadores</h2>
            </div>
            {ganadores && (
              <span className={`badge dash-badge-source ${ganadores.source === 'api' ? 'badge--ai' : 'badge--neutral'}`}>
                {ganadores.source === 'api' ? 'Motor C2 · tendencias' : `${ganadores.mesPrevio ?? ''} → ${ganadores.mesActual ?? ''}`}
              </span>
            )}
          </div>
          {!ganadores && !ganadoresError && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              <div className="skeleton skeleton--text" />
              <div className="skeleton skeleton--text" />
              <div className="skeleton skeleton--text" />
            </div>
          )}
          {ganadoresError && <p className="footnote text-tertiary">No se pudo cargar tendencias ({ganadoresError.message}).</p>}
          {ganadores && (
            <>
              {ganadores.familias?.length > 0 && (
                <div className="dash-familias">
                  {ganadores.familias.map((f) => (
                    <div className="dash-familia-bar" key={f.familia}>
                      <span className="footnote text-secondary">{f.familia}</span>
                      <div className="dash-familia-bar__track">
                        <div
                          className="dash-familia-bar__fill"
                          style={{ width: `${Math.max(4, Math.round((f.valor / ganadores.familias[0].valor) * 100))}%` }}
                        />
                      </div>
                      <span className="footnote tnum">
                        {ganadores.unit === 'currency' ? formatMXNCompact(f.valor) : `+${f.valor}%`}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              <div className="dash-winners">
                {(ganadores.items ?? []).map((it, i) => (
                  <div className="dash-winner" key={it.material_id}>
                    <span className="dash-winner__rank">{i + 1}</span>
                    <div className="dash-winner__info">
                      <p className="body">{it.descripcion}</p>
                      <p className="caption">{it.familia} · {it.material_id}</p>
                    </div>
                    <span className={`dash-winner__growth ${it.crecimiento_pct >= 0 ? 'kpi__delta--up' : 'kpi__delta--down'}`}>
                      {it.crecimiento_pct >= 0 ? '↑' : '↓'} {Math.abs(it.crecimiento_pct)}%
                    </span>
                  </div>
                ))}
                {(ganadores.items ?? []).length === 0 && (
                  <div className="empty" style={{ padding: 'var(--space-8)' }}>
                    <p className="body">Sin suficientes meses de venta para calcular crecimiento.</p>
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        <div className="card dash-card">
          <div className="dash-card__head">
            <div className="dash-card__title">
              <IconGrid />
              <h2 className="h3">Salud por corredor</h2>
            </div>
          </div>
          {!salud && !saludError && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              <div className="skeleton" style={{ height: 120 }} />
            </div>
          )}
          {saludError && <p className="footnote text-tertiary">No se pudo cargar salud por corredor ({saludError.message}).</p>}
          {salud && (
            <HeatGrid
              cells={salud.map((s) => {
                const pctQuiebre = s.total_pares ? (s.en_quiebre / s.total_pares) * 100 : 0
                const tone = pctQuiebre > 15 ? 'stop' : pctQuiebre > 5 ? 'warn' : 'ok'
                return {
                  key: s.corredor,
                  label: s.corredor,
                  value: `${fmt1(pctQuiebre)}%`,
                  sublabel: `${s.en_quiebre ?? 0} en quiebre · ${s.cobertura_media_meses ?? '—'} m prom.`,
                  tone,
                }
              })}
            />
          )}
        </div>
      </section>
    </div>
  )
}

function KpiCard({ icon, label, value, foot, tone, iconTone, link }) {
  const body = (
    <div className="card card--interactive dash-kpi">
      <div className="dash-kpi__head">
        <span className="eyebrow kpi__label">{label}</span>
        <span className={`dash-kpi__icon ${iconTone ? `dash-kpi__icon--${iconTone}` : ''}`}>{icon}</span>
      </div>
      <span className="kpi__value tnum">{value}</span>
      <p className={`footnote text-tertiary dash-kpi__foot ${tone ? `kpi__delta kpi__delta--${tone}` : ''}`}>{foot}</p>
    </div>
  )
  return link ? <Link to={link} style={{ textDecoration: 'none', color: 'inherit' }}>{body}</Link> : body
}

function fmt1(n) {
  if (n === undefined || n === null) return '—'
  return Number(n).toFixed(1)
}

function formatNum(n) {
  return new Intl.NumberFormat('es-MX', { maximumFractionDigits: 0 }).format(n)
}

function formatMXNCompact(n) {
  if (n === undefined || n === null) return '—'
  return new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN', notation: 'compact', maximumFractionDigits: 1 }).format(n)
}
