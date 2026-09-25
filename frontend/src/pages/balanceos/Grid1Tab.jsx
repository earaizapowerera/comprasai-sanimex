import { useEffect, useState } from "react";
import FuenteBadge from "../../components/FuenteBadge.jsx";
import { api } from "../../lib/api.js";
import AgregarModal from "./AgregarModal.jsx";
import BackorderModal from "./BackorderModal.jsx";
import { SkeletonList, ToastBanner, useAutoDismissToast } from "./BalanceosUi.jsx";
import DescartarModal from "./DescartarModal.jsx";
import Grid1Rows from "./Grid1Rows.jsx";
import MaterialCombobox from "./MaterialCombobox.jsx";

/** Grid 1 (waykee 292187): preview por material+zona, una fila por ubicación,
 * con el trigger evaluado en backend (_compute_grid1). Desde v3 (292197) es el
 * 3er nivel de BalanceosNav: llega con material y corredor ya elegidos. */
export default function Grid1Tab({ initialMaterial = null, initialCorredor = "" }) {
  const [corredores, setCorredores] = useState([]);
  const [corredor, setCorredor] = useState(initialCorredor);
  const [material, setMaterial] = useState(initialMaterial);
  const [items, setItems] = useState([]);
  const [fuente, setFuente] = useState(null);
  const [loading, setLoading] = useState(false);
  const [queried, setQueried] = useState(false);
  const [agregarRow, setAgregarRow] = useState(null);
  const [backorderRow, setBackorderRow] = useState(null);
  const [descartarRow, setDescartarRow] = useState(null);
  const [toast, setToast] = useAutoDismissToast();

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
      setFuente(res.fuente || null);
    } finally {
      setLoading(false);
      setQueried(true);
    }
  }

  useEffect(() => {
    if (material) cargarGrid();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [material, corredor]);

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
          {fuente && (
            <div style={{ display: "flex", justifyContent: "flex-end", padding: "8px 12px 0" }}>
              <FuenteBadge fuente={fuente} />
            </div>
          )}
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
