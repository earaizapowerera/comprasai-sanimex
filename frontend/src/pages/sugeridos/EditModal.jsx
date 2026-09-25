import React, { useState } from "react";
import { api } from "../../lib/api.js";

export default function EditModal({ row, onClose, onSaved }) {
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
