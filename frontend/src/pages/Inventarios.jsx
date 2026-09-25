import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  exportarCoberturaCSV,
  fetchCobertura,
  fetchCorredores,
  fetchFamilias,
  fetchPriorizadas,
  fetchResumen,
  fetchSucursales,
} from '../lib/inventariosData.js'
import CoberturaTable from './inventarios/CoberturaTable.jsx'
import DetailDrawer from './inventarios/DetailDrawer.jsx'
import InventariosFilters from './inventarios/InventariosFilters.jsx'
import { PriorizadasSection, ResumenRow } from './inventarios/ResumenPanels.jsx'
import './Inventarios.css'

const PAGE_SIZE = 50

/**
 * Pantalla "Inventarios & Cobertura" (T8 · waykee 290096).
 * Ruta: /inventarios.
 *
 * Subcomponentes en ./inventarios/ (filtros, KPIs/priorizadas, tabla, drawer).
 *
 * Auto-contenida: obtiene sus propios datos de /api/inventarios/cobertura*
 * (motor real de T3/T4). No requiere props — para integrarla al shell basta
 *   import Inventarios from './pages/Inventarios.jsx'
 *   <Route path="/inventarios" element={<Inventarios />} />
 */
export default function Inventarios() {
  const [filters, setFilters] = useState({
    organizacion: '', canal: '', corredor: '', plant: '', familia: '', abc: '', estado: '', search: '',
  })
  const [searchInput, setSearchInput] = useState('')
  const [sort, setSort] = useState('cobertura_asc')

  const [corredores, setCorredores] = useState([])
  const [familias, setFamilias] = useState([])
  const [sucursales, setSucursales] = useState([])

  const [resumen, setResumen] = useState(null)
  const [priorizadas, setPriorizadas] = useState(null)

  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loadingTable, setLoadingTable] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [exporting, setExporting] = useState(false)

  const [selected, setSelected] = useState(null) // { material_id, plant } para el drawer

  // Catálogos (una sola vez)
  useEffect(() => {
    fetchCorredores().then(setCorredores).catch(() => setCorredores([]))
    fetchFamilias().then(setFamilias).catch(() => setFamilias([]))
    fetchSucursales().then(setSucursales).catch(() => setSucursales([]))
  }, [])

  // Debounce del buscador
  useEffect(() => {
    const t = setTimeout(() => setFilters((f) => ({ ...f, search: searchInput })), 350)
    return () => clearTimeout(t)
  }, [searchInput])

  // Resumen + priorizadas: dependen de filtros "macro" (org/canal/corredor/familia/abc/search)
  useEffect(() => {
    let alive = true
    fetchResumen(filters).then((r) => alive && setResumen(r)).catch(() => alive && setResumen(null))
    fetchPriorizadas(filters, 8).then((r) => alive && setPriorizadas(r)).catch(() => alive && setPriorizadas(null))
    return () => {
      alive = false
    }
  }, [filters.organizacion, filters.canal, filters.corredor, filters.plant, filters.familia, filters.abc, filters.search])

  // Tabla principal: reinicia a página 1 cuando cambian filtros u orden
  useEffect(() => {
    let alive = true
    setLoadingTable(true)
    setPage(1)
    fetchCobertura(filters, { page: 1, pageSize: PAGE_SIZE, sort })
      .then((data) => {
        if (!alive) return
        setRows(data.items ?? [])
        setTotal(data.total ?? 0)
      })
      .finally(() => alive && setLoadingTable(false))
    return () => {
      alive = false
    }
  }, [filters, sort])

  const cargarMas = useCallback(() => {
    if (loadingMore || rows.length >= total) return
    setLoadingMore(true)
    const next = page + 1
    fetchCobertura(filters, { page: next, pageSize: PAGE_SIZE, sort })
      .then((data) => {
        setRows((prev) => [...prev, ...(data.items ?? [])])
        setPage(next)
      })
      .finally(() => setLoadingMore(false))
  }, [filters, sort, page, rows.length, total, loadingMore])

  const activeFilterCount = useMemo(
    () => Object.values(filters).filter((v) => v).length,
    [filters],
  )

  function clearFilters() {
    setFilters({ organizacion: '', canal: '', corredor: '', plant: '', familia: '', abc: '', estado: '', search: '' })
    setSearchInput('')
  }

  async function onExportCSV() {
    setExporting(true)
    try {
      await exportarCoberturaCSV(filters, sort)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="page-inventarios">
      <header className="app-page-header">
        <div>
          <p className="eyebrow">Inventarios · Explorador</p>
          <h1 className="h1 app-page-header__title">Inventarios &amp; Cobertura</h1>
          <p className="body text-secondary" style={{ maxWidth: '68ch', marginTop: 'var(--space-1)' }}>
            ¿Qué material-sucursal está en riesgo de quiebre y cuál tiene sobreinventario, hoy?
          </p>
        </div>
        <div className="pi-header-actions">
          <span className="layer layer--c1">C1</span>
          <button type="button" className="btn btn--secondary btn--sm" onClick={onExportCSV} disabled={exporting || !total}>
            {exporting ? 'Exportando…' : '⭳ Exportar CSV'}
          </button>
        </div>
      </header>

      <InventariosFilters
        filters={filters}
        setFilters={setFilters}
        searchInput={searchInput}
        setSearchInput={setSearchInput}
        corredores={corredores}
        familias={familias}
        sucursales={sucursales}
        activeFilterCount={activeFilterCount}
        onClear={clearFilters}
      />

      <ResumenRow resumen={resumen} />

      <PriorizadasSection
        priorizadas={priorizadas}
        onSelect={(item) => setSelected({ material_id: item.material_id, plant: item.plant })}
      />

      <CoberturaTable
        loading={loadingTable}
        rows={rows}
        total={total}
        pageSize={PAGE_SIZE}
        sort={sort}
        setSort={setSort}
        activeFilterCount={activeFilterCount}
        onClear={clearFilters}
        loadingMore={loadingMore}
        onCargarMas={cargarMas}
        onSelect={(r) => setSelected({ material_id: r.material_id, plant: r.plant })}
      />

      {selected && (
        <DetailDrawer
          material_id={selected.material_id}
          plant={selected.plant}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  )
}
