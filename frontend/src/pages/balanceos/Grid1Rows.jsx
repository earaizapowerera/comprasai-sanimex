import { estadoBalanceoSem, fmtM2, fmtMeses } from "./balanceosFormat.js";

// Filas pre-ordenadas por el backend (corredor, orden, plant) — solo se
// intercala un separador visual por corredor cuando no hay filtro de zona.
export default function Grid1Rows({ items, agruparPorCorredor, onVerBackorder, onAgregar, onDescartar }) {
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
