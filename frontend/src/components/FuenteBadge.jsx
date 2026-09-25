// Origen de un dato mostrado al abrir un artículo (waykee 292300): HANA en el
// instante, o el snapshot diario cuando HANA no respondió -- nunca callado.
function hora(iso) {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`)
  return d.toLocaleString('es-MX', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export default function FuenteBadge({ fuente, style }) {
  if (!fuente) return null
  if (fuente.live) {
    return (
      <span className="badge badge--success" style={style} title="Consultado a SAP HANA CAR al abrir">
        ● En vivo HANA · {hora(fuente.consultado_utc)}
      </span>
    )
  }
  return (
    <span
      className="badge badge--warning"
      style={style}
      title={`HANA no respondió (${fuente.motivo_fallback || 'sin detalle'}); se muestra el snapshot diario`}
    >
      Respaldo snapshot · corte {hora(fuente.corte_snapshot_utc)}
    </span>
  )
}
