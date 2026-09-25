import { useEffect, useState } from "react";
import { api } from "../../lib/api.js";
import { estadoBalanceoSem, fmtM2 } from "./balanceosFormat.js";

/** Modal "Agregar" de Grid 1: la fila donde se dio click es el ORIGEN
 * (excedente); el destino se elige entre las demás ubicaciones del grid ya
 * cargado. Prellena metros con /sugerencia-cantidad pero siempre editable
 * (spec, waykee 292187). No postea a SAP aquí — solo inserta en pendientes
 * (Grid 2). */
export default function AgregarModal({ origen, gridItems, materialId, onClose, onAdded }) {
  const destinos = gridItems.filter((g) => g.plant !== origen.plant);
  const [destinoPlant, setDestinoPlant] = useState("");
  const [metros, setMetros] = useState("");
  const [sugerencia, setSugerencia] = useState(null);
  const [loadingSug, setLoadingSug] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!destinoPlant) {
      setSugerencia(null);
      return;
    }
    let alive = true;
    setLoadingSug(true);
    api.balanceos
      .sugerenciaCantidad(materialId, origen.plant, destinoPlant)
      .then((res) => {
        if (!alive) return;
        if (res.error) {
          setError(res.error);
          setSugerencia(null);
        } else {
          setError(null);
          setSugerencia(res);
          setMetros(String(res.cantidadSugeridaMetros ?? 0));
        }
      })
      .finally(() => alive && setLoadingSug(false));
    return () => {
      alive = false;
    };
  }, [destinoPlant, materialId, origen.plant]);

  async function submit() {
    const metrosNum = Number(metros);
    if (!destinoPlant) {
      setError("Elige un destino.");
      return;
    }
    if (!metrosNum || metrosNum <= 0) {
      setError("La cantidad debe ser mayor a 0.");
      return;
    }
    const m2PorCaja = origen.m2PorCaja;
    const cajas = m2PorCaja && m2PorCaja > 0 ? metrosNum / m2PorCaja : metrosNum;
    setSaving(true);
    setError(null);
    try {
      await api.balanceos.agregarPendiente(materialId, origen.plant, destinoPlant, Number(cajas.toFixed(2)));
      onAdded();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true" aria-label="Agregar a balanceos pendientes">
        <h3 className="h3 modal__title">Agregar balanceo</h3>
        <p className="footnote text-secondary">
          Origen (exceso): <strong>{origen.nombre}</strong> ({origen.plant})
        </p>

        <label className="footnote text-secondary" style={{ display: "block", margin: "16px 0 6px" }}>
          Destino
        </label>
        <select className="input select-trigger" value={destinoPlant} onChange={(e) => setDestinoPlant(e.target.value)}>
          <option value="">Selecciona destino…</option>
          {destinos.map((d) => (
            <option key={d.plant} value={d.plant}>
              {d.nombre} ({d.plant}) · {estadoBalanceoSem(d.estado).label}
            </option>
          ))}
        </select>

        <label className="footnote text-secondary" style={{ display: "block", margin: "16px 0 6px" }}>
          Metros a transferir
        </label>
        <input
          className="input tnum"
          type="number"
          min="0"
          step="0.01"
          value={metros}
          onChange={(e) => setMetros(e.target.value)}
          disabled={loadingSug}
        />
        {loadingSug && <p className="caption text-tertiary">Calculando sugerencia…</p>}
        {sugerencia && (
          <div className="ai-explain" style={{ marginTop: 12 }}>
            <div className="ai-explain__head">
              Sugerencia: {fmtM2.format(sugerencia.cantidadSugeridaMetros)} m² ({sugerencia.fuenteTope})
            </div>
            {!sugerencia.permitidoPorPrioridad && (
              <p className="footnote" style={{ margin: "8px 0 0", color: "var(--danger-text)" }}>
                ⚠ La regla de prioridad no recomienda este traslado (prioridad origen {sugerencia.prioridadOrigen.valor}{" "}
                vs. destino {sugerencia.prioridadDestino.valor}). Puedes forzarlo editando la cantidad, pero revísalo
                antes.
              </p>
            )}
          </div>
        )}
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
            {saving ? "Agregando…" : "Agregar"}
          </button>
        </div>
      </div>
    </>
  );
}
