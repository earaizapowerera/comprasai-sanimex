import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ABCS,
  CANALES,
  ESTADOS,
  ORGANIZACIONES,
  calcularForecast,
  exportarCoberturaCSV,
  fetchCobertura,
  fetchCorredores,
  fetchFamilias,
  fetchMaterialDetail,
  fetchPriorizadas,
  fetchResumen,
  fetchSucursales,
  fetchVentasSerie,
} from '../lib/inventariosData.js'
import './Inventarios.css'

const PAGE_SIZE = 50

/**
 * Pantalla "Inventarios & Cobertura" (T8 · waykee 290096).
 * Ruta: /inventarios.
 *
 * Auto-contenida: obtiene sus propios datos de /api/inventarios/cobertura*
 * (motor real de T3/T4). No requiere props — para integrarla al shell basta
 *   import Inventarios from './pages/Inventarios.jsx'
 *   <Route path="/inventarios" element={<Inventarios />} />
 */
export default function Inventarios() {
  const [filters, setFilters] = useState({
    organizacion: '', canal: '', corredor: '', plant: '', familia: '', abc: '', estado: '', search: '',
  })
  const [searchInput, setSearchInput] = useState('')
  const [sort, setSort] = useState('cobertura_asc')

  const [corredores, setCorredores] = useState([])
  const [familias, setFamilias] = useState([])
  const [sucursales, setSucursales] = useState([])

  const [resumen, setResumen] = useState(null)
  const [priorizadas, setPriorizadas] = useState(null)

  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loadingTable, setLoadingTable] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [exporting, setExporting] = useState(false)

  const [selected, setSelected] = useState(null) // { material_id, plant } para el drawer

  // Catálogos (una sola vez)
  useEffect(() => {
    fetchCorredores().then(setCorredores).catch(() => setCorredores([]))
    fetchFamilias().then(setFamilias).catch(() => setFamilias([]))
    fetchSucursales().then(setSucursales).catch(() => setSucursales([]))
  }, [])

  // Debounce del buscador
  useEffect(() => {
    const t = setTimeout(() => setFilters((f) => ({ ...f, search: searchInput })), 350)
    return () => clearTimeout(t)
  }, [searchInput])

  // Resumen + priorizadas: dependen de filtros "macro" (org/canal/corredor/familia/abc/search)
  useEffect(() => {
    let alive = true
    fetchResumen(filters).then((r) => alive && setResumen(r)).catch(() => alive && setResumen(null))
    fetchPriorizadas(filters, 8).then((r) => alive && setPriorizadas(r)).catch(() => alive && setPriorizadas(null))
    return () => {
      alive = false
    }
  }, [filters.organizacion, filters.canal, filters.corredor, filters.plant, filters.familia, filters.abc, filters.search])

  // Tabla principal: reinicia a página 1 cuando cambian filtros u orden
  useEffect(() => {
    let alive = true
    setLoadingTable(true)
    setPage(1)
    fetchCobertura(filters, { page: 1, pageSize: PAGE_SIZE, sort })
      .then((data) => {
        if (!alive) return
        setRows(data.items ?? [])
        setTotal(data.total ?? 0)
      })
      .finally(() => alive && setLoadingTable(false))
    return () => {
      alive = false
    }
  }, [filters, sort])

  const cargarMas = useCallback(() => {
    if (loadingMore || rows.length >= total) return
    setLoadingMore(true)
    const next = page + 1
    fetchCobertura(filters, { page: next, pageSize: PAGE_SIZE, sort })
      .then((data) => {
        setRows((prev) => [...prev, ...(data.items ?? [])])
        setPage(next)
      })
      .finally(() => setLoadingMore(false))
  }, [filters, sort, page, rows.length, total, loadingMore])

  // Scroll infinito dentro del contenedor de la tabla (windowing simplificado)
  const scrollRef = useRef(null)
  const onTableScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    if (el.scrollTop + el.clientHeight > el.scrollHeight - 240) cargarMas()
  }, [cargarMas])

  const activeFilterCount = useMemo(
    () => Object.values(filters).filter((v) => v).length,
    [filters],
  )

  function clearFilters() {
    setFilters({ organizacion: '', canal: '', corredor: '', plant: '', familia: '', abc: '', estado: '', search: '' })
    setSearchInput('')
  }

  async function onExportCSV() {
    setExporting(true)
    try {
      await exportarCoberturaCSV(filters, sort)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="page-inventarios">
      <header className="app-page-header">
        <div>
          <p className="eyebrow">Inventarios · Explorador</p>
          <h1 className="h1 app-page-header__title">Inventarios &amp; Cobertura</h1>
          <p className="body text-secondary" style={{ maxWidth: '68ch', marginTop: 'var(--space-1)' }}>
            ¿Qué material-sucursal está en riesgo de quiebre y cuál tiene sobreinventario, hoy?
          </p>
        </div>
        <div className="pi-header-actions">
          <span className="layer layer--c1">C1</span>
          <button type="button" className="btn btn--secondary btn--sm" onClick={onExportCSV} disabled={exporting || !total}>
            {exporting ? 'Exportando…' : '⭳ Exportar CSV'}
          </button>
        </div>
      </header>

      <FiltersBar
        filters={filters}
        setFilters={setFilters}
        searchInput={searchInput}
        setSearchInput={setSearchInput}
        corredores={corredores}
        familias={familias}
        sucursales={sucursales}
        activeFilterCount={activeFilterCount}
        onClear={clearFilters}
      />

      <ResumenRow resumen={resumen} />

      <PriorizadasSection
        priorizadas={priorizadas}
        onSelect={(item) => setSelected({ material_id: item.material_id, plant: item.plant })}
      />

      <section className="card pi-table-card">
        <div className="pi-table-card__head">
          <h3 className="h4" style={{ margin: 0 }}>
            Explorador de pares material · sucursal
            {!loadingTable && <span className="badge badge--neutral" style={{ marginLeft: 'var(--space-3)' }}>{total.toLocaleString('es-MX')}</span>}
          </h3>
          <SortSelect sort={sort} setSort={setSort} />
        </div>

        {loadingTable ? (
          <TableSkeleton />
        ) : rows.length === 0 ? (
          <div className="empty">
            <div className="empty__icon">📭</div>
            <p className="h4">Sin resultados</p>
            <p className="footnote">Ajusta o limpia los filtros para ver otros pares material-sucursal.</p>
            {activeFilterCount > 0 && (
              <button type="button" className="btn btn--secondary btn--sm" onClick={clearFilters}>Limpiar filtros</button>
            )}
          </div>
        ) : (
          <div className="pi-table-scroll" ref={scrollRef} onScroll={onTableScroll}>
            <table className="table">
              <thead>
                <tr>
                  <th>Material</th>
                  <th>Sucursal</th>
                  <th>Org · Canal</th>
                  <th className="num">Disponible</th>
                  <th className="num">Tránsito</th>
                  <th className="num">Comprometido</th>
                  <th className="num">Disp. neto</th>
                  <th>Cobertura</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.material_id}__${r.plant}`} className="pi-row" onClick={() => setSelected({ material_id: r.material_id, plant: r.plant })}>
                    <td>
                      <div className="pi-material-cell">
                        <span className={`abc abc--${r.abc.toLowerCase()}`}>{r.abc}</span>
                        <div>
                          <p className="footnote" style={{ fontWeight: 600, margin: 0 }}>{r.descripcion}</p>
                          <p className="caption tnum" style={{ margin: 0 }}>{r.material_id} · {r.familia}</p>
                        </div>
                      </div>
                    </td>
                    <td>
                      <p className="footnote" style={{ margin: 0 }}>{r.nombre_sucursal}</p>
                      <p className="caption tnum" style={{ margin: 0 }}>{r.plant} · {r.corredor}</p>
                    </td>
                    <td><span className="badge badge--neutral">{r.organizacion}</span> <span className="caption">{r.canal}</span></td>
                    <td className="num tnum">{fmt(r.disponible)}</td>
                    <td className="num tnum">{fmt(r.transito)}</td>
                    <td className="num tnum">{fmt(r.comprometido)}</td>
                    <td className="num tnum" style={{ fontWeight: 600 }}>{fmt(r.disponible_neto)}</td>
                    <td><Semaforo estado={r.estado} coberturaMeses={r.cobertura_meses} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {loadingMore && <div className="pi-loading-more footnote text-tertiary">Cargando más filas…</div>}
            {!loadingMore && rows.length < total && (
              <div className="pi-loading-more">
                <button type="button" className="btn btn--ghost btn--sm" onClick={cargarMas}>Cargar más ({rows.length} de {total})</button>
              </div>
            )}
            {rows.length >= total && total > PAGE_SIZE && (
              <p className="footnote text-tertiary pi-loading-more">Mostrando los {total.toLocaleString('es-MX')} pares que cumplen el filtro.</p>
            )}
          </div>
        )}
      </section>

      {selected && (
        <DetailDrawer
          material_id={selected.material_id}
          plant={selected.plant}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Filtros
// ---------------------------------------------------------------------------
function FiltersBar({ filters, setFilters, searchInput, setSearchInput, corredores, familias, sucursales, activeFilterCount, onClear }) {
  const set = (k) => (v) => setFilters((f) => ({ ...f, [k]: f[k] === v ? '' : v }))

  return (
    <div className="card card--flat pi-filters">
      <div className="input combobox" style={{ maxWidth: 280 }}>
        <input
          className="input"
          placeholder="Buscar SKU o descripción…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          style={{ border: 'none', background: 'transparent', padding: 0, height: 'auto' }}
        />
      </div>

      <SearchableSelect
        label="Sucursal"
        value={filters.plant}
        onChange={set('plant')}
        options={sucursales.map((s) => ({ value: s.plant, label: `${s.nombre} (${s.plant})` }))}
        placeholder="Todas las sucursales"
      />
      <SearchableSelect
        label="Corredor"
        value={filters.corredor}
        onChange={set('corredor')}
        options={corredores.map((c) => ({ value: c, label: c }))}
        placeholder="Todos los corredores"
      />
      <SearchableSelect
        label="Familia"
        value={filters.familia}
        onChange={set('familia')}
        options={familias.map((f) => ({ value: f, label: f }))}
        placeholder="Todas las familias"
      />

      <ChipGroup label="Organización" value={filters.organizacion} onChange={set('organizacion')} options={ORGANIZACIONES} />
      <ChipGroup label="Canal" value={filters.canal} onChange={set('canal')} options={CANALES} />
      <ChipGroup label="ABC" value={filters.abc} onChange={set('abc')} options={ABCS} />
      <ChipGroup
        label="Estado"
        value={filters.estado}
        onChange={set('estado')}
        options={ESTADOS.map((e) => e.value)}
        renderLabel={(v) => ESTADOS.find((e) => e.value === v)?.label ?? v}
      />

      {activeFilterCount > 0 && (
        <button type="button" className="btn btn--ghost btn--sm" onClick={onClear}>
          ✕ Limpiar ({activeFilterCount})
        </button>
      )}
    </div>
  )
}

function ChipGroup({ label, value, onChange, options, renderLabel }) {
  return (
    <div className="pi-chipgroup">
      <span className="caption text-tertiary">{label}</span>
      <div className="pi-chipgroup__row">
        {options.map((opt) => (
          <button
            key={opt}
            type="button"
            className={`btn btn--sm ${value === opt ? 'btn--primary' : 'btn--secondary'}`}
            onClick={() => onChange(opt)}
          >
            {renderLabel ? renderLabel(opt) : opt}
          </button>
        ))}
      </div>
    </div>
  )
}

function SearchableSelect({ label, value, onChange, options, placeholder }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const ref = useRef(null)

  useEffect(() => {
    function onDocClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  const filtered = useMemo(
    () => options.filter((o) => o.label.toLowerCase().includes(query.toLowerCase())),
    [options, query],
  )
  const selectedLabel = options.find((o) => o.value === value)?.label

  return (
    <div className="pi-combobox-wrap" ref={ref}>
      <span className="caption text-tertiary">{label}</span>
      <div className="combobox">
        <button
          type="button"
          className="select-trigger pi-select-trigger"
          onClick={() => setOpen((v) => !v)}
          aria-haspopup="listbox"
          aria-expanded={open}
        >
          <span className={selectedLabel ? '' : 'text-tertiary'}>{selectedLabel || placeholder}</span>
          <span aria-hidden="true">⌄</span>
        </button>
        {open && (
          <div className="combobox__panel">
            <input
              autoFocus
              className="input"
              style={{ marginBottom: 'var(--space-2)' }}
              placeholder="Filtrar…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {value && (
              <div
                className="combobox__option"
                onClick={() => {
                  onChange('')
                  setOpen(false)
                  setQuery('')
                }}
              >
                <em>Limpiar selección</em>
              </div>
            )}
            {filtered.length === 0 ? (
              <div className="combobox__empty">Sin coincidencias</div>
            ) : (
              filtered.slice(0, 200).map((o) => (
                <div
                  key={o.value}
                  className="combobox__option"
                  aria-selected={o.value === value}
                  onClick={() => {
                    onChange(o.value)
                    setOpen(false)
                    setQuery('')
                  }}
                >
                  {o.label}
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Resumen (KPIs)
// ---------------------------------------------------------------------------
function ResumenRow({ resumen }) {
  return (
    <div className="card pi-kpis">
      {!resumen ? (
        <>
          <div className="skeleton skeleton--kpi" />
          <div className="skeleton skeleton--kpi" />
          <div className="skeleton skeleton--kpi" />
          <div className="skeleton skeleton--kpi" />
        </>
      ) : (
        <>
          <Kpi label="Pares material-sucursal" value={resumen.total_pares?.toLocaleString('es-MX') ?? '—'} />
          <Kpi label="En quiebre" value={resumen.en_quiebre?.toLocaleString('es-MX') ?? '—'} tone="danger" />
          <Kpi label="En exceso" value={resumen.en_exceso?.toLocaleString('es-MX') ?? '—'} tone="accent" />
          <Kpi label="Cobertura media" value={`${resumen.cobertura_media_meses ?? '—'} m`} />
        </>
      )}
    </div>
  )
}

function Kpi({ label, value, tone }) {
  const toneClass = tone === 'danger' ? 'text-danger' : tone === 'accent' ? '' : ''
  return (
    <div className="kpi">
      <span className="eyebrow kpi__label">{label}</span>
      <span className={`kpi__value tnum ${toneClass}`} style={tone === 'accent' ? { color: 'var(--accent-soft-text)' } : {}}>{value}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Listas priorizadas
// ---------------------------------------------------------------------------
function PriorizadasSection({ priorizadas, onSelect }) {
  return (
    <div className="pi-priorizadas">
      <PriorityList
        title="⚠ Riesgo de quiebre"
        subtitle="Menor cobertura primero"
        items={priorizadas?.riesgo_quiebre}
        onSelect={onSelect}
        emptyText="Ningún par en riesgo con el filtro actual."
      />
      <PriorityList
        title="📦 Sobreinventario"
        subtitle="Mayor cobertura primero"
        items={priorizadas?.sobreinventario}
        onSelect={onSelect}
        emptyText="Sin excedentes detectados con el filtro actual."
      />
    </div>
  )
}

function PriorityList({ title, subtitle, items, onSelect, emptyText }) {
  return (
    <section className="card pi-priority-card">
      <div className="pi-priority-card__head">
        <h3 className="h4" style={{ margin: 0 }}>{title}</h3>
        <span className="caption text-tertiary">{subtitle}</span>
      </div>
      {items === undefined ? (
        <div className="pi-priority-list">
          {[0, 1, 2].map((i) => <span key={i} className="skeleton skeleton--text" style={{ height: 40 }} />)}
        </div>
      ) : items.length === 0 ? (
        <p className="footnote text-tertiary" style={{ padding: 'var(--space-4) 0' }}>{emptyText}</p>
      ) : (
        <ul className="pi-priority-list">
          {items.map((it) => (
            <li key={`${it.material_id}__${it.plant}`} className="pi-priority-item" onClick={() => onSelect(it)}>
              <span className={`abc abc--${it.abc.toLowerCase()}`}>{it.abc}</span>
              <div className="pi-priority-item__info">
                <p className="footnote" style={{ margin: 0, fontWeight: 600 }}>{it.descripcion}</p>
                <p className="caption tnum" style={{ margin: 0 }}>{it.material_id} · {it.nombre_sucursal}</p>
              </div>
              <Semaforo estado={it.estado} coberturaMeses={it.cobertura_meses} compact />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Semáforo (nunca color solo: dot + texto)
// ---------------------------------------------------------------------------
function Semaforo({ estado, coberturaMeses, compact }) {
  const meta = ESTADOS.find((e) => e.value === estado) ?? ESTADOS[ESTADOS.length - 1]
  const texto = coberturaMeses === null || coberturaMeses === undefined ? meta.label : `${meta.label} · ${coberturaMeses}m`
  return (
    <span className={`sem ${meta.dotClass}`} style={compact ? { flex: 'none' } : {}}>
      <span className="sem__dot" />
      {texto}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Orden
// ---------------------------------------------------------------------------
function SortSelect({ sort, setSort }) {
  const options = [
    { value: 'cobertura_asc', label: 'Cobertura ↑ (menor primero)' },
    { value: 'cobertura_desc', label: 'Cobertura ↓ (mayor primero)' },
    { value: 'disponible_neto_asc', label: 'Disp. neto ↑' },
    { value: 'disponible_neto_desc', label: 'Disp. neto ↓' },
    { value: 'material_id', label: 'Material (A-Z)' },
  ]
  return (
    <select className="select-trigger" style={{ width: 'auto', minWidth: 220 }} value={sort} onChange={(e) => setSort(e.target.value)}>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
}

// ---------------------------------------------------------------------------
// Skeleton de tabla
// ---------------------------------------------------------------------------
function TableSkeleton() {
  return (
    <div className="pi-table-skeleton">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="pi-table-skeleton__row">
          <span className="skeleton skeleton--text" style={{ width: '30%' }} />
          <span className="skeleton skeleton--text" style={{ width: '20%' }} />
          <span className="skeleton skeleton--text" style={{ width: '15%' }} />
          <span className="skeleton skeleton--text" style={{ width: '15%' }} />
          <span className="skeleton skeleton--text" style={{ width: '15%' }} />
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Drill-down: panel lateral con detalle del material-sucursal
// ---------------------------------------------------------------------------
function DetailDrawer({ material_id, plant, onClose }) {
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

function fmt(n) {
  if (n === null || n === undefined) return '—'
  return Number(n).toLocaleString('es-MX', { maximumFractionDigits: 1 })
}
