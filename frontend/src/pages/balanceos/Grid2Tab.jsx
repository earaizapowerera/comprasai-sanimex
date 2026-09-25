import { useEffect, useState } from "react";
import { api } from "../../lib/api.js";
import { SkeletonList, ToastBanner, useAutoDismissToast } from "./BalanceosUi.jsx";
import { fmtDate, fmtInt } from "./balanceosFormat.js";

/** Grid 2 (waykee 292187): "Balanceos pendientes" — agrupado por ruta
 * mientras estado='pendiente' (todos los "Agregar" hechos desde Grid 1);
 * agrupado por traslado_ref para 'posteado'/'entregado'. */
export default function Grid2Tab() {
  const [estado, setEstado] = useState("pendiente");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useAutoDismissToast();

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
