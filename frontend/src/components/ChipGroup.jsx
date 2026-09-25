/**
 * Grupo de chips de selección única (clic en el activo lo deselecciona vía
 * el onChange del padre). Compartido por Inventarios (prefix "pi") y
 * Semáforo (prefix "sf"): el prefijo solo selecciona las clases CSS de cada
 * pantalla.
 */
export default function ChipGroup({ prefix, label, value, onChange, options, renderLabel }) {
  return (
    <div className={`${prefix}-chipgroup`}>
      <span className="caption text-tertiary">{label}</span>
      <div className={`${prefix}-chipgroup__row`}>
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
