import { useEffect, useMemo, useRef, useState } from 'react'

/**
 * Dropdown con filtro de texto (regla UX: >5 opciones siempre searchable).
 * options: [{ value, label }]. Compartido por Inventarios (prefix "pi") y
 * Semáforo (prefix "sf"): el prefijo solo selecciona las clases CSS.
 */
export default function SearchableSelect({ prefix, label, value, onChange, options, placeholder }) {
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
    <div className={`${prefix}-combobox-wrap`} ref={ref}>
      <span className="caption text-tertiary">{label}</span>
      <div className="combobox">
        <button
          type="button"
          className={`select-trigger ${prefix}-select-trigger`}
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
