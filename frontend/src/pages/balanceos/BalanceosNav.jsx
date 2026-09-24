import { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api.js";
import "./BalanceosNav.css";

/**
 * Balanceos v3 (waykee 292197): navegación en 3 niveles sobre el cache de
 * propuestas del backend (GET /api/balanceos/zonas y /articulos).
 *   1) Zonas (corredores) con conteo de balanceos propuestos.
 *   2) Artículos con balanceo propuesto en la zona elegida.
 *   3) Grid 1 (292187) del artículo en TODA la zona — se recibe como
 *      DetalleComponent para no duplicarlo ni crear import circular.
 */
const fmtInt = new Intl.NumberFormat("es-MX");
const fmtMxn = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN", maximumFractionDigits: 0 });
const PAGE = 100;

function fmtGenerado(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("es-MX");
}

export default function BalanceosNav({ DetalleComponent }) {
  const [zona, setZona] = useState(null);
  const [articulo, setArticulo] = useState(null);

  return (
    <div className="bn">
      <Breadcrumb
        zona={zona}
        articulo={articulo}
        onRoot={() => {
          setZona(null);
          setArticulo(null);
        }}
        onZona={() => setArticulo(null)}
      />
      {!zona && <ZonasView onSelect={setZona} />}
      {zona && !articulo && <ArticulosView key={zona} corredor={zona} onSelect={setArticulo} />}
      {zona && articulo && (
        <DetalleComponent
          key={`${zona}-${articulo.material_id}`}
          initialMaterial={{ material_id: articulo.material_id, descripcion: articulo.descripcion }}
          initialCorredor={zona}
        />
      )}
    </div>
  );
}

function Breadcrumb({ zona, articulo, onRoot, onZona }) {
  return (
    <nav className="bn-crumbs footnote" aria-label="Navegación de balanceos">
      {zona ? (
        <button type="button" className="bn-crumb" onClick={onRoot}>Zonas</button>
      ) : (
        <span className="bn-crumb bn-crumb--current">Zonas</span>
      )}
      {zona && <span className="text-tertiary">›</span>}
      {zona &&
        (articulo ? (
          <button type="button" className="bn-crumb" onClick={onZona}>{zona}</button>
        ) : (
          <span className="bn-crumb bn-crumb--current">{zona}</span>
        ))}
      {articulo && <span className="text-tertiary">›</span>}
      {articulo && (
        <span className="bn-crumb bn-crumb--current">
          {articulo.material_id} — {articulo.descripcion}
        </span>
      )}
    </nav>
  );
}

function ErrorCard({ error }) {
  return (
    <div className="empty card" role="alert">
      <div className="empty__icon">⚠</div>
      <p className="h4">No se pudieron cargar los balanceos</p>
      <p className="footnote">{error}</p>
    </div>
  );
}

function SkeletonRows() {
  return (
    <div className="bn-zonas">
      {[0, 1, 2, 3].map((i) => (
        <div className="card" key={i}>
          <span className="skeleton skeleton--text" style={{ width: "60%" }} />
          <span className="skeleton" style={{ width: "100%", height: 40, marginTop: 12 }} />
        </div>
      ))}
    </div>
  );
}

function ZonasView({ onSelect }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [orden, setOrden] = useState("ahorro");
  const [recalculando, setRecalculando] = useState(false);
  const [aviso, setAviso] = useState(null);

  useEffect(() => {
    api.balanceos.zonas().then(setData).catch((e) => setError(e.message));
  }, []);

  const zonas = useMemo(() => {
    const items = [...(data?.items || [])];
    return orden === "count"
      ? items.sort((a, b) => b.propuestas - a.propuestas)
      : items.sort((a, b) => b.ahorroTotal - a.ahorroTotal);
  }, [data, orden]);

  async function recalcular() {
    setRecalculando(true);
    setAviso(null);
    try {
      const r = await api.balanceos.recalcular();
      setAviso({ kind: "success", text: `Recalculado: ${fmtInt.format(r.total)} balanceos en ${r.zonas} zonas (${fmtInt.format(r.duracionMs)} ms).` });
      setData(await api.balanceos.zonas());
    } catch (e) {
      setAviso({ kind: "danger", text: e.message });
    } finally {
      setRecalculando(false);
    }
  }

  if (error) return <ErrorCard error={error} />;

  return (
    <>
      <div className="bn-toolbar card card--flat">
        <div>
          <p className="h4">{data ? `${fmtInt.format(data.total)} balanceos propuestos` : "Cargando…"}</p>
          <p className="caption text-tertiary">Calculado: {fmtGenerado(data?.generado)} · se recalcula con cada snapshot diario</p>
        </div>
        <div className="bn-toolbar__actions">
          <span className="footnote text-secondary">Ordenar por</span>
          <button type="button" className={`btn btn--sm ${orden === "ahorro" ? "btn--primary" : "btn--secondary"}`} onClick={() => setOrden("ahorro")}>
            Ahorro
          </button>
          <button type="button" className={`btn btn--sm ${orden === "count" ? "btn--primary" : "btn--secondary"}`} onClick={() => setOrden("count")}>
            Nº balanceos
          </button>
          <button type="button" className="btn btn--sm btn--secondary" onClick={recalcular} disabled={recalculando}>
            {recalculando ? "Recalculando…" : "↻ Recalcular ahora"}
          </button>
        </div>
      </div>
      {aviso && <div className={`badge badge--${aviso.kind} bn-aviso`}>{aviso.text}</div>}
      {!data ? (
        <SkeletonRows />
      ) : zonas.length === 0 ? (
        <div className="empty card">
          <div className="empty__icon">⇄</div>
          <p className="h4">No hay balanceos propuestos en el snapshot actual</p>
        </div>
      ) : (
        <div className="bn-zonas">
          {zonas.map((z) => (
            <button type="button" key={z.corredor} className="card bn-zona" onClick={() => onSelect(z.corredor)}>
              <div className="bn-zona__top">
                <span className="h4">{z.corredor}</span>
                <span className="badge badge--accent bn-zona__count" title="Balanceos propuestos">
                  {fmtInt.format(z.propuestas)}
                </span>
              </div>
              <div className="bn-zona__metrics">
                <div><span className="caption text-tertiary">Ahorro estimado</span><span className="tnum">{fmtMxn.format(z.ahorroTotal)}</span></div>
                <div><span className="caption text-tertiary">Artículos</span><span className="tnum">{fmtInt.format(z.materiales)}</span></div>
                <div><span className="caption text-tertiary">Cajas</span><span className="tnum">{fmtInt.format(z.cajasTransferir)}</span></div>
              </div>
            </button>
          ))}
        </div>
      )}
    </>
  );
}

function ArticulosView({ corredor, onSelect }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [visibles, setVisibles] = useState(PAGE);

  useEffect(() => {
    api.balanceos.articulos(corredor).then(setData).catch((e) => setError(e.message));
  }, [corredor]);

  const filtrados = useMemo(() => {
    const q = search.trim().toLowerCase();
    const items = data?.items || [];
    return q ? items.filter((a) => a.material_id.toLowerCase().includes(q) || (a.descripcion || "").toLowerCase().includes(q)) : items;
  }, [data, search]);

  if (error) return <ErrorCard error={error} />;
  if (!data) return <SkeletonRows />;

  return (
    <>
      <div className="bn-toolbar card card--flat">
        <div>
          <p className="h4">{fmtInt.format(data.total)} artículos con balanceo propuesto</p>
          <p className="caption text-tertiary">Elige un artículo para ver sus existencias en toda la zona</p>
        </div>
        <input
          className="input"
          style={{ maxWidth: 280 }}
          placeholder="Buscar SKU o descripción…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setVisibles(PAGE);
          }}
        />
      </div>
      <div className="card" style={{ overflowX: "auto", padding: 0 }}>
        <table className="table bn-table">
          <thead>
            <tr>
              <th>SKU</th>
              <th>Descripción</th>
              <th>ABC</th>
              <th className="num">Balanceos</th>
              <th className="num">Déficit (cajas)</th>
              <th className="num">Cajas a mover</th>
              <th className="num">Ahorro estimado</th>
            </tr>
          </thead>
          <tbody>
            {filtrados.slice(0, visibles).map((a) => (
              <tr key={a.material_id} className="bn-row" onClick={() => onSelect(a)} tabIndex={0}
                onKeyDown={(e) => e.key === "Enter" && onSelect(a)}>
                <td className="tnum" style={{ fontWeight: 600 }}>{a.material_id}</td>
                <td>{a.descripcion}</td>
                <td><span className="badge badge--neutral">{a.abc || "—"}</span></td>
                <td className="num tnum">{a.propuestas}</td>
                <td className="num tnum">{fmtInt.format(Math.round(a.deficit))}</td>
                <td className="num tnum">{fmtInt.format(a.cajasTransferir)}</td>
                <td className="num tnum">{fmtMxn.format(a.ahorroEstimado)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtrados.length === 0 && <p className="footnote text-secondary" style={{ padding: 16 }}>Sin resultados.</p>}
      </div>
      {filtrados.length > visibles && (
        <button type="button" className="btn btn--secondary btn--sm bn-more" onClick={() => setVisibles((v) => v + PAGE)}>
          Mostrar más ({fmtInt.format(filtrados.length - visibles)} restantes)
        </button>
      )}
    </>
  );
}
