import { useEffect, useState } from "react";
import { api } from "../../lib/api.js";
import { Metric } from "./BalanceosUi.jsx";
import { fmtDate, fmtInt } from "./balanceosFormat.js";

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
export default function BackorderModal({ materialId, row, onClose }) {
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
