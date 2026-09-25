import { Metric } from "./BalanceosUi.jsx";

/** Tab "Remates" (T10): tarjetas de remanentes con ruta y escala de la minuta GAM. */
export default function RematesTab({ items, onMarcar }) {
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
