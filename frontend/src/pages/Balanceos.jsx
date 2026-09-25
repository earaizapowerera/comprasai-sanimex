import { useEffect, useMemo, useState } from "react";
import { fetchRemates, ORGANIZACIONES } from "../lib/balanceosData";
import BalanceosNav from "./balanceos/BalanceosNav.jsx";
import { SkeletonList } from "./balanceos/BalanceosUi.jsx";
import Grid1Tab from "./balanceos/Grid1Tab.jsx";
import Grid2Tab from "./balanceos/Grid2Tab.jsx";
import RematesTab from "./balanceos/RematesTab.jsx";
import "./Balanceos.css";

/**
 * Pantalla "Balanceos & Remates" (T10 · waykee 290098; motor de triggers v2
 * y Grid 1/Grid 2 · waykee 292187).
 * Ruta esperada: /balanceos.
 *
 * "Remates" sigue igual que en la demo (T10): motor de reglas local /
 * mock de remateEngine.js. "Balanceos" y "Pendientes" son el motor de
 * triggers v2 contra backend/app/routers/engines/balanceos.py.
 *
 * Subcomponentes en ./balanceos/ (navegación, Grid 1, modales, Grid 2, remates).
 */

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
