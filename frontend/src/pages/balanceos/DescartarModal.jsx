import { useState } from "react";
import { api } from "../../lib/api.js";

/** Modal "Descartar" (snooze) de Grid 1: pregunta cuántos días descartar
 * la sugerencia antes de volver a mostrarla (spec, waykee 292187). */
export default function DescartarModal({ materialId, row, onClose, onDone }) {
  const [dias, setDias] = useState(30);
  const [motivo, setMotivo] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function submit() {
    if (!dias || Number(dias) <= 0) {
      setError("Ingresa un número de días mayor a 0.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.balanceos.descartar(materialId, row.plant, Number(dias), motivo.trim() || undefined);
      onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true" aria-label="Descartar sugerencia de balanceo">
        <h3 className="h3 modal__title">Descartar sugerencia</h3>
        <p className="footnote text-secondary">
          {row.nombre} ({row.plant}) — no se volverá a sugerir hasta que expire.
        </p>
        <label className="footnote text-secondary" style={{ display: "block", margin: "16px 0 6px" }}>
          Días a descartar
        </label>
        <input className="input tnum" type="number" min="1" value={dias} onChange={(e) => setDias(e.target.value)} />
        <label className="footnote text-secondary" style={{ display: "block", margin: "16px 0 6px" }}>
          Motivo (opcional)
        </label>
        <textarea
          className="input"
          style={{ height: 72, paddingTop: 10, resize: "vertical" }}
          value={motivo}
          onChange={(e) => setMotivo(e.target.value)}
          placeholder="Ej. Ya se colocó pedido urgente con el proveedor…"
        />
        {error && (
          <p className="footnote" style={{ color: "var(--danger-text)", marginTop: 8 }}>
            {error}
          </p>
        )}
        <div className="modal__actions">
          <button className="btn btn--ghost" onClick={onClose} disabled={saving}>
            Cancelar
          </button>
          <button className="btn btn--primary" onClick={submit} disabled={saving}>
            {saving ? "Guardando…" : "Descartar"}
          </button>
        </div>
      </div>
    </>
  );
}
