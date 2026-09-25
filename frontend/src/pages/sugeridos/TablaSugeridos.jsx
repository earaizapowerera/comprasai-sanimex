import { coberturaSem, fmtInt, fmtMoney, tendenciaBadge } from "./formato.js";

const COLUMNAS = ["SKU", "Descripción", "ABC", "Cobertura actual → objetivo", "Cant. sugerida", "Costo est.", "Confianza IA", "Tendencia", "Capa", "Acciones"];
const COLUMNAS_NUM = new Set(["Cant. sugerida", "Costo est."]);

function BarraSeleccion({ s }) {
  const { selected, setSelected, totalMonto, tab, setApprove, selectedRows } = s;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "12px 20px",
        background: "var(--accent-soft)",
        borderBottom: "1px solid var(--border-default)",
      }}
    >
      <strong className="footnote">{selected.size} seleccionada{selected.size === 1 ? "" : "s"}</strong>
      <span className="footnote tnum text-secondary">{fmtMoney.format(totalMonto)}</span>
      <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
        <button className="btn btn--sm btn--secondary" onClick={() => setSelected(new Set())}>Limpiar</button>
        {tab === "propuesto" && (
          <>
            <button className="btn btn--sm btn--danger" onClick={() => setApprove({ rows: selectedRows, accion: "rechazar" })}>
              Rechazar
            </button>
            <button className="btn btn--sm btn--primary" onClick={() => setApprove({ rows: selectedRows, accion: "aprobar" })}>
              Aprobar
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function CeldasProducto({ r }) {
  const sem = coberturaSem(r);
  return (
    <>
      <td className="tnum">{r.material_id}</td>
      <td>
        {r.descripcion}
        <div className="caption text-tertiary">{r.plant} · {r.proveedor || "s/proveedor"}</div>
      </td>
      <td>
        <span className={`abc abc--${(r.abc || "c").toLowerCase()}`}>{r.abc}</span>
        {r.datos_decision?.categoria?.valor && (
          <div className="caption text-tertiary">{r.datos_decision.categoria.valor}</div>
        )}
      </td>
      <td>
        <span className={`sem ${sem.cls}`}>
          <span className="sem__dot" />
          {r.cobertura_actual?.toFixed?.(1) ?? r.cobertura_actual} → {r.cobertura_objetivo} meses
        </span>
      </td>
    </>
  );
}

function CeldasIndicadores({ r }) {
  const trend = tendenciaBadge(r.tendencia);
  return (
    <>
      <td className="num tnum">{fmtMoney.format(r.costo_estimado || 0)}</td>
      <td>
        <span className="ai-factor" style={{ margin: 0 }}>
          <span className="ai-factor__bar" style={{ width: 60 }}>
            <span className="ai-factor__fill" style={{ width: `${r.confianza}%` }} />
          </span>
          <span className="caption tnum">{r.confianza}%</span>
        </span>
      </td>
      <td><span className={`badge ${trend.cls}`}>{trend.icon} {trend.label}</span></td>
      <td><span className={`layer layer--${(r.capa || "c1").toLowerCase()}`}>{r.capa}</span></td>
    </>
  );
}

function FilaSugerido({ r, s }) {
  const { selected, toggleRow, tab, setEditRow, setExplainRow } = s;
  return (
    <tr
      style={{ cursor: "pointer" }}
      onClick={() => setExplainRow(r)}
      title="Ver detalle de la decisión"
    >
      <td onClick={(e) => e.stopPropagation()}>
        <input type="checkbox" checked={selected.has(r.id)} onChange={() => toggleRow(r.id)} />
      </td>
      <CeldasProducto r={r} />
      <td className="num tnum">
        {fmtInt.format(r.cantidad_final)} caj
        {tab === "propuesto" && (
          <button
            className="btn btn--ghost btn--sm"
            style={{ marginLeft: 6, height: 22, padding: "0 6px" }}
            title="Editar cantidad (requiere justificación)"
            onClick={(e) => { e.stopPropagation(); setEditRow(r); }}
          >
            ✎
          </button>
        )}
      </td>
      <CeldasIndicadores r={r} />
      <td>
        <button className="btn btn--ghost btn--sm" onClick={(e) => { e.stopPropagation(); setExplainRow(r); }}>
          Ver detalle
        </button>
      </td>
    </tr>
  );
}

function Encabezado({ s }) {
  const { rows, selected, toggleAll } = s;
  return (
    <thead>
      <tr>
        <th style={{ width: 36 }}>
          <input type="checkbox" checked={rows.length > 0 && selected.size === rows.length} onChange={toggleAll} />
        </th>
        {COLUMNAS.map((c) => <th key={c} className={COLUMNAS_NUM.has(c) ? "num" : undefined}>{c}</th>)}
      </tr>
    </thead>
  );
}

function FilasCargando() {
  return Array.from({ length: 5 }).map((_, i) => (
    <tr key={`sk-${i}`}>
      {Array.from({ length: 11 }).map((__, j) => (
        <td key={j}><div className="skeleton skeleton--text" /></td>
      ))}
    </tr>
  ));
}

function SinLineas({ tab }) {
  return (
    <div className="empty">
      <span className="empty__icon">🗂️</span>
      <p className="body" style={{ margin: 0 }}>
        {tab === "propuesto"
          ? "Sin sugeridos aún — usa los filtros y presiona “Generar sugeridos”."
          : `Sin líneas ${tab === "aprobado" ? "aprobadas" : "rechazadas"} todavía.`}
      </p>
    </div>
  );
}

/** Tabla de sugeridos con barra de selección para aprobación en lote (RF-008). */
export default function TablaSugeridos({ s }) {
  const { loadingList, generating, rows, selected, tab } = s;
  const cargando = loadingList || generating;
  return (
    <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
      <div className="card" style={{ flex: 1, padding: 0, overflow: "hidden" }}>
        {selected.size > 0 && <BarraSeleccion s={s} />}

        <div style={{ overflowX: "auto" }}>
          <table className="table">
            <Encabezado s={s} />
            <tbody>
              {cargando && <FilasCargando />}

              {!cargando && rows.map((r) => <FilaSugerido key={r.id} r={r} s={s} />)}
            </tbody>
          </table>

          {!cargando && rows.length === 0 && <SinLineas tab={tab} />}
        </div>
      </div>

    </div>
  );
}
