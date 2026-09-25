import React, { useState } from "react";
import { fmtInt } from "./formato.js";

/** T25 (waykee 290148): botón que expande el detalle documento-a-documento
 * (backorder) o PO-a-PO (pedidos por cumplir) bajo demanda -- no se precarga
 * para no pegarle a la API por cada línea de la tabla. */
export default function DrillDown({ label, cantidad, cargar, columnas }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  if (!cantidad) {
    return <strong className="tnum">{fmtInt.format(0)}</strong>;
  }

  async function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (data || loading) return;
    setLoading(true);
    setError(null);
    try {
      setData(await cargar());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  const filas = data?.documentos || data?.pedidos || [];

  return (
    <span>
      <button
        className="btn btn--ghost btn--sm"
        style={{ padding: "0 4px", height: "auto", textDecoration: "underline", verticalAlign: "baseline" }}
        onClick={toggle}
        title={`Ver detalle de ${label.toLowerCase()}`}
        type="button"
      >
        <strong className="tnum">{fmtInt.format(cantidad)}</strong> {open ? "▴" : "▾"}
      </button>
      {open && (
        <div className="card card--flat" style={{ marginTop: 6, padding: 8, maxHeight: 170, overflowY: "auto" }}>
          {loading && <div className="caption text-tertiary">Cargando…</div>}
          {error && <div className="caption" style={{ color: "var(--danger-text)" }}>{error}</div>}
          {data && data.disponible === false && (
            <div className="caption text-tertiary">
              Detalle de {label.toLowerCase()} aún no disponible — viene en camino (waykee 290147).
            </div>
          )}
          {data && data.disponible && filas.length === 0 && (
            <div className="caption text-tertiary">Sin renglones de detalle para esta línea.</div>
          )}
          {data && data.disponible && filas.length > 0 && (
            <table className="table table--compact">
              <thead>
                <tr>{columnas.map((c) => <th key={c.key} className={c.num ? "num" : ""}>{c.label}</th>)}</tr>
              </thead>
              <tbody>
                {filas.map((r, i) => (
                  <tr key={i}>
                    {columnas.map((c) => (
                      <td key={c.key} className={c.num ? "num tnum" : ""}>
                        {c.fmt ? c.fmt(r[c.key]) : r[c.key] ?? "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </span>
  );
}
