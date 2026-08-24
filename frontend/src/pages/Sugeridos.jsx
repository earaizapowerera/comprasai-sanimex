import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api.js";

const ETAPAS = [
  { key: "C1", label: "Reglas de negocio", detail: "Cobertura, MOQ, transferencias (RN-01/RN-02)" },
  { key: "C2", label: "Forecast", detail: "Demanda proyectada y tendencia" },
  { key: "C3", label: "Explicación", detail: "Razonamiento en lenguaje natural" },
];

const TABS = [
  { key: "propuesto", label: "Propuestos" },
  { key: "aprobado", label: "Aprobados" },
  { key: "rechazado", label: "Rechazados" },
];

const fmtInt = new Intl.NumberFormat("es-MX");
const fmtMoney = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN", maximumFractionDigits: 0 });

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("es-MX");
}

// T25 (waykee 290148): columnas del drill-down, mismo nombre de campo que
// backorder_detalle/pedidos_compra_detalle (dataset v5, waykee 290147).
const BACKORDER_COLUMNAS = [
  { key: "documento", label: "Doc." },
  { key: "posicion", label: "Pos." },
  { key: "cliente", label: "Cliente" },
  { key: "cantidad_pendiente", label: "Cant.", num: true, fmt: (v) => fmtInt.format(v || 0) },
  { key: "fecha_entrega_comprometida", label: "Entrega compr.", fmt: fmtDate },
];
const PEDIDOS_COLUMNAS = [
  { key: "po", label: "PO" },
  { key: "posicion", label: "Pos." },
  { key: "proveedor", label: "Proveedor" },
  { key: "cantidad_pendiente", label: "Cant.", num: true, fmt: (v) => fmtInt.format(v || 0) },
  { key: "fecha_entrega_estimada", label: "Entrega est.", fmt: fmtDate },
];

function comprarDe(row) {
  return row.cantidad_comprar_bruta ?? row.cantidad_comprar ?? 0;
}

function coberturaSem(row) {
  const objetivo = row.cobertura_objetivo || 0;
  const ratio = objetivo > 0 ? (row.cobertura_actual || 0) / objetivo : 0;
  if ((row.cobertura_actual || 0) <= 0) return { cls: "sem--stop", label: "Sin cobertura" };
  if (ratio < 0.5) return { cls: "sem--stop", label: "Crítico" };
  if (ratio < 0.85) return { cls: "sem--warn", label: "Ajustado" };
  return { cls: "sem--ok", label: "Cerca del objetivo" };
}

