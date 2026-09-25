import { fmtMoney, fmtNum } from '../../lib/semaforoData.js'

// ---------------------------------------------------------------------------
// Tarjetas grandes verde/amarillo/rojo (clicables -> filtran la tabla)
// ---------------------------------------------------------------------------
export default function SemaforoCards({ resumen, error, umbralDias, estadoActivo, setEstadoActivo }) {
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
