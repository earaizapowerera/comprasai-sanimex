import SemaforoCobertura from './SemaforoCobertura.jsx'

// ---------------------------------------------------------------------------
// Resumen (KPIs)
// ---------------------------------------------------------------------------
export function ResumenRow({ resumen }) {
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
export function PriorizadasSection({ priorizadas, onSelect }) {
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
              <SemaforoCobertura estado={it.estado} coberturaMeses={it.cobertura_meses} compact />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
