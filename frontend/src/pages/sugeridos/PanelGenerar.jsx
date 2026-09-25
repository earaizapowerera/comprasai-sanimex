import Combobox from "./Combobox.jsx";
import { ETAPAS, fmtInt } from "./formato.js";

/** Waykee 292251: lote vigente a la fecha elegida (informativo antes de generar). */
function LoteVigente({ loteInfo, onConfigurar }) {
  return (
    <div className="footnote" data-testid="lote-vigente" style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      {loteInfo.aplicado ? (
        <>
          <span className="badge badge--accent">🗂 Lote vigente</span>
          <span className="text-secondary">Solo clasificaciones:</span>
          {loteInfo.clasificaciones.length
            ? loteInfo.clasificaciones.map((c) => <span key={c} className="badge badge--neutral">{c}</span>)
            : <span className="badge badge--warning">⚠ ninguna</span>}
          <span className="caption text-tertiary">({loteInfo.lotes.map((l) => l.nombre).join(" · ")})</span>
          {loteInfo.lineas_excluidas != null && (
            <span className="caption text-tertiary">· {fmtInt.format(loteInfo.lineas_excluidas)} líneas fuera de lote</span>
          )}
        </>
      ) : (
        <span className="text-secondary">Sin lote de compra vigente para esta fecha: se consideran todas las clasificaciones.</span>
      )}
      <button className="btn btn--ghost btn--sm" onClick={onConfigurar}>Configurar lotes →</button>
    </div>
  );
}

function EtapasGeneracion({ stage }) {
  return (
    <div style={{ display: "flex", gap: 12, marginTop: 20, flexWrap: "wrap" }}>
      {ETAPAS.map((e, i) => (
        <div
          key={e.key}
          className="card card--flat"
          style={{
            flex: "1 1 200px",
            padding: "12px 16px",
            opacity: i <= stage ? 1 : 0.4,
            borderColor: i === stage ? "var(--ai)" : "var(--border-default)",
            transition: "opacity 220ms ease, border-color 220ms ease",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className={`layer layer--${e.key.toLowerCase()}`}>{e.key}</span>
            <strong className="footnote">{e.label}</strong>
            {i < stage && <span style={{ marginLeft: "auto", color: "var(--success-text)" }}>✓</span>}
            {i === stage && <span className="typing" style={{ marginLeft: "auto", padding: 0 }}><span /><span /><span /></span>}
          </div>
          <p className="caption text-tertiary" style={{ margin: "4px 0 0" }}>{e.detail}</p>
        </div>
      ))}
    </div>
  );
}

function Filtros({ s }) {
  const { filtros, setFiltros, opciones, fecha, setFecha, generar, generating } = s;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gap: "var(--space-4)", alignItems: "end" }}>
      <div style={{ gridColumn: "span 3" }}>
        <Combobox label="Familia" value={filtros.familia} options={opciones.familias} onChange={(v) => setFiltros((f) => ({ ...f, familia: v }))} />
      </div>
      <div style={{ gridColumn: "span 3" }}>
        <Combobox label="Proveedor" value={filtros.proveedor} options={opciones.proveedores} onChange={(v) => setFiltros((f) => ({ ...f, proveedor: v }))} />
      </div>
      <div style={{ gridColumn: "span 2" }}>
        <Combobox label="Corredor" value={filtros.corredor} options={opciones.corredores} onChange={(v) => setFiltros((f) => ({ ...f, corredor: v }))} />
      </div>
      <div style={{ gridColumn: "span 2" }}>
        <label className="footnote text-secondary" style={{ display: "block", marginBottom: 6 }}>Fecha de compra</label>
        <input type="date" className="input" value={fecha} onChange={(e) => setFecha(e.target.value)} aria-label="Fecha de compra" />
      </div>
      <div style={{ gridColumn: "span 2" }}>
        <button className="btn btn--ai btn--lg" style={{ width: "100%" }} onClick={generar} disabled={generating}>
          {generating ? "Generando…" : "✨ Generar sugeridos"}
        </button>
      </div>
    </div>
  );
}

/** Tarjeta de filtros + botón Generar (animación C1→C2→C3). */
export default function PanelGenerar({ s }) {
  return (
    <div className="card" style={{ marginBottom: 24 }}>
      <Filtros s={s} />

      {s.loteInfo && <LoteVigente loteInfo={s.loteInfo} onConfigurar={() => s.setVista("lotes")} />}

      {s.generating && <EtapasGeneracion stage={s.stage} />}
    </div>
  );
}
