import { useEffect, useMemo, useState } from "react";
import { fetchBalanceos, fetchRemates, ORGANIZACIONES } from "../lib/balanceosData";
import "./Balanceos.css";

/**
 * Pantalla "Balanceos & Remates" (T10 · waykee 290098).
 * Ruta esperada: /balanceos.
 *
 * Auto-contenida: obtiene sus propios datos (API real de T4 si existe, si no
 * cae a mock construido con el motor de reglas de remateEngine.js) y no
 * requiere props. Para integrarla al shell de T7 basta:
 *   import Balanceos from "./pages/Balanceos";
 *   <Route path="/balanceos" element={<Balanceos />} />
 *
 * Asume que el shell ya importa design-tokens.css y components.css a nivel
 * global (T2). Este archivo solo agrega estilos propios de la visualización
 * de flujo (Balanceos.css).
 */
export default function Balanceos() {
  const [tab, setTab] = useState("balanceos");
  const [loading, setLoading] = useState(true);
  const [balanceos, setBalanceos] = useState([]);
  const [remates, setRemates] = useState([]);
  const [dataSource, setDataSource] = useState({ balanceos: "mock", remates: "mock" });
  const [org, setOrg] = useState("todas");
  const [search, setSearch] = useState("");
  const [comboOpen, setComboOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([fetchBalanceos(), fetchRemates()]).then(([b, r]) => {
      if (!alive) return;
      setBalanceos(b.items);
      setRemates(r.items);
      setDataSource({ balanceos: b.source, remates: r.source });
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, []);

  const balanceosFiltrados = useMemo(
    () =>
      balanceos.filter(
        (b) =>
          (!search || b.descripcion.toLowerCase().includes(search.toLowerCase()) || b.material_id.toLowerCase().includes(search.toLowerCase()))
      ),
    [balanceos, search]
  );

  const remmatesFiltrados = useMemo(
    () =>
      remates.filter(
        (r) =>
          (org === "todas" || r.organizacion === org) &&
          (!search || r.descripcion.toLowerCase().includes(search.toLowerCase()) || r.material_id.toLowerCase().includes(search.toLowerCase()))
      ),
    [remates, org, search]
  );

  function aprobarBalanceo(id, aprobado) {
    setBalanceos((prev) => prev.map((b) => (b.id === id ? { ...b, estado: aprobado ? "aprobado" : "rechazado" } : b)));
  }

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
            <span className="badge badge--neutral">{balanceosFiltrados.length}</span>
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

        {tab === "remates" && (
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
        )}

        {(dataSource.balanceos === "mock" || dataSource.remates === "mock") && (
          <span className="badge badge--ai" title="La API de motores (T4) aún no está disponible; mostrando datos de demostración construidos con el mismo motor de reglas.">
            ✨ Demo con motor de reglas local — API T4 pendiente
          </span>
        )}
      </div>

      {loading ? (
        <SkeletonList />
      ) : tab === "balanceos" ? (
        <BalanceosTab items={balanceosFiltrados} onAprobar={aprobarBalanceo} />
      ) : (
        <RematesTab items={remmatesFiltrados} onMarcar={marcarRemate} />
      )}
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

function BalanceosTab({ items, onAprobar }) {
  if (!items.length) {
    return (
      <div className="empty card">
        <div className="empty__icon">⇄</div>
        <p className="h4">Sin propuestas de balanceo</p>
        <p className="footnote">No hay excedentes disponibles dentro de ningún corredor en este momento.</p>
      </div>
    );
  }
  return (
    <div className="pb-list">
      {items.map((b) => (
        <div className="card pb-card" key={b.id}>
          <div className="pb-card__top">
            <div className="pb-card__title">
              <span className={`abc abc--${b.abc.toLowerCase()}`}>{b.abc}</span>
              <div>
                <p className="body" style={{ fontWeight: 600 }}>{b.descripcion}</p>
                <p className="caption tnum">{b.material_id} · {b.corredor}</p>
              </div>
            </div>
            <span className="layer layer--c3">C3</span>
          </div>

          <FlowBalanceo origen={b.origen} destino={b.destino} cajas={b.cajasTransferir} />

          <div className="pb-card__metrics">
            <Metric label="Transferir" value={`${b.cajasTransferir} cajas`} />
            {b.cajasComprar > 0 ? (
              <Metric label="Compra complementaria" value={`${b.cajasComprar} cajas`} tone="warn" />
            ) : (
              <Metric label="Compra evitada" value="100%" tone="ok" />
            )}
            <Metric label="Costo traslado" value={`$${b.costoTraslado.toLocaleString("es-MX")}`} />
            <Metric label="Ahorro estimado" value={`$${b.ahorroEstimado.toLocaleString("es-MX")}`} tone="ok" strong />
          </div>

          <div className="pb-card__actions">
            {b.estado === "pendiente" ? (
              <>
                <button className="btn btn--secondary btn--sm" onClick={() => onAprobar(b.id, false)}>Rechazar</button>
                <button className="btn btn--primary btn--sm" onClick={() => onAprobar(b.id, true)}>Aprobar transferencia</button>
              </>
            ) : (
              <span className={`badge ${b.estado === "aprobado" ? "badge--success" : "badge--danger"}`}>
                {b.estado === "aprobado" ? "✓ Aprobado" : "✕ Rechazado"}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
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

function FlowBalanceo({ origen, destino, cajas }) {
  return (
    <div className="flow">
      <div className="flow-node">
        <span className="caption">Origen (exceso)</span>
        <span className="footnote" style={{ fontWeight: 600 }}>{origen.nombre}</span>
      </div>
      <div className="flow-arrow">
        <span className="flow-arrow__label tnum">{cajas} cajas</span>
        <div className="flow-arrow__line" />
      </div>
      <div className="flow-node flow-node--dest">
        <span className="caption">Destino (faltante)</span>
        <span className="footnote" style={{ fontWeight: 600 }}>{destino.nombre}</span>
      </div>
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
