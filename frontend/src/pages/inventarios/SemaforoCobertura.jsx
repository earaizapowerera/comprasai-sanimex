import { ESTADOS } from '../../lib/inventariosData.js'

// Semáforo de cobertura (nunca color solo: dot + texto)
export default function SemaforoCobertura({ estado, coberturaMeses, compact }) {
  const meta = ESTADOS.find((e) => e.value === estado) ?? ESTADOS[ESTADOS.length - 1]
  const texto = coberturaMeses === null || coberturaMeses === undefined ? meta.label : `${meta.label} · ${coberturaMeses}m`
  return (
    <span className={`sem ${meta.dotClass}`} style={compact ? { flex: 'none' } : {}}>
      <span className="sem__dot" />
      {texto}
    </span>
  )
}
