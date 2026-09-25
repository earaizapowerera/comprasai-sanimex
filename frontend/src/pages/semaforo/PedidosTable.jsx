import { useRef } from 'react'
import { estadoMeta, fmtMoney, fmtNum } from '../../lib/semaforoData.js'

/** Drill-down de pedidos abiertos por proveedor · sucursal (scroll infinito
 * + "Cargar más"). onClearAll limpia filtros Y el estado activo de tarjeta. */
export default function PedidosTable({
  loading, error, rows, total, pageSize, sort, setSort, estadoActivo, setEstadoActivo,
  activeFilterCount, onClearAll, loadingMore, onCargarMas,
}) {
  const scrollRef = useRef(null)
  function onTableScroll() {
    const el = scrollRef.current
    if (!el) return
    if (el.scrollTop + el.clientHeight > el.scrollHeight - 240) onCargarMas()
  }

  return (
    <section className="card sf-table-card">
      <div className="sf-table-card__head">
        <h3 className="h4" style={{ margin: 0 }}>
          Pedidos abiertos por proveedor · sucursal
          {!loading && <span className="badge badge--neutral" style={{ marginLeft: 'var(--space-3)' }}>{total.toLocaleString('es-MX')}</span>}
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

      {loading ? (
        <TableSkeleton />
      ) : error ? (
        <div className="empty">
          <div className="empty__icon">⚠️</div>
          <p className="h4">No se pudo cargar el detalle</p>
          <p className="footnote">{error.message}</p>
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
              onClick={onClearAll}
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
              <button type="button" className="btn btn--ghost btn--sm" onClick={onCargarMas}>Cargar más ({rows.length} de {total})</button>
            </div>
          )}
          {rows.length >= total && total > pageSize && (
            <p className="footnote text-tertiary sf-loading-more">Mostrando los {total.toLocaleString('es-MX')} pedidos que cumplen el filtro.</p>
          )}
        </div>
      )}
    </section>
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
