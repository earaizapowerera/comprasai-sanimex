import { useEffect, useMemo, useRef, useState } from 'react'
import {
  estadoMeta,
  fetchCorredores,
  fetchDetalle,
  fetchProveedores,
  fetchResumen,
  fmtMoney,
  fmtNum,
} from '../lib/semaforoData.js'
import './Semaforo.css'

const PAGE_SIZE = 50
const DEFAULT_UMBRAL = 3

/**
 * Pantalla "Semáforo de Cumplimiento (Lite)" (T11 · waykee 290099).
 * Ruta: /semaforo.
 *
 * Tablero de pedidos abiertos (backorders): tarjetas grandes verde/amarillo/
 * rojo con conteo + monto en riesgo, tabla drill-down por proveedor/sucursal
 * con días de atraso y compras en tránsito ligadas, umbral de "próximo a
 * vencer" configurable en la barra de filtros.
 *
 * Auto-contenida: consume /api/semaforo/* — no requiere props.
 */
export default function Semaforo() {
  const [filters, setFilters] = useState({ organizacion: '', canal: '', corredor: '', proveedor: '' })
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [umbralDias, setUmbralDias] = useState(DEFAULT_UMBRAL)
  const [umbralInput, setUmbralInput] = useState(String(DEFAULT_UMBRAL))
  const [estadoActivo, setEstadoActivo] = useState('')
  const [sort, setSort] = useState('atraso_desc')

  const [corredores, setCorredores] = useState([])
  const [proveedores, setProveedores] = useState([])

  const [resumen, setResumen] = useState(null)
  const [resumenError, setResumenError] = useState(null)

  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loadingTable, setLoadingTable] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [tableError, setTableError] = useState(null)

  // Catálogos (una sola vez)
  useEffect(() => {
    fetchCorredores().then(setCorredores).catch(() => setCorredores([]))
    fetchProveedores().then(setProveedores).catch(() => setProveedores([]))
  }, [])

  // Debounce del buscador
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput), 350)
    return () => clearTimeout(t)
  }, [searchInput])

  // Debounce del umbral (input numérico libre, valida rango 0-30)
  useEffect(() => {
    const n = Number(umbralInput)
    if (umbralInput === '' || Number.isNaN(n) || n < 0 || n > 30) return
    const t = setTimeout(() => setUmbralDias(n), 400)
    return () => clearTimeout(t)
  }, [umbralInput])

  const allFilters = useMemo(() => ({ ...filters, search }), [filters, search])

  // Resumen: 3 tarjetas + monto total + tránsito ligado
  useEffect(() => {
    let alive = true
    setResumenError(null)
    fetchResumen(allFilters, umbralDias)
      .then((r) => alive && setResumen(r))
      .catch((e) => alive && setResumenError(e))
    return () => {
      alive = false
    }
  }, [allFilters, umbralDias])

  // Tabla: reinicia a página 1 cuando cambian filtros, umbral, estado o sort
  useEffect(() => {
    let alive = true
    setLoadingTable(true)
    setTableError(null)
    setPage(1)
    fetchDetalle(allFilters, umbralDias, { estado: estadoActivo, sort, page: 1, pageSize: PAGE_SIZE })
      .then((data) => {
        if (!alive) return
        setRows(data.items ?? [])
        setTotal(data.total ?? 0)
      })
      .catch((e) => alive && setTableError(e))
      .finally(() => alive && setLoadingTable(false))
    return () => {
      alive = false
    }
  }, [allFilters, umbralDias, estadoActivo, sort])

  function cargarMas() {
    if (loadingMore || rows.length >= total) return
    setLoadingMore(true)
    const next = page + 1
    fetchDetalle(allFilters, umbralDias, { estado: estadoActivo, sort, page: next, pageSize: PAGE_SIZE })
      .then((data) => {
        setRows((prev) => [...prev, ...(data.items ?? [])])
        setPage(next)
      })
      .finally(() => setLoadingMore(false))
  }

  const scrollRef = useRef(null)
  function onTableScroll() {
    const el = scrollRef.current
    if (!el) return
    if (el.scrollTop + el.clientHeight > el.scrollHeight - 240) cargarMas()
  }

  const activeFilterCount = useMemo(
    () => Object.values(filters).filter((v) => v).length + (search ? 1 : 0),
    [filters, search],
  )

  function clearFilters() {
    setFilters({ organizacion: '', canal: '', corredor: '', proveedor: '' })
    setSearchInput('')
    setSearch('')
  }

  return (
    <div className="page-semaforo">
      <header className="app-page-header">
        <div>
          <p className="eyebrow">Cumplimiento · Lite</p>
          <h1 className="h1 app-page-header__title">Semáforo de Cumplimiento</h1>
          <p className="body text-secondary" style={{ maxWidth: '68ch', marginTop: 'var(--space-1)' }}>
            ¿Qué pedidos de compra abiertos están vencidos o a punto de vencer, y dónde?
          </p>
        </div>
        <div className="sf-header-actions">
          <span className="layer layer--c1">C1</span>
          <span className="badge badge--neutral" title="Alcance Fase 1: solo pedidos abiertos. El semáforo end-to-end (Requerimiento→Recepción) es F2.">
            Lite
          </span>
        </div>
      </header>

      <FiltersBar
        filters={filters}
        setFilters={setFilters}
        searchInput={searchInput}
        setSearchInput={setSearchInput}
        corredores={corredores}
        proveedores={proveedores}
        umbralInput={umbralInput}
        setUmbralInput={setUmbralInput}
        activeFilterCount={activeFilterCount}
        onClear={clearFilters}
      />

      <SemaforoCards
        resumen={resumen}
        error={resumenError}
        umbralDias={umbralDias}
        estadoActivo={estadoActivo}
        setEstadoActivo={setEstadoActivo}
      />

      <section className="card sf-table-card">
        <div className="sf-table-card__head">
          <h3 className="h4" style={{ margin: 0 }}>
            Pedidos abiertos por proveedor · sucursal
            {!loadingTable && <span className="badge badge--neutral" style={{ marginLeft: 'var(--space-3)' }}>{total.toLocaleString('es-MX')}</span>}
          </h3>
          <div className="sf-table-card__actions">
            {estadoActivo && (
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => setEstadoActivo('')}>
                ✕ Quitar filtro «{estadoMeta(estadoActivo).label}»
              </button>
            )}
            <SortSelect sort={sort} setSort={setSort} />
          </div>
        </div>

        {loadingTable ? (
          <TableSkeleton />
        ) : tableError ? (
          <div className="empty">
            <div className="empty__icon">⚠️</div>
            <p className="h4">No se pudo cargar el detalle</p>
            <p className="footnote">{tableError.message}</p>
          </div>
        ) : rows.length === 0 ? (
          <div className="empty">
            <div className="empty__icon">✅</div>
            <p className="h4">Sin pedidos en este filtro</p>
            <p className="footnote">Ajusta o limpia los filtros para ver otros pedidos abiertos.</p>
            {(activeFilterCount > 0 || estadoActivo) && (
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                onClick={() => {
                  clearFilters()
                  setEstadoActivo('')
                }}
              >
                Limpiar filtros
              </button>
            )}
          </div>
        ) : (
          <div className="sf-table-scroll" ref={scrollRef} onScroll={onTableScroll}>
            <table className="table">
              <thead>
                <tr>
                  <th>Material</th>
                  <th>Proveedor</th>
                  <th>Sucursal</th>
                  <th className="num">Pedido abierto</th>
                  <th className="num">Monto en riesgo</th>
                  <th className="num">Tránsito ligado</th>
                  <th>Fecha esperada</th>
                  <th className="num">Días de atraso</th>
                  <th>Estado</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.material_id}__${r.plant}`}>
                    <td>
                      <p className="footnote" style={{ fontWeight: 600, margin: 0 }}>{r.descripcion}</p>
                      <p className="caption tnum" style={{ margin: 0 }}>{r.material_id} · {r.familia}</p>
                    </td>
                    <td>
                      <p className="footnote" style={{ margin: 0 }}>{r.proveedor ?? '—'}</p>
                      <p className="caption text-tertiary" style={{ margin: 0 }}>Lead time {r.lead_time_dias}d</p>
                    </td>
                    <td>
                      <p className="footnote" style={{ margin: 0 }}>{r.nombre_sucursal}</p>
                      <p className="caption tnum text-tertiary" style={{ margin: 0 }}>{r.plant} · {r.corredor}</p>
                    </td>
                    <td className="num tnum">{fmtNum(r.pedidos_abiertos)}</td>
                    <td className="num tnum" style={{ fontWeight: 600 }}>{fmtMoney(r.monto_riesgo)}</td>
                    <td className="num tnum">{r.transito > 0 ? fmtNum(r.transito) : '—'}</td>
                    <td className="footnote tnum">{r.fecha_esperada}</td>
                    <td className="num tnum" style={{ fontWeight: r.dias_atraso > 0 ? 600 : 400 }}>
                      {r.dias_atraso > 0 ? `${r.dias_atraso} d` : '—'}
                    </td>
                    <td><SemaforoBadge estado={r.estado} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {loadingMore && <div className="sf-loading-more footnote text-tertiary">Cargando más filas…</div>}
            {!loadingMore && rows.length < total && (
              <div className="sf-loading-more">
                <button type="button" className="btn btn--ghost btn--sm" onClick={cargarMas}>Cargar más ({rows.length} de {total})</button>
              </div>
            )}
            {rows.length >= total && total > PAGE_SIZE && (
              <p className="footnote text-tertiary sf-loading-more">Mostrando los {total.toLocaleString('es-MX')} pedidos que cumplen el filtro.</p>
            )}
          </div>
        )}
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Filtros
// ---------------------------------------------------------------------------
function FiltersBar({
  filters, setFilters, searchInput, setSearchInput, corredores, proveedores,
  umbralInput, setUmbralInput, activeFilterCount, onClear,
}) {
  const set = (k) => (v) => setFilters((f) => ({ ...f, [k]: f[k] === v ? '' : v }))

  return (
    <div className="card card--flat sf-filters">
      <div className="input combobox" style={{ maxWidth: 260 }}>
        <input
          className="input"
          placeholder="Buscar SKU o descripción…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          style={{ border: 'none', background: 'transparent', padding: 0, height: 'auto' }}
        />
      </div>

      <SearchableSelect
        label="Proveedor"
        value={filters.proveedor}
        onChange={set('proveedor')}
        options={proveedores.map((p) => ({ value: p, label: p }))}
        placeholder="Todos los proveedores"
      />
      <SearchableSelect
        label="Corredor"
        value={filters.corredor}
        onChange={set('corredor')}
        options={corredores.map((c) => ({ value: c, label: c }))}
        placeholder="Todos los corredores"
      />

      <ChipGroup label="Organización" value={filters.organizacion} onChange={set('organizacion')} options={['GAM', 'GSA', 'SA', 'GAMN']} />
      <ChipGroup label="Canal" value={filters.canal} onChange={set('canal')} options={['Mayoreo', 'Menudeo', 'Remates']} />

      <div className="sf-umbral">
        <span className="caption text-tertiary">Próximo a vencer (días)</span>
        <input
          type="number"
          min={0}
          max={30}
          className="input sf-umbral__input"
          value={umbralInput}
          onChange={(e) => setUmbralInput(e.target.value)}
        />
      </div>

      {activeFilterCount > 0 && (
        <button type="button" className="btn btn--ghost btn--sm" onClick={onClear}>
          ✕ Limpiar ({activeFilterCount})
        </button>
      )}
    </div>
  )
}

function ChipGroup({ label, value, onChange, options }) {
  return (
    <div className="sf-chipgroup">
      <span className="caption text-tertiary">{label}</span>
      <div className="sf-chipgroup__row">
        {options.map((opt) => (
          <button
            key={opt}
            type="button"
            className={`btn btn--sm ${value === opt ? 'btn--primary' : 'btn--secondary'}`}
            onClick={() => onChange(opt)}
          >
            {opt}
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
    <div className="sf-combobox-wrap" ref={ref}>
      <span className="caption text-tertiary">{label}</span>
      <div className="combobox">
        <button
          type="button"
          className="select-trigger sf-select-trigger"
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
// Tarjetas grandes verde/amarillo/rojo (clicables -> filtran la tabla)
// ---------------------------------------------------------------------------
function SemaforoCards({ resumen, error, umbralDias, estadoActivo, setEstadoActivo }) {
  if (error) {
    return (
      <div className="card sf-cards-error">
        <p className="footnote text-tertiary">No se pudo cargar el resumen ({error.message}).</p>
      </div>
    )
  }

  const cards = [
    { estado: 'rojo', title: 'Vencidos', desc: 'Fecha esperada ya pasó', icon: '🔴' },
    { estado: 'amarillo', title: 'Próximos a vencer', desc: `Vencen en ≤ ${umbralDias} días`, icon: '🟡' },
    { estado: 'verde', title: 'En tiempo', desc: `Vencen en > ${umbralDias} días`, icon: '🟢' },
  ]

  return (
    <div className="sf-cards">
      {cards.map((c) => {
        const data = resumen?.[c.estado]
        const active = estadoActivo === c.estado
        return (
          <button
            key={c.estado}
            type="button"
            className={`card sf-card sf-card--${c.estado} ${active ? 'sf-card--active' : ''}`}
            onClick={() => setEstadoActivo(active ? '' : c.estado)}
            aria-pressed={active}
          >
            <div className="sf-card__head">
              <span className={`sem sem--${c.estado === 'rojo' ? 'stop' : c.estado === 'amarillo' ? 'warn' : 'ok'}`}>
                <span className="sem__dot" />
                {c.title}
              </span>
              <span aria-hidden="true" className="sf-card__icon">{c.icon}</span>
            </div>
            {!resumen ? (
              <span className="skeleton skeleton--kpi" style={{ width: '70%' }} />
            ) : (
              <>
                <span className="sf-card__value tnum">{(data?.count ?? 0).toLocaleString('es-MX')}</span>
                <span className="sf-card__sub tnum">{fmtMoney(data?.monto)} en riesgo</span>
              </>
            )}
            <span className="caption text-tertiary">{c.desc}</span>
          </button>
        )
      })}
      <div className="card sf-card sf-card--total">
        <div className="sf-card__head">
          <span className="eyebrow">Resumen global</span>
        </div>
        {!resumen ? (
          <span className="skeleton skeleton--kpi" style={{ width: '70%' }} />
        ) : (
          <>
            <span className="sf-card__value tnum">{fmtMoney(resumen.monto_total_riesgo)}</span>
            <span className="sf-card__sub tnum">{(resumen.total_pedidos ?? 0).toLocaleString('es-MX')} pedidos abiertos</span>
          </>
        )}
        <span className="caption text-tertiary">
          {resumen ? `${fmtNum(resumen.transito_ligado)} unid. ya en tránsito ligadas` : ' '}
        </span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Semáforo (nunca color solo: dot + texto)
// ---------------------------------------------------------------------------
function SemaforoBadge({ estado }) {
  const meta = estadoMeta(estado)
  return (
    <span className={`sem ${meta.dotClass}`}>
      <span className="sem__dot" />
      {meta.label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Orden
// ---------------------------------------------------------------------------
function SortSelect({ sort, setSort }) {
  const options = [
    { value: 'atraso_desc', label: 'Días de atraso (mayor primero)' },
    { value: 'monto_desc', label: 'Monto en riesgo (mayor primero)' },
    { value: 'proveedor', label: 'Proveedor (A-Z)' },
    { value: 'sucursal', label: 'Sucursal (A-Z)' },
  ]
  return (
    <select className="select-trigger" style={{ width: 'auto', minWidth: 240 }} value={sort} onChange={(e) => setSort(e.target.value)}>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
}

// ---------------------------------------------------------------------------
// Skeleton de tabla
// ---------------------------------------------------------------------------
function TableSkeleton() {
  return (
    <div className="sf-table-skeleton">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="sf-table-skeleton__row">
          <span className="skeleton skeleton--text" style={{ width: '28%' }} />
          <span className="skeleton skeleton--text" style={{ width: '18%' }} />
          <span className="skeleton skeleton--text" style={{ width: '18%' }} />
          <span className="skeleton skeleton--text" style={{ width: '14%' }} />
          <span className="skeleton skeleton--text" style={{ width: '14%' }} />
        </div>
      ))}
    </div>
  )
}
