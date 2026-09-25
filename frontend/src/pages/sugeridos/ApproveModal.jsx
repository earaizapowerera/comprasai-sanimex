import React, { useState } from "react";
import { api } from "../../lib/api.js";
import { fmtInt, fmtMoney } from "./formato.js";

export default function ApproveModal({ rows, accion, onClose, onDone }) {
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
