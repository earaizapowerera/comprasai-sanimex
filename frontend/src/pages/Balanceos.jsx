import { useEffect, useMemo, useRef, useState } from "react";
import { fetchRemates, ORGANIZACIONES } from "../lib/balanceosData";
import { api } from "../lib/api.js";
import BalanceosNav from "./balanceos/BalanceosNav.jsx";
import "./Balanceos.css";

/**
 * Pantalla "Balanceos & Remates" (T10 · waykee 290098; motor de triggers v2
 * y Grid 1/Grid 2 · waykee 292187).
 * Ruta esperada: /balanceos.
 *
 * "Remates" sigue igual que en la demo (T10): motor de reglas local /
 * mock de remateEngine.js. "Balanceos" y "Pendientes" son el motor de
 * triggers v2 contra backend/app/routers/engines/balanceos.py.
 */
const fmtInt = new Intl.NumberFormat("es-MX");
const fmtM2 = new Intl.NumberFormat("es-MX", { maximumFractionDigits: 1 });
const fmtMeses = new Intl.NumberFormat("es-MX", { maximumFractionDigits: 2 });

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("es-MX");
}

// Mismos umbrales que estado_semaforo_balanceo (balanceos.py) / COBERTURA_CTE.
// No hay .sem--info ni .sem--neutral definidas en components.css: exceso y
// sin_dato reusan sem--ok / sin clase en vez de referenciar clases inexistentes.
function estadoBalanceoSem(estado) {
  switch (estado) {
    case "quiebre":
      return { cls: "sem--stop", label: "Quiebre" };
    case "riesgo":
      return { cls: "sem--warn", label: "Riesgo" };
    case "exceso":
      return { cls: "sem--ok", label: "Exceso" };
    case "sin_dato":
      return { cls: "", label: "Sin dato" };
    default:
      return { cls: "sem--ok", label: "OK" };
  }
}

