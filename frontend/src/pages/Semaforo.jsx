import { useEffect, useMemo, useState } from 'react'
import { fetchCorredores, fetchDetalle, fetchProveedores, fetchResumen } from '../lib/semaforoData.js'
import PedidosTable from './semaforo/PedidosTable.jsx'
import SemaforoCards from './semaforo/SemaforoCards.jsx'
import SemaforoFilters from './semaforo/SemaforoFilters.jsx'
import './Semaforo.css'

const PAGE_SIZE = 50
const DEFAULT_UMBRAL = 3

/**
 * Pantalla "Semáforo de Cumplimiento (Lite)" (T11 · waykee 290099).
 * Ruta: /semaforo.
 *
 * Tablero de pedidos abiertos (backorders): tarjetas grandes verde/amarillo/
 * rojo con conteo + monto en riesgo, tabla drill-down por proveedor/sucursal
 * con días de atraso y compras en tránsito ligadas, umbral de "próximo a
 * vencer" configurable en la barra de filtros.
 *
 * Subcomponentes en ./semaforo/ (filtros, tarjetas, tabla).
 *
 * Auto-contenida: consume /api/semaforo/* — no requiere props.
 */
export default function Semaforo() {
  const [filters, setFilters] = useState({ organizacion: '', canal: '', corredor: '', proveedor: '' })
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [umbralDias, setUmbralDias] = useState(DEFAULT_UMBRAL)
  const [umbralInput, setUmbralInput] = useState(String(DEFAULT_UMBRAL))
  const [estadoActivo, setEstadoActivo] = useState('')
  const [sort, setSort] = useState('atraso_desc')

  const [corredores, setCorredores] = useState([])
  const [proveedores, setProveedores] = useState([])

  const [resumen, setResumen] = useState(null)
  const [resumenError, setResumenError] = useState(null)

  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loadingTable, setLoadingTable] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [tableError, setTableError] = useState(null)

  // Catálogos (una sola vez)
  useEffect(() => {
    fetchCorredores().then(setCorredores).catch(() => setCorredores([]))
    fetchProveedores().then(setProveedores).catch(() => setProveedores([]))
  }, [])

  // Debounce del buscador
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput), 350)
    return () => clearTimeout(t)
  }, [searchInput])

  // Debounce del umbral (input numérico libre, valida rango 0-30)
  useEffect(() => {
    const n = Number(umbralInput)
    if (umbralInput === '' || Number.isNaN(n) || n < 0 || n > 30) return
    const t = setTimeout(() => setUmbralDias(n), 400)
    return () => clearTimeout(t)
  }, [umbralInput])

  const allFilters = useMemo(() => ({ ...filters, search }), [filters, search])

  // Resumen: 3 tarjetas + monto total + tránsito ligado
  useEffect(() => {
    let alive = true
    setResumenError(null)
    fetchResumen(allFilters, umbralDias)
      .then((r) => alive && setResumen(r))
      .catch((e) => alive && setResumenError(e))
    return () => {
      alive = false
    }
  }, [allFilters, umbralDias])

  // Tabla: reinicia a página 1 cuando cambian filtros, umbral, estado o sort
  useEffect(() => {
    let alive = true
    setLoadingTable(true)
    setTableError(null)
    setPage(1)
    fetchDetalle(allFilters, umbralDias, { estado: estadoActivo, sort, page: 1, pageSize: PAGE_SIZE })
      .then((data) => {
        if (!alive) return
        setRows(data.items ?? [])
        setTotal(data.total ?? 0)
      })
      .catch((e) => alive && setTableError(e))
      .finally(() => alive && setLoadingTable(false))
    return () => {
      alive = false
    }
  }, [allFilters, umbralDias, estadoActivo, sort])

  function cargarMas() {
    if (loadingMore || rows.length >= total) return
    setLoadingMore(true)
    const next = page + 1
    fetchDetalle(allFilters, umbralDias, { estado: estadoActivo, sort, page: next, pageSize: PAGE_SIZE })
      .then((data) => {
        setRows((prev) => [...prev, ...(data.items ?? [])])
        setPage(next)
      })
      .finally(() => setLoadingMore(false))
  }

  const activeFilterCount = useMemo(
    () => Object.values(filters).filter((v) => v).length + (search ? 1 : 0),
    [filters, search],
  )

  function clearFilters() {
    setFilters({ organizacion: '', canal: '', corredor: '', proveedor: '' })
    setSearchInput('')
    setSearch('')
  }

  return (
    <div className="page-semaforo">
      <header className="app-page-header">
        <div>
          <p className="eyebrow">Cumplimiento · Lite</p>
          <h1 className="h1 app-page-header__title">Semáforo de Cumplimiento</h1>
          <p className="body text-secondary" style={{ maxWidth: '68ch', marginTop: 'var(--space-1)' }}>
            ¿Qué pedidos de compra abiertos están vencidos o a punto de vencer, y dónde?
          </p>
        </div>
        <div className="sf-header-actions">
          <span className="layer layer--c1">C1</span>
          <span className="badge badge--neutral" title="Alcance Fase 1: solo pedidos abiertos. El semáforo end-to-end (Requerimiento→Recepción) es F2.">
            Lite
          </span>
        </div>
      </header>

      <SemaforoFilters
        filters={filters}
        setFilters={setFilters}
        searchInput={searchInput}
        setSearchInput={setSearchInput}
        corredores={corredores}
        proveedores={proveedores}
        umbralInput={umbralInput}
        setUmbralInput={setUmbralInput}
        activeFilterCount={activeFilterCount}
        onClear={clearFilters}
      />

      <SemaforoCards
        resumen={resumen}
        error={resumenError}
        umbralDias={umbralDias}
        estadoActivo={estadoActivo}
        setEstadoActivo={setEstadoActivo}
      />

      <PedidosTable
        loading={loadingTable}
        error={tableError}
        rows={rows}
        total={total}
        pageSize={PAGE_SIZE}
        sort={sort}
        setSort={setSort}
        estadoActivo={estadoActivo}
        setEstadoActivo={setEstadoActivo}
        activeFilterCount={activeFilterCount}
        onClearAll={() => {
          clearFilters()
          setEstadoActivo('')
        }}
        loadingMore={loadingMore}
        onCargarMas={cargarMas}
      />
    </div>
  )
}
