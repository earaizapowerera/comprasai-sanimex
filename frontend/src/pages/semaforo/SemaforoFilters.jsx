import ChipGroup from '../../components/ChipGroup.jsx'
import SearchableSelect from '../../components/SearchableSelect.jsx'

export default function SemaforoFilters({
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
        prefix="sf"
        label="Proveedor"
        value={filters.proveedor}
        onChange={set('proveedor')}
        options={proveedores.map((p) => ({ value: p, label: p }))}
        placeholder="Todos los proveedores"
      />
      <SearchableSelect
        prefix="sf"
        label="Corredor"
        value={filters.corredor}
        onChange={set('corredor')}
        options={corredores.map((c) => ({ value: c, label: c }))}
        placeholder="Todos los corredores"
      />

      <ChipGroup prefix="sf" label="Organización" value={filters.organizacion} onChange={set('organizacion')} options={['GAM', 'GSA', 'SA', 'GAMN']} />
      <ChipGroup prefix="sf" label="Canal" value={filters.canal} onChange={set('canal')} options={['Mayoreo', 'Menudeo', 'Remates']} />

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
