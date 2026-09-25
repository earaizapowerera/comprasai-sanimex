import { useCallback, useRef } from 'react'
import SemaforoCobertura from './SemaforoCobertura.jsx'

/** Explorador paginado de pares material · sucursal (scroll infinito dentro
 * del contenedor + botón "Cargar más"). onSelect(row) abre el drill-down. */
export default function CoberturaTable({
  loading, rows, total, pageSize, sort, setSort, activeFilterCount, onClear, loadingMore, onCargarMas, onSelect,
}) {
  // Scroll infinito dentro del contenedor de la tabla (windowing simplificado)
  const scrollRef = useRef(null)
  const onTableScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    if (el.scrollTop + el.clientHeight > el.scrollHeight - 240) onCargarMas()
  }, [onCargarMas])

  return (
    <section className="card pi-table-card">
      <div className="pi-table-card__head">
        <h3 className="h4" style={{ margin: 0 }}>
          Explorador de pares material · sucursal
          {!loading && <span className="badge badge--neutral" style={{ marginLeft: 'var(--space-3)' }}>{total.toLocaleString('es-MX')}</span>}
        </h3>
        <SortSelect sort={sort} setSort={setSort} />
      </div>

      {loading ? (
        <TableSkeleton />
      ) : rows.length === 0 ? (
        <div className="empty">
          <div className="empty__icon">📭</div>
          <p className="h4">Sin resultados</p>
          <p className="footnote">Ajusta o limpia los filtros para ver otros pares material-sucursal.</p>
          {activeFilterCount > 0 && (
            <button type="button" className="btn btn--secondary btn--sm" onClick={onClear}>Limpiar filtros</button>
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
                <tr key={`${r.material_id}__${r.plant}`} className="pi-row" onClick={() => onSelect(r)}>
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
                  <td><SemaforoCobertura estado={r.estado} coberturaMeses={r.cobertura_meses} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {loadingMore && <div className="pi-loading-more footnote text-tertiary">Cargando más filas…</div>}
          {!loadingMore && rows.length < total && (
            <div className="pi-loading-more">
              <button type="button" className="btn btn--ghost btn--sm" onClick={onCargarMas}>Cargar más ({rows.length} de {total})</button>
            </div>
          )}
          {rows.length >= total && total > pageSize && (
            <p className="footnote text-tertiary pi-loading-more">Mostrando los {total.toLocaleString('es-MX')} pares que cumplen el filtro.</p>
          )}
        </div>
      )}
    </section>
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

function fmt(n) {
  if (n === null || n === undefined) return '—'
  return Number(n).toLocaleString('es-MX', { maximumFractionDigits: 1 })
}
