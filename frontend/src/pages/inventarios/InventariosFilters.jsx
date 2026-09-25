import ChipGroup from '../../components/ChipGroup.jsx'
import SearchableSelect from '../../components/SearchableSelect.jsx'
import { ABCS, CANALES, ESTADOS, ORGANIZACIONES } from '../../lib/inventariosData.js'

export default function InventariosFilters({ filters, setFilters, searchInput, setSearchInput, corredores, familias, sucursales, activeFilterCount, onClear }) {
  const set = (k) => (v) => setFilters((f) => ({ ...f, [k]: f[k] === v ? '' : v }))

  return (
    <div className="card card--flat pi-filters">
      <div className="input combobox" style={{ maxWidth: 280 }}>
        <input
          className="input"
          placeholder="Buscar SKU o descripción…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          style={{ border: 'none', background: 'transparent', padding: 0, height: 'auto' }}
        />
      </div>

      <SearchableSelect
        prefix="pi"
        label="Sucursal"
        value={filters.plant}
        onChange={set('plant')}
        options={sucursales.map((s) => ({ value: s.plant, label: `${s.nombre} (${s.plant})` }))}
        placeholder="Todas las sucursales"
      />
      <SearchableSelect
        prefix="pi"
        label="Corredor"
        value={filters.corredor}
        onChange={set('corredor')}
        options={corredores.map((c) => ({ value: c, label: c }))}
        placeholder="Todos los corredores"
      />
      <SearchableSelect
        prefix="pi"
        label="Familia"
        value={filters.familia}
        onChange={set('familia')}
        options={familias.map((f) => ({ value: f, label: f }))}
        placeholder="Todas las familias"
      />

      <ChipGroup prefix="pi" label="Organización" value={filters.organizacion} onChange={set('organizacion')} options={ORGANIZACIONES} />
      <ChipGroup prefix="pi" label="Canal" value={filters.canal} onChange={set('canal')} options={CANALES} />
      <ChipGroup prefix="pi" label="ABC" value={filters.abc} onChange={set('abc')} options={ABCS} />
      <ChipGroup
        prefix="pi"
        label="Estado"
        value={filters.estado}
        onChange={set('estado')}
        options={ESTADOS.map((e) => e.value)}
        renderLabel={(v) => ESTADOS.find((e) => e.value === v)?.label ?? v}
      />

      {activeFilterCount > 0 && (
        <button type="button" className="btn btn--ghost btn--sm" onClick={onClear}>
          ✕ Limpiar ({activeFilterCount})
        </button>
      )}
    </div>
  )
}