export default function Balanceos() {
  const [tab, setTab] = useState("balanceos");
  const [loading, setLoading] = useState(true);
  const [remates, setRemates] = useState([]);
  const [dataSource, setDataSource] = useState({ remates: "mock" });
  const [org, setOrg] = useState("todas");
  const [search, setSearch] = useState("");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetchRemates().then((r) => {
      if (!alive) return;
      setRemates(r.items);
      setDataSource({ remates: r.source });
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, []);

  const remmatesFiltrados = useMemo(
    () =>
      remates.filter(
        (r) =>
          (org === "todas" || r.organizacion === org) &&
          (!search || r.descripcion.toLowerCase().includes(search.toLowerCase()) || r.material_id.toLowerCase().includes(search.toLowerCase()))
      ),
    [remates, org, search]
  );

  function marcarRemate(id) {
    setRemates((prev) => prev.map((r) => (r.id === id ? { ...r, estado: "marcado" } : r)));
  }

  return (
    <div className="page-balanceos">
      <header className="pb-header">
        <div>
          <p className="eyebrow">Inventarios · Optimización</p>
          <h1 className="h1">Balanceos &amp; Remates</h1>
          <p className="body text-secondary" style={{ maxWidth: "62ch", marginTop: "var(--space-1)" }}>
            ¿Qué muevo entre sucursales antes de comprar, y qué liquido antes de que se vuelva costo muerto?
          </p>
        </div>
        <div className="pb-tabs" role="tablist" aria-label="Balanceos y Remates">
          <button
            role="tab"
            aria-selected={tab === "balanceos"}
            className={`pb-tab ${tab === "balanceos" ? "pb-tab--active" : ""}`}
            onClick={() => setTab("balanceos")}
          >
            ⇄ Balanceos
          </button>
          <button
            role="tab"
            aria-selected={tab === "pendientes"}
            className={`pb-tab ${tab === "pendientes" ? "pb-tab--active" : ""}`}
            onClick={() => setTab("pendientes")}
          >
            📋 Balanceos pendientes
          </button>
          <button
            role="tab"
            aria-selected={tab === "remates"}
            className={`pb-tab ${tab === "remates" ? "pb-tab--active" : ""}`}
            onClick={() => setTab("remates")}
          >
            ⚠ Remates
            <span className="badge badge--neutral">{remmatesFiltrados.length}</span>
          </button>
        </div>
      </header>

      {tab === "remates" && (
        <div className="pb-filters card card--flat">
          <div className="input combobox" style={{ maxWidth: 280 }}>
            <input
              className="input"
              placeholder="Buscar SKU o descripción…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ border: "none", background: "transparent", padding: 0, height: "auto" }}
            />
          </div>
          <div className="pb-org-filter">
            <button
              className={`btn btn--sm ${org === "todas" ? "btn--primary" : "btn--secondary"}`}
              onClick={() => setOrg("todas")}
            >
              Todas
            </button>
            {ORGANIZACIONES.map((o) => (
              <button
                key={o}
                className={`btn btn--sm ${org === o ? "btn--primary" : "btn--secondary"}`}
                onClick={() => setOrg(o)}
              >
                {o}
              </button>
            ))}
          </div>

          {dataSource.remates === "mock" && (
            <span className="badge badge--ai" title="La API de motores (T4) aún no está disponible; mostrando datos de demostración construidos con el mismo motor de reglas.">
              ✨ Demo con motor de reglas local — API T4 pendiente
            </span>
          )}
        </div>
      )}

      {tab === "balanceos" && <BalanceosNav DetalleComponent={Grid1Tab} />}
      {tab === "pendientes" && <Grid2Tab />}
      {tab === "remates" &&
        (loading ? <SkeletonList /> : <RematesTab items={remmatesFiltrados} onMarcar={marcarRemate} />)}
    </div>
  );
}

function SkeletonList() {
  return (
    <div className="pb-list">
      {[0, 1, 2].map((i) => (
        <div className="card" key={i}>
          <span className="skeleton skeleton--text" style={{ width: "40%" }} />
          <span className="skeleton skeleton--text" style={{ width: "70%" }} />
          <span className="skeleton" style={{ width: "100%", height: 48, marginTop: 12 }} />
        </div>
      ))}
    </div>
  );
}

function ToastBanner({ toast }) {
  if (!toast) return null;
  return (
    <div
      className={`badge badge--${toast.kind === "danger" ? "danger" : toast.kind === "success" ? "success" : "neutral"}`}
      style={{ marginBottom: 16, height: "auto", padding: "8px 14px", display: "block" }}
    >
      {toast.text}
    </div>
  );
}

/** Combobox de materiales (Grid 1): busca contra GET /api/materiales — a
 * diferencia del Combobox genérico de Sugeridos.jsx (array plano de strings),
 * aquí las opciones son objetos {material_id, descripcion, ...} traídos de
 * la API con debounce, porque el catálogo es demasiado grande para precargar. */
function MaterialCombobox({ value, onSelect }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(value ? `${value.material_id} — ${value.descripcion}` : "");
  const [opciones, setOpciones] = useState([]);
  const [loading, setLoading] = useState(false);
  const ref = useRef(null);
  const debounceRef = useRef(null);

  useEffect(() => {
    function onClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  useEffect(() => {
    if (!open) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setLoading(true);
      api.materiales
        .buscar(text.trim())
        .then((res) => setOpciones(res.items || []))
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(debounceRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, open]);

  return (
    <div className="combobox" ref={ref} style={{ minWidth: 320 }}>
      <label className="footnote text-secondary" style={{ display: "block", marginBottom: 6 }}>
        Material
      </label>
      <div className="select-trigger" onClick={() => setOpen(true)} role="button" tabIndex={0}>
        <input
          className="body"
          style={{ border: "none", background: "transparent", width: "100%", outline: "none", padding: 0, height: "100%" }}
          placeholder="Buscar SKU o descripción…"
          value={text}
          onFocus={() => setOpen(true)}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      {open && (
        <div className="combobox__panel">
          {loading && <div className="combobox__empty">Buscando…</div>}
          {!loading && opciones.length === 0 && <div className="combobox__empty">Sin resultados</div>}
          {!loading &&
            opciones.map((m) => (
              <div
                key={m.material_id}
                className="combobox__option"
                aria-selected={value?.material_id === m.material_id}
                onClick={() => {
                  onSelect(m);
                  setText(`${m.material_id} — ${m.descripcion}`);
                  setOpen(false);
                }}
              >
                {m.material_id} — {m.descripcion}
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

/** Grid 1 (waykee 292187): preview por material+zona, una fila por ubicación,
 * con el trigger evaluado en backend (_compute_grid1). Desde v3 (292197) es el
 * 3er nivel de BalanceosNav: llega con material y corredor ya elegidos. */
function Grid1Tab({ initialMaterial = null, initialCorredor = "" }) {
  const [corredores, setCorredores] = useState([]);
  const [corredor, setCorredor] = useState(initialCorredor);
  const [material, setMaterial] = useState(initialMaterial);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [queried, setQueried] = useState(false);
  const [agregarRow, setAgregarRow] = useState(null);
  const [backorderRow, setBackorderRow] = useState(null);
  const [descartarRow, setDescartarRow] = useState(null);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    api.sugeridos
      .opciones()
      .then((r) => setCorredores(r.corredores || []))
      .catch(() => {});
  }, []);

  async function cargarGrid() {
    if (!material) return;
    setLoading(true);
    try {
      const res = await api.balanceos.grid(material.material_id, corredor || undefined);
      setItems(res.items || []);
    } finally {
      setLoading(false);
      setQueried(true);
    }
  }

  useEffect(() => {
    if (material) cargarGrid();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [material, corredor]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  return (
    <>
      <div className="pb-filters card card--flat">
        <MaterialCombobox value={material} onSelect={setMaterial} />
        <div className="combobox" style={{ minWidth: 200 }}>
          <label className="footnote text-secondary" style={{ display: "block", marginBottom: 6 }}>
            Zona / corredor
          </label>
          <select className="input select-trigger" value={corredor} onChange={(e) => setCorredor(e.target.value)}>
            <option value="">Todas las zonas</option>
            {corredores.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
      </div>

      <ToastBanner toast={toast} />

      {!material ? (
        <div className="empty card">
          <div className="empty__icon">⇄</div>
          <p className="h4">Elige un material para ver sus ubicaciones</p>
          <p className="footnote">El Grid 1 evalúa el trigger de balanceo por ubicación para el SKU seleccionado.</p>
        </div>
      ) : loading ? (
        <SkeletonList />
      ) : queried && items.length === 0 ? (
        <div className="empty card">
          <div className="empty__icon">⇄</div>
          <p className="h4">Sin ubicaciones para este material{corredor ? ` en ${corredor}` : ""}</p>
        </div>
      ) : (
        <div className="card" style={{ overflowX: "auto", padding: 0 }}>
          <table className="table">
            <thead>
              <tr>
                <th></th>
                <th>Ubicación</th>
                <th className="num">Metros</th>
                <th className="num">Meses</th>
                <th>Backorder compra</th>
                <th className="num">Backorder traslado</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <Grid1Rows
                items={items}
                agruparPorCorredor={!corredor}
                onVerBackorder={setBackorderRow}
                onAgregar={setAgregarRow}
                onDescartar={setDescartarRow}
              />
            </tbody>
          </table>
        </div>
      )}

      {agregarRow && (
        <AgregarModal
          origen={agregarRow}
          gridItems={items}
          materialId={material.material_id}
          onClose={() => setAgregarRow(null)}
          onAdded={() => {
            setAgregarRow(null);
            setToast({ kind: "success", text: "Agregado a Balanceos pendientes." });
          }}
        />
      )}

      {backorderRow && (
        <BackorderModal materialId={material.material_id} row={backorderRow} onClose={() => setBackorderRow(null)} />
      )}

      {descartarRow && (
        <DescartarModal
          materialId={material.material_id}
          row={descartarRow}
          onClose={() => setDescartarRow(null)}
          onDone={() => {
            setDescartarRow(null);
            setToast({ kind: "success", text: "Sugerencia descartada." });
            cargarGrid();
          }}
        />
      )}
    </>
  );
}

// Filas pre-ordenadas por el backend (corredor, orden, plant) — solo se
// intercala un separador visual por corredor cuando no hay filtro de zona.
function Grid1Rows({ items, agruparPorCorredor, onVerBackorder, onAgregar, onDescartar }) {
  let ultimoCorredor = null;
  const filas = [];
  items.forEach((row) => {
    if (agruparPorCorredor && row.corredor !== ultimoCorredor) {
      ultimoCorredor = row.corredor;
      filas.push(
        <tr key={`corredor-${row.corredor}-${row.plant}`}>
          <td colSpan={7} className="caption text-secondary" style={{ paddingTop: 16, background: "var(--surface-secondary)" }}>
            Corredor {row.corredor || "—"}
          </td>
        </tr>
      );
    }
    const sem = estadoBalanceoSem(row.estado);
    filas.push(
      <tr key={row.plant}>
        <td>
          <span className={`sem ${sem.cls}`} title={sem.label} style={{ display: "inline-flex" }}>
            <span className="sem__dot" />
          </span>
        </td>
        <td>
          <div style={{ fontWeight: 600 }}>
            {row.nombre}
            {row.esCedis && (
              <span className="badge badge--neutral" style={{ marginLeft: 6 }}>
                CEDIS
              </span>
            )}
          </div>
          <div className="caption text-tertiary">{row.plant}</div>
        </td>
        <td className="num tnum">{fmtM2.format(row.metros)}</td>
        <td className="num tnum">
          {row.meses == null ? "—" : fmtMeses.format(row.meses)}{" "}
          <span className="caption text-tertiary">/ {fmtMeses.format(row.mesesObjetivo)}</span>
        </td>
        <td>
          {row.backorderCompra.cajas > 0 ? (
            <button
              className="btn btn--ghost btn--sm"
              style={{ padding: "0 4px", height: "auto", textDecoration: "underline", whiteSpace: "normal", textAlign: "left" }}
              onClick={() => onVerBackorder(row)}
              type="button"
            >
              {fmtM2.format(row.backorderCompra.metros)} m² ·{" "}
              {row.backorderCompra.diasDesdePedido != null ? `hace ${row.backorderCompra.diasDesdePedido} d` : "—"} ·{" "}
              {row.backorderCompra.numeroPedidos} ped.
            </button>
          ) : (
            <span className="caption text-tertiary">—</span>
          )}
        </td>
        <td className="num tnum">
          {row.backorderTraslado.cajas > 0
            ? `${fmtM2.format(row.backorderTraslado.metros)} m² · ${fmtMeses.format(row.backorderTraslado.meses)} m`
            : "—"}
        </td>
        <td>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
            {row.trigger && (
              <span
                className={`badge ${row.descartado ? "badge--neutral" : "badge--warning"}`}
                title={
                  row.trigger.trigger === "sin_pedido"
                    ? "Rojo sin pedido de compra pendiente"
                    : `Pedido vencido (${row.trigger.diasDesdePedido}d > ${row.trigger.umbralDias}d)`
                }
              >
                {row.descartado ? "Descartado" : row.trigger.trigger === "sin_pedido" ? "Sin pedido" : "Pedido vencido"}
              </span>
            )}
            <button className="btn btn--primary btn--sm" onClick={() => onAgregar(row)} type="button">
              Agregar
            </button>
            {row.trigger && !row.descartado && (
              <button className="btn btn--secondary btn--sm" onClick={() => onDescartar(row)} type="button">
                Descartar
              </button>
            )}
          </div>
        </td>
      </tr>
    );
  });
  return filas;
}

/** Modal "Agregar" de Grid 1: la fila donde se dio click es el ORIGEN
 * (excedente); el destino se elige entre las demás ubicaciones del grid ya
 * cargado. Prellena metros con /sugerencia-cantidad pero siempre editable
 * (spec, waykee 292187). No postea a SAP aquí — solo inserta en pendientes
 * (Grid 2). */
function AgregarModal({ origen, gridItems, materialId, onClose, onAdded }) {
  const destinos = gridItems.filter((g) => g.plant !== origen.plant);
  const [destinoPlant, setDestinoPlant] = useState("");
  const [metros, setMetros] = useState("");
  const [sugerencia, setSugerencia] = useState(null);
  const [loadingSug, setLoadingSug] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!destinoPlant) {
      setSugerencia(null);
      return;
    }
    let alive = true;
    setLoadingSug(true);
    api.balanceos
      .sugerenciaCantidad(materialId, origen.plant, destinoPlant)
      .then((res) => {
        if (!alive) return;
        if (res.error) {
          setError(res.error);
          setSugerencia(null);
        } else {
          setError(null);
          setSugerencia(res);
          setMetros(String(res.cantidadSugeridaMetros ?? 0));
        }
      })
      .finally(() => alive && setLoadingSug(false));
    return () => {
      alive = false;
    };
  }, [destinoPlant, materialId, origen.plant]);

  async function submit() {
    const metrosNum = Number(metros);
    if (!destinoPlant) {
      setError("Elige un destino.");
      return;
    }
    if (!metrosNum || metrosNum <= 0) {
      setError("La cantidad debe ser mayor a 0.");
      return;
    }
    const m2PorCaja = origen.m2PorCaja;
    const cajas = m2PorCaja && m2PorCaja > 0 ? metrosNum / m2PorCaja : metrosNum;
    setSaving(true);
    setError(null);
    try {
      await api.balanceos.agregarPendiente(materialId, origen.plant, destinoPlant, Number(cajas.toFixed(2)));
      onAdded();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true" aria-label="Agregar a balanceos pendientes">
        <h3 className="h3 modal__title">Agregar balanceo</h3>
        <p className="footnote text-secondary">
          Origen (exceso): <strong>{origen.nombre}</strong> ({origen.plant})
        </p>

        <label className="footnote text-secondary" style={{ display: "block", margin: "16px 0 6px" }}>
          Destino
        </label>
        <select className="input select-trigger" value={destinoPlant} onChange={(e) => setDestinoPlant(e.target.value)}>
          <option value="">Selecciona destino…</option>
          {destinos.map((d) => (
            <option key={d.plant} value={d.plant}>
              {d.nombre} ({d.plant}) · {estadoBalanceoSem(d.estado).label}
            </option>
          ))}
        </select>

        <label className="footnote text-secondary" style={{ display: "block", margin: "16px 0 6px" }}>
          Metros a transferir
        </label>
        <input
          className="input tnum"
          type="number"
          min="0"
          step="0.01"
          value={metros}
          onChange={(e) => setMetros(e.target.value)}
          disabled={loadingSug}
        />
        {loadingSug && <p className="caption text-tertiary">Calculando sugerencia…</p>}
        {sugerencia && (
          <div className="ai-explain" style={{ marginTop: 12 }}>
            <div className="ai-explain__head">
              Sugerencia: {fmtM2.format(sugerencia.cantidadSugeridaMetros)} m² ({sugerencia.fuenteTope})
            </div>
            {!sugerencia.permitidoPorPrioridad && (
              <p className="footnote" style={{ margin: "8px 0 0", color: "var(--danger-text)" }}>
                ⚠ La regla de prioridad no recomienda este traslado (prioridad origen {sugerencia.prioridadOrigen.valor}{" "}
                vs. destino {sugerencia.prioridadDestino.valor}). Puedes forzarlo editando la cantidad, pero revísalo
                antes.
              </p>
            )}
          </div>
        )}
        {error && (
          <p className="footnote" style={{ color: "var(--danger-text)", marginTop: 8 }}>
            {error}
          </p>
        )}
        <div className="modal__actions">
          <button className="btn btn--ghost" onClick={onClose} disabled={saving}>
            Cancelar
          </button>
          <button className="btn btn--primary" onClick={submit} disabled={saving}>
            {saving ? "Agregando…" : "Agregar"}
          </button>
        </div>
      </div>
    </>
  );
}

const BACKORDER_COMPRA_COLUMNAS = [
  { key: "po", label: "PO" },
  { key: "posicion", label: "Pos." },
  { key: "proveedor", label: "Proveedor" },
  { key: "cantidad_pendiente", label: "Cant.", num: true, fmt: (v) => fmtInt.format(v || 0) },
  { key: "fecha_entrega_estimada", label: "Entrega est.", fmt: fmtDate },
];

/** Modal de detalle de backorder de compra (columna "Backorder compra" de
 * Grid 1). Dataset actual no tiene pedidos_compra_detalle por OC: se
 * degrada mostrando el agregado + la fecha simulada del pedido más antiguo
 * (mismo criterio que Semáforo/Sugeridos, ver calc_dias_desde_pedido). */
function BackorderModal({ materialId, row, onClose }) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    api.balanceos
      .backorderDetalle(materialId, row.plant)
      .then((res) => alive && setData(res))
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [materialId, row.plant]);

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="modal modal--lg" role="dialog" aria-modal="true" aria-label="Detalle de backorder de compra">
        <h3 className="h3 modal__title">
          Backorder de compra — {row.nombre} ({row.plant})
        </h3>
        {loading && <p className="caption text-tertiary">Cargando…</p>}
        {error && (
          <p className="footnote" style={{ color: "var(--danger-text)" }}>
            {error}
          </p>
        )}
        {data && data.disponible === false && (
          <div>
            <p className="footnote text-secondary" style={{ marginTop: 8 }}>
              {data.motivo}
            </p>
            <div className="pb-card__metrics" style={{ marginTop: 12 }}>
              <Metric label="Cajas en pedidos abiertos" value={fmtInt.format(data.pedidosAbiertosCajas || 0)} />
              <Metric label="Fecha del pedido más antiguo (simulada)" value={fmtDate(data.fechaPedidoSimulada)} />
            </div>
          </div>
        )}
        {data && data.disponible && (data.documentos || []).length === 0 && (
          <p className="caption text-tertiary" style={{ marginTop: 12 }}>
            Sin renglones de detalle para esta línea.
          </p>
        )}
        {data && data.disponible && (data.documentos || []).length > 0 && (
          <table className="table table--compact" style={{ marginTop: 12 }}>
            <thead>
              <tr>
                {BACKORDER_COMPRA_COLUMNAS.map((c) => (
                  <th key={c.key} className={c.num ? "num" : ""}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.documentos.map((d, i) => (
                <tr key={i}>
                  {BACKORDER_COMPRA_COLUMNAS.map((c) => (
                    <td key={c.key} className={c.num ? "num tnum" : ""}>
                      {c.fmt ? c.fmt(d[c.key]) : d[c.key] ?? "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="modal__actions">
          <button className="btn btn--primary" onClick={onClose}>
            Cerrar
          </button>
        </div>
      </div>
    </>
  );
}

/** Modal "Descartar" (snooze) de Grid 1: pregunta cuántos días descartar
 * la sugerencia antes de volver a mostrarla (spec, waykee 292187). */
function DescartarModal({ materialId, row, onClose, onDone }) {
  const [dias, setDias] = useState(30);
  const [motivo, setMotivo] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function submit() {
    if (!dias || Number(dias) <= 0) {
      setError("Ingresa un número de días mayor a 0.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.balanceos.descartar(materialId, row.plant, Number(dias), motivo.trim() || undefined);
      onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true" aria-label="Descartar sugerencia de balanceo">
        <h3 className="h3 modal__title">Descartar sugerencia</h3>
        <p className="footnote text-secondary">
          {row.nombre} ({row.plant}) — no se volverá a sugerir hasta que expire.
        </p>
        <label className="footnote text-secondary" style={{ display: "block", margin: "16px 0 6px" }}>
          Días a descartar
        </label>
        <input className="input tnum" type="number" min="1" value={dias} onChange={(e) => setDias(e.target.value)} />
        <label className="footnote text-secondary" style={{ display: "block", margin: "16px 0 6px" }}>
          Motivo (opcional)
        </label>
        <textarea
          className="input"
          style={{ height: 72, paddingTop: 10, resize: "vertical" }}
          value={motivo}
          onChange={(e) => setMotivo(e.target.value)}
          placeholder="Ej. Ya se colocó pedido urgente con el proveedor…"
        />
        {error && (
          <p className="footnote" style={{ color: "var(--danger-text)", marginTop: 8 }}>
            {error}
          </p>
        )}
        <div className="modal__actions">
          <button className="btn btn--ghost" onClick={onClose} disabled={saving}>
            Cancelar
          </button>
          <button className="btn btn--primary" onClick={submit} disabled={saving}>
            {saving ? "Guardando…" : "Descartar"}
          </button>
        </div>
      </div>
    </>
  );
}

/** Grid 2 (waykee 292187): "Balanceos pendientes" — agrupado por ruta
 * mientras estado='pendiente' (todos los "Agregar" hechos desde Grid 1);
 * agrupado por traslado_ref para 'posteado'/'entregado'. */
function Grid2Tab() {
  const [estado, setEstado] = useState("pendiente");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);

  async function cargar() {
    setLoading(true);
    try {
      const res = await api.balanceos.pendientes(estado);
      setItems(res.items || []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [estado]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  async function generarTraslado(row) {
    try {
      const res = await api.balanceos.generarTraslado(row.origen_plant, row.destino_plant);
      if (res.error) {
        setToast({ kind: "danger", text: res.error });
        return;
      }
      setToast({ kind: "success", text: `Traslado ${res.trasladoRef} generado (${fmtInt.format(res.cajasTotal)} cajas).` });
      cargar();
    } catch (e) {
      setToast({ kind: "danger", text: e.message });
    }
  }

  async function marcarEntregado(row) {
    try {
      await api.balanceos.marcarEntregado(row.traslado_ref);
      setToast({ kind: "success", text: `Traslado ${row.traslado_ref} marcado como entregado.` });
      cargar();
    } catch (e) {
      setToast({ kind: "danger", text: e.message });
    }
  }

  const labelEstado = estado === "pendiente" ? "pendientes" : estado === "posteado" ? "posteados" : "entregados";

  return (
    <>
      <div className="pb-filters card card--flat">
        <div className="pb-org-filter">
          {[
            ["pendiente", "Pendientes"],
            ["posteado", "Posteados"],
            ["entregado", "Entregados"],
          ].map(([k, label]) => (
            <button
              key={k}
              className={`btn btn--sm ${estado === k ? "btn--primary" : "btn--secondary"}`}
              onClick={() => setEstado(k)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <ToastBanner toast={toast} />

      {loading ? (
        <SkeletonList />
      ) : items.length === 0 ? (
        <div className="empty card">
          <div className="empty__icon">📋</div>
          <p className="h4">Sin traslados {labelEstado}</p>
          <p className="footnote">Agrega balanceos desde la pestaña "⇄ Balanceos".</p>
        </div>
      ) : (
        <div className="card" style={{ overflowX: "auto", padding: 0 }}>
          <table className="table">
            <thead>
              <tr>
                <th>Ruta</th>
                <th className="num">Cajas</th>
                <th className="num">Líneas</th>
                {estado !== "pendiente" && <th>Referencia SAP</th>}
                {estado === "posteado" && <th>Posteado</th>}
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.traslado_ref || `${row.origen_plant}-${row.destino_plant}`}>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontWeight: 600 }}>{row.origen_nombre}</span>
                      <span aria-hidden="true">→</span>
                      <span style={{ fontWeight: 600 }}>{row.destino_nombre}</span>
                    </div>
                    <div className="caption text-tertiary">
                      {row.origen_plant} → {row.destino_plant}
                    </div>
                  </td>
                  <td className="num tnum">{fmtInt.format(row.cajas)}</td>
                  <td className="num tnum">{row.items}</td>
                  {estado !== "pendiente" && <td className="caption tnum">{row.traslado_ref}</td>}
                  {estado === "posteado" && <td className="caption">{fmtDate(row.posteado_en)}</td>}
                  <td>
                    {estado === "pendiente" && (
                      <button className="btn btn--primary btn--sm" onClick={() => generarTraslado(row)} type="button">
                        Generar traslado
                      </button>
                    )}
                    {estado === "posteado" && (
                      <button className="btn btn--secondary btn--sm" onClick={() => marcarEntregado(row)} type="button">
                        Marcar entregado
                      </button>
                    )}
                    {estado === "entregado" && <span className="badge badge--success">✓ Entregado</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function RematesTab({ items, onMarcar }) {
  return (
    <>
      <EscalaLegend />
      {!items.length ? (
        <div className="empty card">
          <div className="empty__icon">⚠</div>
          <p className="h4">Sin remanentes detectados</p>
          <p className="footnote">Ajusta el filtro de organización o vuelve más tarde.</p>
        </div>
      ) : (
        <div className="pb-list">
          {items.map((r) => (
            <div className="card pb-card" key={r.id}>
              <div className="pb-card__top">
                <div className="pb-card__title">
                  <span className={`abc abc--${r.abc.toLowerCase()}`}>{r.abc}</span>
                  <div>
                    <p className="body" style={{ fontWeight: 600 }}>
                      {r.descripcion} {r.economico && <span className="badge badge--neutral">Económico</span>}
                    </p>
                    <p className="caption tnum">{r.material_id} · {r.nombre} · {r.organizacion}</p>
                  </div>
                </div>
                <span className="layer layer--c1">C1</span>
              </div>

              <FlowRemate ruta={r.ruta} enSitio={r.enSitio} excepcionPlaza={r.excepcionPlaza} />

              <div className="pb-card__metrics">
                <Metric label="Días sin venta" value={r.diasSinVenta} tone={r.diasSinVenta > 120 ? "danger" : "warn"} />
                <Metric label="Cajas remanentes" value={r.cajas} />
                <Metric label="Precio de remate" value={`$${r.precioPorCaja}/caja`} />
                <Metric label="Valor en riesgo" value={`$${r.valorEnRiesgo.toLocaleString("es-MX")}`} tone="danger" strong />
                <Metric label="Importe remate" value={`$${r.importe.toLocaleString("es-MX")}`} tone="ok" strong />
              </div>

              {r.esExcepcionPrecio && (
                <div className="ai-explain" style={{ marginTop: "var(--space-3)" }}>
                  <div className="ai-explain__head">
                    {r.esSupuestoPrecio ? "⚠ Supuesto a validar con Sanimex" : "✓ Regla de excepción aplicada"}
                  </div>
                  <p className="footnote" style={{ margin: "var(--space-2) 0 0" }}>{r.motivoPrecio}</p>
                </div>
              )}

              <div className="pb-card__actions">
                {r.estado === "pendiente" ? (
                  <button className="btn btn--danger btn--sm" onClick={() => onMarcar(r.id)}>Marcar para remate</button>
                ) : (
                  <span className="badge badge--danger">✓ Marcado para remate</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function Metric({ label, value, tone, strong }) {
  const toneClass = tone === "ok" ? "text-success" : tone === "warn" ? "text-warn" : tone === "danger" ? "text-danger" : "";
  return (
    <div className="pb-metric">
      <span className="caption">{label}</span>
      <span className={`tnum ${strong ? "body" : "footnote"} ${toneClass}`} style={strong ? { fontWeight: 700 } : {}}>
        {value}
      </span>
    </div>
  );
}

function FlowRemate({ ruta, enSitio, excepcionPlaza }) {
  if (enSitio) {
    return (
      <div className="flow">
        <div className="flow-node flow-node--dest">
          <span className="caption">{excepcionPlaza ? "Plaza de excepción" : "Sin traslado"}</span>
          <span className="footnote" style={{ fontWeight: 600 }}>{ruta[0].nombre} · liquida en sitio</span>
        </div>
      </div>
    );
  }
  return (
    <div className="flow flow--multi">
      {ruta.map((nodo, i) => (
        <div className="flow-hop" key={i}>
          <div className={`flow-node ${nodo.tipo === "remate" ? "flow-node--dest" : ""} ${nodo.tipo === "cedis" ? "flow-node--cedis" : ""}`}>
            <span className="caption">{nodo.tipo === "origen" ? "Origen" : nodo.tipo === "cedis" ? "CEDIS" : "Sucursal de remate"}</span>
            <span className="footnote" style={{ fontWeight: 600 }}>{nodo.nombre}</span>
          </div>
          {i < ruta.length - 1 && (
            <div className="flow-arrow flow-arrow--compact">
              <div className="flow-arrow__line" />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function EscalaLegend() {
  return (
    <div className="card card--flat pb-legend">
      <span className="eyebrow">Minuta GAM · precio por caja según cantidad remanente</span>
      <div className="pb-legend__row">
        <span className="badge badge--neutral tnum">1-3 → $70</span>
        <span className="badge badge--neutral tnum">4-10 → $80</span>
        <span className="badge badge--warning tnum">11-14 → $120</span>
        <span className="badge badge--danger tnum">15-30 → $140</span>
        <span className="badge badge--ai tnum">Económico ≥30 → $120 directo</span>
      </div>
    </div>
  );
}
