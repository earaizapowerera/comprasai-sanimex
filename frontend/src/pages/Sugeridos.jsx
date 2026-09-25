import { api } from "../lib/api.js";
import LotesCompra from "./sugeridos/LotesCompra.jsx";
import DecisionModal from "./sugeridos/DecisionModal.jsx";
import EditModal from "./sugeridos/EditModal.jsx";
import ApproveModal from "./sugeridos/ApproveModal.jsx";
import PanelGenerar from "./sugeridos/PanelGenerar.jsx";
import TablaSugeridos from "./sugeridos/TablaSugeridos.jsx";
import Toast from "./sugeridos/Toast.jsx";
import useSugeridos from "./sugeridos/useSugeridos.js";
import { TABS, VISTAS } from "./sugeridos/formato.js";

/** S8 Sugeridos de Compra. Estado/acciones en useSugeridos; vista en sugeridos/*. */

function Encabezado() {
  return (
    <div className="app-page-header" style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
      <div>
        <h1 className="h1 app-page-header__title">Sugeridos de Compra</h1>
        <p className="app-page-header__subtitle">
          Genera, explica y aprueba compras sugeridas — flujo Planeador → Gerente en 3 clics.
        </p>
      </div>
      <a className="btn btn--secondary" href={api.sugeridos.exportarSapUrl()} download>
        ⭳ Exportar plantilla SAP
      </a>
    </div>
  );
}

function SelectorVista({ vista, setVista }) {
  return (
    <div style={{ display: "flex", gap: 8, marginBottom: 20 }} role="tablist">
      {VISTAS.map((v) => (
        <button
          key={v.key}
          role="tab"
          aria-selected={vista === v.key}
          data-vista={v.key}
          className={`btn ${vista === v.key ? "btn--primary" : "btn--secondary"}`}
          onClick={() => setVista(v.key)}
        >
          {v.label}
        </button>
      ))}
    </div>
  );
}

function SelectorEstado({ tab, setTab }) {
  return (
    <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
      {TABS.map((t) => (
        <button
          key={t.key}
          className={`btn btn--sm ${tab === t.key ? "btn--primary" : "btn--secondary"}`}
          onClick={() => setTab(t.key)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

function Modales({ s }) {
  const { explainRow, setExplainRow, editRow, setEditRow, approve, setApprove } = s;
  return (
    <>
      {explainRow && (
        <DecisionModal
          row={explainRow}
          onClose={() => setExplainRow(null)}
          onDecidir={(r, accion) => {
            setApprove({ rows: [r], accion });
            setExplainRow(null);
          }}
        />
      )}
      {editRow && <EditModal row={editRow} onClose={() => setEditRow(null)} onSaved={s.onEditSaved} />}
      {approve && <ApproveModal rows={approve.rows} accion={approve.accion} onClose={() => setApprove(null)} onDone={s.onDecided} />}
    </>
  );
}

export default function Sugeridos() {
  const s = useSugeridos();
  return (
    <div>
      <Encabezado />
      <SelectorVista vista={s.vista} setVista={s.setVista} />

      {s.vista === "lotes" && s.toast && <Toast toast={s.toast} />}
      {s.vista === "lotes" && <LotesCompra onToast={s.setToast} />}

      {s.vista === "sugeridos" && (<>
        <PanelGenerar s={s} />
        {s.toast && <Toast toast={s.toast} />}
        <SelectorEstado tab={s.tab} setTab={s.setTab} />
        <TablaSugeridos s={s} />
      </>)}

      <Modales s={s} />
    </div>
  );
}