function tendenciaBadge(t) {
  if (t === "alza") return { cls: "badge--accent", icon: "▲", label: "Alza" };
  if (t === "baja") return { cls: "badge--warning", icon: "▼", label: "Baja" };
  return { cls: "badge--neutral", icon: "▬", label: "Estable" };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Dropdown searchable genérico (regla UX: >5 opciones => filtro por texto). */
function Combobox({ label, value, options, onChange, placeholder }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const ref = useRef(null);

  useEffect(() => {
    function onClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const filtered = useMemo(() => {
    const q = text.trim().toLowerCase();
    const base = options || [];
    return q ? base.filter((o) => o.toLowerCase().includes(q)) : base;
  }, [options, text]);

  return (
    <div className="combobox" ref={ref}>
      <label className="footnote text-secondary" style={{ display: "block", marginBottom: 6 }}>
        {label}
      </label>
      <div className="select-trigger" onClick={() => setOpen(true)} role="button" tabIndex={0}>
        <input
          className="body"
          style={{ border: "none", background: "transparent", width: "100%", outline: "none", padding: 0, height: "100%" }}
          placeholder={placeholder || "Todos"}
          value={open ? text : value || ""}
          onFocus={() => setOpen(true)}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      {open && (
        <div className="combobox__panel">
          <div
            className="combobox__option"
            aria-selected={!value}
            onClick={() => {
              onChange("");
              setText("");
              setOpen(false);
            }}
          >
            Todos
          </div>
          {filtered.length === 0 && <div className="combobox__empty">Sin resultados</div>}
          {filtered.map((opt) => (
            <div
              key={opt}
              className="combobox__option"
              aria-selected={opt === value}
              onClick={() => {
                onChange(opt);
                setText("");
                setOpen(false);
              }}
            >
              {opt}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** T19 (waykee 290116): la explicación mostraba una lista "factores" con
 * pesos hardcodeados (40/25/15/10/10) que no salían de ningún cálculo real.
 * Ahora se muestran los datos REALES que entraron en la fórmula del backend
 * (datos_decision): serie de demanda, desglose de inventario, fórmula
 * cobertura→faltante→redondeo, y el detalle de transferencias RN-02.
 *
 * T25 (waykee 290148): feedback directo de Enrique -- la explicación no era
 * coherente porque no mostraba los datos que un humano usaría para decidir.
 * Se agrega: (1) marca visual de qué meses entran al promedio de 3, con
 * espacio ya reservado para los que T21 excluya por desabasto; (2) fila de
 * inventario fin de mes (kardex_diario, "disponible próximamente" mientras
 * T20 no aterriza); (3) comprometido/pedidos-por-cumplir clickeables con
 * drill-down documento a documento (T25/waykee 290147, "en camino" mientras
 * la tabla no exista). */
function SerieYInventarioTabla({ dd }) {
  const serie = dd?.serie_demanda;
  if (!serie || serie.length === 0) return null;
  const inventarioPorMes = new Map((dd.inventario_fin_mes || []).map((p) => [p.anio_mes, p.saldo]));
  const excluidosDesabasto = new Set(dd.meses_excluidos_desabasto || []);

  return (
    <div style={{ marginTop: 14 }}>
      <div className="footnote text-secondary" style={{ marginBottom: 4 }}>
        Ventas e inventario, últimos {serie.length} meses
      </div>
      <table className="table table--compact">
        <thead>
          <tr>
            <th></th>
            {serie.map((p) => {
              const excluido = excluidosDesabasto.has(p.anio_mes);
              const incluido = p.incluido_promedio_3m && !excluido;
              return (
                <th
                  key={p.anio_mes}
                  className="num"
                  style={{ opacity: incluido ? 1 : 0.55 }}
                  title={
                    excluido
                      ? "Excluido del promedio por desabasto (RN próxima, T21)"
                      : p.incluido_promedio_3m
                      ? `Incluido en el promedio de ${dd.meses_demanda ?? 3} meses`
                      : `Fuera de la ventana del promedio de ${dd.meses_demanda ?? 3} meses`
                  }
                >
                  {p.anio_mes}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="footnote text-secondary">Ventas (caj)</td>
            {serie.map((p) => {
              const excluido = excluidosDesabasto.has(p.anio_mes);
              const incluido = p.incluido_promedio_3m && !excluido;
              return (
                <td
                  key={p.anio_mes}
                  className="num tnum"
                  style={{ opacity: incluido ? 1 : 0.55, fontWeight: incluido ? "var(--fw-semibold)" : "normal" }}
                >
                  {fmtInt.format(p.cajas)}
                  {incluido && <sup style={{ marginLeft: 2 }}>●</sup>}
                </td>
              );
            })}
          </tr>
          <tr>
            <td className="footnote text-secondary">Inv. fin de mes</td>
            {serie.map((p) => {
              const saldo = inventarioPorMes.get(p.anio_mes);
              return (
                <td key={p.anio_mes} className="num tnum">
                  {saldo === undefined || saldo === null ? (
                    <span className="text-tertiary" title="kardex_diario aún no disponible en este dataset (T20)">—</span>
                  ) : (
                    fmtInt.format(saldo)
                  )}
                </td>
              );
            })}
          </tr>
        </tbody>
      </table>
      <div className="caption text-tertiary" style={{ marginTop: 2 }}>
        ● entra al promedio de {dd.meses_demanda ?? 3} meses usado para cobertura/faltante.
        {dd.kardex_disponible === false && " Inventario fin de mes: disponible próximamente (kardex_diario en extracción, T20)."}
      </div>
    </div>
  );
}

/** T25 (waykee 290148): botón que expande el detalle documento-a-documento
 * (backorder) o PO-a-PO (pedidos por cumplir) bajo demanda -- no se precarga
 * para no pegarle a la API por cada línea de la tabla. */
function DrillDown({ label, cantidad, cargar, columnas }) {
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

function ExplainPanel({ row, onClose }) {
  if (!row) return null;
  const dd = row.datos_decision;
  const tieneDatosDecision = !!(dd && Object.keys(dd).length > 0);
  const inv = dd?.inventario || {};
  const prov = dd?.proveedor || {};
  const red = dd?.redondeo || {};
  const trans = dd?.transferencia || { cantidad_transferir: row.cantidad_transferir, detalle_transferencias: row.detalle_transferencias };

  return (
    <aside className="card card--elevated" style={{ position: "sticky", top: 84, alignSelf: "flex-start", width: 400, flexShrink: 0 }}>
      <div className="ai-explain">
        <div className="ai-explain__head">
          ✨ Por qué se sugiere esta cantidad
          <span className={`layer layer--${(row.capa || "c1").toLowerCase()}`}>{row.capa}</span>
        </div>
        <p className="body" style={{ marginTop: 12, marginBottom: 0 }}>{row.explicacion}</p>

        {inv.sobrevendido && (
          <div className="footnote" style={{ marginTop: 10, color: "var(--danger-text)", fontWeight: "var(--fw-semibold)" }}>
            ⚠ Sobrevendido {fmtInt.format(Math.abs(inv.disponible_neto))} cajas (comprometido excede stock)
          </div>
        )}

        {tieneDatosDecision ? (
          <>
            <SerieYInventarioTabla dd={dd} />
            <div className="caption text-tertiary" style={{ marginTop: 2 }}>
              Promedio {dd.meses_demanda ?? 3}m: {fmtInt.format(dd.demanda_promedio_3m || 0)} caj/mes · {dd.meses_con_venta ?? "—"}/{dd.meses_historia ?? 6} meses con venta
            </div>

            <div style={{ marginTop: 14 }}>
              <div className="footnote text-secondary" style={{ marginBottom: 4 }}>Inventario (cajas)</div>
              <div className="footnote" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                <span>Disponible: <strong className="tnum">{fmtInt.format(inv.disponible || 0)}</strong></span>
                <span>
                  Pedidos por cumplir:{" "}
                  <DrillDown
                    label="Pedidos por cumplir"
                    cantidad={inv.transito || 0}
                    cargar={() => api.sugeridos.pedidosDetalle(row.material_id, row.plant)}
                    columnas={PEDIDOS_COLUMNAS}
                  />
                </span>
                <span>
                  Comprometido:{" "}
                  <DrillDown
                    label="Backorder"
                    cantidad={inv.comprometido || 0}
                    cargar={() => api.sugeridos.backorderDetalle(row.material_id, row.plant)}
                    columnas={BACKORDER_COLUMNAS}
                  />
                </span>
                <span>Neto: <strong className="tnum">{fmtInt.format(inv.disponible_neto || 0)}</strong></span>
              </div>
            </div>

            <div style={{ marginTop: 14 }}>
              <div className="footnote text-secondary" style={{ marginBottom: 4 }}>Fórmula</div>
              <div className="footnote">
                Promedio <strong className="tnum">{fmtInt.format(dd.demanda_promedio_3m || 0)}</strong> caj/mes → cobertura actual{" "}
                <strong className="tnum">{dd.cobertura_actual?.toFixed?.(1) ?? "—"}</strong> vs objetivo{" "}
                <strong className="tnum">{dd.meses_objetivo ?? "—"}</strong> meses → faltante{" "}
                <strong className="tnum">{fmtInt.format(dd.faltante_bruto || 0)}</strong> cajas
              </div>
              {trans.cantidad_transferir > 0 && (
                <div className="footnote" style={{ marginTop: 4, color: "var(--text-secondary)" }}>
                  − {fmtInt.format(trans.cantidad_transferir)} cajas por transferencia (RN-02):{" "}
                  {(trans.detalle_transferencias || []).map((d) => `${d.desde_plant} (${fmtInt.format(d.cantidad)})`).join(", ")}
                </div>
              )}
              <div className="footnote" style={{ marginTop: 4 }}>
                Compra bruta <strong className="tnum">{fmtInt.format(red.cantidad_comprar_bruta || 0)}</strong> → final{" "}
                <strong className="tnum">{fmtInt.format(red.cantidad_final ?? row.cantidad_final)}</strong> cajas (MOQ/pallet)
              </div>
              {red.motivo && <div className="caption text-tertiary" style={{ marginTop: 2 }}>{red.motivo}</div>}
            </div>

            <div style={{ marginTop: 14 }}>
              <div className="footnote text-secondary" style={{ marginBottom: 4 }}>Proveedor</div>
              <div className="footnote">
                {prov.nombre || "s/proveedor"} · MOQ {prov.moq_cajas ?? "—"} caj · Pallet {prov.cajas_por_pallet ?? "—"} caj · Lead time {prov.lead_time_dias ?? "—"} días
              </div>
            </div>
          </>
        ) : (
          row.detalle_transferencias && row.detalle_transferencias.length > 0 && (
            <div className="footnote" style={{ marginTop: 12, color: "var(--text-secondary)" }}>
              Transferencias: {row.detalle_transferencias.map((d) => `${d.desde_plant} (${fmtInt.format(d.cantidad)})`).join(", ")}
            </div>
          )
        )}
      </div>
      <div className="footnote text-tertiary" style={{ marginTop: 12 }}>
        SKU {row.material_id} · Sucursal {row.plant} · Confianza IA {row.confianza}%
      </div>
      <button className="btn btn--ghost btn--sm" style={{ marginTop: 12, width: "100%" }} onClick={onClose}>
        Cerrar
      </button>
    </aside>
  );
}

function EditModal({ row, onClose, onSaved }) {
  const [cantidad, setCantidad] = useState(row.cantidad_final);
  const [justificacion, setJustificacion] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function submit() {
    if (justificacion.trim().length < 5) {
      setError("La justificación debe tener al menos 5 caracteres (RN-08).");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await api.sugeridos.editar(row.id, Number(cantidad), justificacion.trim());
      onSaved(row.id, res.cantidad_final, res.costo_estimado, justificacion.trim());
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true">
        <h3 className="h3 modal__title">Editar cantidad sugerida</h3>
        <p className="footnote text-secondary">
          SKU {row.material_id} · {row.descripcion} · Sucursal {row.plant}
        </p>
        <label className="footnote text-secondary" style={{ display: "block", margin: "16px 0 6px" }}>
          Cantidad final (cajas)
        </label>
        <input
          className="input tnum"
          type="number"
          min="0"
          value={cantidad}
          onChange={(e) => setCantidad(e.target.value)}
        />
        <label className="footnote text-secondary" style={{ display: "block", margin: "16px 0 6px" }}>
          Justificación del cambio (obligatoria)
        </label>
        <textarea
          className="input"
          style={{ height: 88, paddingTop: 10, resize: "vertical" }}
          placeholder="Ej. Ajuste por promoción confirmada con el proveedor la próxima semana…"
          value={justificacion}
          onChange={(e) => setJustificacion(e.target.value)}
        />
        {error && <p className="footnote" style={{ color: "var(--danger-text)", marginTop: 8 }}>{error}</p>}
        <div className="modal__actions">
          <button className="btn btn--ghost" onClick={onClose} disabled={saving}>Cancelar</button>
          <button className="btn btn--primary" onClick={submit} disabled={saving}>
            {saving ? "Guardando…" : "Guardar cambio"}
          </button>
        </div>
      </div>
    </>
  );
}

function ApproveModal({ rows, accion, onClose, onDone }) {
  const [aprobadoPor, setAprobadoPor] = useState("Gerente Demo");
  const [confirmado, setConfirmado] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const total = rows.reduce((sum, r) => sum + (r.costo_estimado || 0), 0);
  const esAprobar = accion === "aprobar";

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      const res = await api.sugeridos.decidir(rows.map((r) => r.id), accion, aprobadoPor.trim() || "Gerente Demo");
      onDone(res);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true">
        <h3 className="h3 modal__title">{esAprobar ? "Aprobar sugeridos" : "Rechazar sugeridos"}</h3>
        <p className="footnote text-secondary">
          {rows.length} línea{rows.length === 1 ? "" : "s"} · Monto total{" "}
          <strong className="tnum">{fmtMoney.format(total)}</strong>
        </p>
        <div className="card card--flat" style={{ maxHeight: 200, overflowY: "auto", padding: 12, marginTop: 12 }}>
          {rows.map((r) => (
            <div key={r.id} className="footnote" style={{ display: "flex", justifyContent: "space-between", padding: "4px 0" }}>
              <span>{r.material_id} · {r.plant}</span>
              <span className="tnum">{fmtInt.format(r.cantidad_final)} caj · {fmtMoney.format(r.costo_estimado || 0)}</span>
            </div>
          ))}
        </div>
        {esAprobar && (
          <>
            <label className="footnote text-secondary" style={{ display: "block", margin: "16px 0 6px" }}>
              Aprobado por
            </label>
            <input className="input" value={aprobadoPor} onChange={(e) => setAprobadoPor(e.target.value)} />
          </>
        )}
        <label className="footnote" style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 16, cursor: "pointer" }}>
          <input type="checkbox" checked={confirmado} onChange={(e) => setConfirmado(e.target.checked)} />
          Confirmo que revisé estas líneas y su monto antes de {esAprobar ? "aprobar" : "rechazar"}.
        </label>
        {error && <p className="footnote" style={{ color: "var(--danger-text)", marginTop: 8 }}>{error}</p>}
        <div className="modal__actions">
          <button className="btn btn--ghost" onClick={onClose} disabled={saving}>Cancelar</button>
          <button
            className={esAprobar ? "btn btn--primary" : "btn btn--danger"}
            onClick={submit}
            disabled={saving || !confirmado}
          >
            {saving ? "Procesando…" : esAprobar ? "Confirmar aprobación" : "Confirmar rechazo"}
          </button>
        </div>
      </div>
    </>
  );
}

export default function Sugeridos() {
  const [opciones, setOpciones] = useState({ familias: [], proveedores: [], corredores: [] });
  const [filtros, setFiltros] = useState({ familia: "", proveedor: "", corredor: "" });
  const [tab, setTab] = useState("propuesto");
  const [rows, setRows] = useState([]);
  const [loadingList, setLoadingList] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [stage, setStage] = useState(-1);
  const [selected, setSelected] = useState(() => new Set());
  const [explainRow, setExplainRow] = useState(null);
  const [editRow, setEditRow] = useState(null);
  const [approve, setApprove] = useState(null); // { rows, accion }
  const [toast, setToast] = useState(null);
  const [hasGenerated, setHasGenerated] = useState(false);

  useEffect(() => {
    api.sugeridos.opciones().then(setOpciones).catch(() => {});
  }, []);

  useEffect(() => {
    if (!hasGenerated || tab !== "propuesto") {
      loadTab(tab);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  async function loadTab(t) {
    setLoadingList(true);
    setSelected(new Set());
    try {
      const res = await api.sugeridos.lista({ estado: t });
      setRows(res.items || []);
    } catch (e) {
      setToast({ kind: "danger", text: e.message });
    } finally {
      setLoadingList(false);
    }
  }

  async function generar() {
    setGenerating(true);
    setStage(0);
    setSelected(new Set());
    setExplainRow(null);
    try {
      await sleep(420);
      setStage(1);
      await sleep(420);
      setStage(2);
      const res = await api.sugeridos.generar(filtros);
      await sleep(280);
      setRows(res.items || []);
      setHasGenerated(true);
      setTab("propuesto");
      setToast({
        kind: res.items?.length ? "success" : "neutral",
        text: res.items?.length
          ? `${res.items.length} línea${res.items.length === 1 ? "" : "s"} generada${res.items.length === 1 ? "" : "s"}.`
          : "No hay líneas por debajo de su cobertura objetivo con estos filtros.",
      });
    } catch (e) {
      setToast({ kind: "danger", text: e.message });
    } finally {
      setGenerating(false);
      setStage(-1);
    }
  }

  function toggleRow(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected((prev) => (prev.size === rows.length ? new Set() : new Set(rows.map((r) => r.id))));
  }

  function onEditSaved(id, cantidad_final, costo_estimado, justificacion) {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, cantidad_final, costo_estimado, justificacion_edicion: justificacion } : r)));
    setEditRow(null);
    setToast({ kind: "success", text: "Cantidad actualizada." });
  }

  function onDecided(res) {
    const affected = new Set(res.items.map((i) => i.id));
    setRows((prev) => prev.filter((r) => !affected.has(r.id)));
    setSelected(new Set());
    setApprove(null);
    setExplainRow(null);
    setToast({
      kind: "success",
      text: `${res.afectados} línea${res.afectados === 1 ? "" : "s"} ${res.estado} · ${fmtMoney.format(res.monto_total)}`,
    });
  }

  const selectedRows = rows.filter((r) => selected.has(r.id));
  const totalMonto = selectedRows.reduce((sum, r) => sum + (r.costo_estimado || 0), 0);

  return (
    <div>
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

      <div className="card" style={{ marginBottom: 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gap: "var(--space-4)", alignItems: "end" }}>
          <div style={{ gridColumn: "span 3" }}>
            <Combobox label="Familia" value={filtros.familia} options={opciones.familias} onChange={(v) => setFiltros((f) => ({ ...f, familia: v }))} />
          </div>
          <div style={{ gridColumn: "span 3" }}>
            <Combobox label="Proveedor" value={filtros.proveedor} options={opciones.proveedores} onChange={(v) => setFiltros((f) => ({ ...f, proveedor: v }))} />
          </div>
          <div style={{ gridColumn: "span 3" }}>
            <Combobox label="Corredor" value={filtros.corredor} options={opciones.corredores} onChange={(v) => setFiltros((f) => ({ ...f, corredor: v }))} />
          </div>
          <div style={{ gridColumn: "span 3" }}>
            <button className="btn btn--ai btn--lg" style={{ width: "100%" }} onClick={generar} disabled={generating}>
              {generating ? "Generando…" : "✨ Generar sugeridos"}
            </button>
          </div>
        </div>

        {generating && (
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
        )}
      </div>

      {toast && (
        <div
          className={`badge badge--${toast.kind === "danger" ? "danger" : toast.kind === "success" ? "success" : "neutral"}`}
          style={{ marginBottom: 16, height: "auto", padding: "8px 14px", display: "block" }}
        >
          {toast.text}
        </div>
      )}

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

      <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
        <div className="card" style={{ flex: 1, padding: 0, overflow: "hidden" }}>
          {selected.size > 0 && (
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
          )}

          <div style={{ overflowX: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: 36 }}>
                    <input type="checkbox" checked={rows.length > 0 && selected.size === rows.length} onChange={toggleAll} />
                  </th>
                  <th>SKU</th>
                  <th>Descripción</th>
                  <th>ABC</th>
                  <th>Cobertura actual → objetivo</th>
                  <th className="num">Cant. sugerida</th>
                  <th className="num">Costo est.</th>
                  <th>Confianza IA</th>
                  <th>Tendencia</th>
                  <th>Capa</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {(loadingList || generating) &&
                  Array.from({ length: 5 }).map((_, i) => (
                    <tr key={`sk-${i}`}>
                      {Array.from({ length: 11 }).map((__, j) => (
                        <td key={j}><div className="skeleton skeleton--text" /></td>
                      ))}
                    </tr>
                  ))}

                {!loadingList && !generating && rows.map((r) => {
                  const sem = coberturaSem(r);
                  const trend = tendenciaBadge(r.tendencia);
                  return (
                    <tr key={r.id}>
                      <td><input type="checkbox" checked={selected.has(r.id)} onChange={() => toggleRow(r.id)} /></td>
                      <td className="tnum">{r.material_id}</td>
                      <td>
                        {r.descripcion}
                        <div className="caption text-tertiary">{r.plant} · {r.proveedor || "s/proveedor"}</div>
                      </td>
                      <td><span className={`abc abc--${(r.abc || "c").toLowerCase()}`}>{r.abc}</span></td>
                      <td>
                        <span className={`sem ${sem.cls}`}>
                          <span className="sem__dot" />
                          {r.cobertura_actual?.toFixed?.(1) ?? r.cobertura_actual} → {r.cobertura_objetivo} meses
                        </span>
                      </td>
                      <td className="num tnum">
                        {fmtInt.format(r.cantidad_final)} caj
                        {tab === "propuesto" && (
                          <button
                            className="btn btn--ghost btn--sm"
                            style={{ marginLeft: 6, height: 22, padding: "0 6px" }}
                            title="Editar cantidad (requiere justificación)"
                            onClick={() => setEditRow(r)}
                          >
                            ✎
                          </button>
                        )}
                      </td>
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
                      <td>
                        <button className="btn btn--ghost btn--sm" onClick={() => setExplainRow(r)}>Ver explicación</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {!loadingList && !generating && rows.length === 0 && (
              <div className="empty">
                <span className="empty__icon">🗂️</span>
                <p className="body" style={{ margin: 0 }}>
                  {tab === "propuesto"
                    ? "Sin sugeridos aún — usa los filtros y presiona “Generar sugeridos”."
                    : `Sin líneas ${tab === "aprobado" ? "aprobadas" : "rechazadas"} todavía.`}
                </p>
              </div>
            )}
          </div>
        </div>

        {explainRow && <ExplainPanel row={explainRow} onClose={() => setExplainRow(null)} />}
      </div>

      {editRow && <EditModal row={editRow} onClose={() => setEditRow(null)} onSaved={onEditSaved} />}
      {approve && <ApproveModal rows={approve.rows} accion={approve.accion} onClose={() => setApprove(null)} onDone={onDecided} />}
    </div>
  );
}
