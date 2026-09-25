import useArticuloVivo from '../hooks/useArticuloVivo.js'
import FuenteBadge from './FuenteBadge.jsx'

const fmt = new Intl.NumberFormat('es-MX', { maximumFractionDigits: 0 })
const fmtM2 = new Intl.NumberFormat('es-MX', { maximumFractionDigits: 1 })

/** Posición del artículo en UN centro, leída de HANA al abrirlo (waykee
 * 292300). Si HANA no responde, el badge avisa que es el snapshot. */
export default function PosicionVivo({ material_id, plant }) {
  const { data, error, loading } = useArticuloVivo(material_id, plant)
  if (loading) return <span className="skeleton" style={{ width: '100%', height: 64 }} />
  if (error) return <p className="footnote text-tertiary">Sin posición actual ({error.message}).</p>
  const p = data.posiciones.find((x) => x.plant === plant) || {}
  const ventaMes = data.venta_mes ? `${fmtM2.format(p.venta_mes_m2 || 0)} m²` : '—'
  return (
    <div className="card card--flat" style={{ padding: 12, marginBottom: 'var(--space-4)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <h4 className="footnote" style={{ fontWeight: 600, margin: 0 }}>Posición actual</h4>
        <FuenteBadge fuente={data.fuente} />
      </div>
      <div className="pi-drawer__metrics">
        <Dato label="Disponible" value={`${fmt.format(p.disponible || 0)} caj`} />
        <Dato label="Tránsito" value={`${fmt.format(p.transito || 0)} caj`} />
        <Dato label="Comprometido" value={`${fmt.format(p.comprometido || 0)} caj`} />
        <Dato label="Disponible neto" value={`${fmt.format(p.disponible_neto || 0)} caj`} />
        <Dato label="OC pendientes" value={`${fmt.format(p.pedidos_compra_pendientes || 0)} caj`} />
        <Dato label="Backorder ventas" value={`${fmt.format(p.backorder_ventas || 0)} caj`} />
        <Dato label={`Venta del mes${data.venta_mes ? ` (${data.venta_mes.anio_mes})` : ''}`} value={ventaMes} />
      </div>
    </div>
  )
}

function Dato({ label, value }) {
  return (
    <div className="pi-mini-metric">
      <span className="caption text-tertiary">{label}</span>
      <span className="footnote tnum" style={{ fontWeight: 600 }}>{value}</span>
    </div>
  )
}
