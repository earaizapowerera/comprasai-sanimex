import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../lib/api.js";

// Waykee 292251: Lotes de Compra -- por rango de fechas, qué clasificaciones
// comerciales (REM, PET52, OUTLET01...) entran al motor de Sugeridos. Si
// ningún lote activo cubre la fecha, Sugeridos no filtra (flujo previo).

function hoyIso() {
  return new Date().toISOString().slice(0, 10);
}

function rangoMesActual() {
  const d = new Date();
  const ini = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1));
  const fin = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0));
  return { fecha_inicio: ini.toISOString().slice(0, 10), fecha_fin: fin.toISOString().slice(0, 10) };
}

function estadoLote(lote, hoy) {
  if (!lote.activo) return { cls: "badge--neutral", label: "Inactivo" };
  if (hoy < lote.fecha_inicio) return { cls: "badge--accent", label: "Programado" };
  if (hoy > lote.fecha_fin) return { cls: "badge--neutral", label: "Vencido" };
  return { cls: "badge--success", label: "Vigente hoy" };
}

/** Selector searchable (regla UX >5 opciones) que agrega UNA clasificación;
 * excluye las que el lote ya tiene. */
function ClasificacionPicker({ catalogo, excluir, onPick }) {
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

  const opciones = useMemo(() => {
    const q = text.trim().toLowerCase();
    return catalogo.filter((c) => !excluir.includes(c.clasificacion) && (!q || c.clasificacion.toLowerCase().includes(q)));
  }, [catalogo, excluir, text]);

  return (
    <div className="combobox" ref={ref} style={{ minWidth: 220 }}>
      <input
        className="input"
        placeholder="＋ Agregar clasificación…"
        value={text}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
        }}
        aria-label="Agregar clasificación"
      />
      {open && (
        <div className="combobox__panel">
          {opciones.length === 0 && <div className="combobox__empty">Sin resultados</div>}
          {opciones.map((c) => (
            <div
              key={c.clasificacion}
              className="combobox__option"
              data-clasificacion={c.clasificacion}
              onClick={() => {
                onPick(c.clasificacion);
                setText("");
                setOpen(false);
              }}
              style={{ display: "flex", justifyContent: "space-between", gap: 12 }}
            >
              <span>{c.clasificacion}</span>
              <span className="caption text-tertiary tnum">{c.materiales_mes} mat.</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Chip({ label, onRemove, disabled }) {
  return (
    <span className="badge badge--accent" style={{ gap: 6 }} data-chip={label}>
      {label}
      <button
        className="btn btn--ghost btn--sm"
        style={{ height: 18, padding: "0 4px", minWidth: 0 }}
        onClick={onRemove}
        disabled={disabled}
        aria-label={`Quitar ${label}`}
        title={`Quitar ${label}`}
      >
        ✕
      </button>
    </span>
  );
}

function LoteRow({ lote, catalogo, hoy, onChange, onDelete, busy }) {
  const est = estadoLote(lote, hoy);
  const [fechas, setFechas] = useState({ fecha_inicio: lote.fecha_inicio, fecha_fin: lote.fecha_fin });
  useEffect(() => setFechas({ fecha_inicio: lote.fecha_inicio, fecha_fin: lote.fecha_fin }), [lote.fecha_inicio, lote.fecha_fin]);

  function guardarFecha(campo, valor) {
    const next = { ...fechas, [campo]: valor };
    setFechas(next);
    if (valor && next.fecha_inicio <= next.fecha_fin) onChange(lote.id, next);
  }

  return (
    <tr data-lote-id={lote.id}>
      <td>
        <strong className="footnote">{lote.nombre}</strong>
        <div style={{ marginTop: 4 }}>
          <span className={`badge ${est.cls}`}>{est.label}</span>
        </div>
      </td>
      <td>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="date" className="input" style={{ width: 150 }} value={fechas.fecha_inicio} max={fechas.fecha_fin}
            onChange={(e) => guardarFecha("fecha_inicio", e.target.value)} disabled={busy} aria-label="Fecha inicio" />
          <span className="text-tertiary">→</span>
          <input type="date" className="input" style={{ width: 150 }} value={fechas.fecha_fin} min={fechas.fecha_inicio}
            onChange={(e) => guardarFecha("fecha_fin", e.target.value)} disabled={busy} aria-label="Fecha fin" />
        </div>
      </td>
      <td>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
          {lote.clasificaciones.length === 0 && (
            <span className="caption text-tertiary">⚠ Sin clasificaciones: en este rango no se sugiere nada</span>
          )}
          {lote.clasificaciones.map((c) => (
            <Chip key={c} label={c} disabled={busy}
              onRemove={() => onChange(lote.id, { clasificaciones: lote.clasificaciones.filter((x) => x !== c) })} />
          ))}
          <ClasificacionPicker catalogo={catalogo} excluir={lote.clasificaciones}
            onPick={(c) => onChange(lote.id, { clasificaciones: [...lote.clasificaciones, c] })} />
        </div>
      </td>
      <td style={{ whiteSpace: "nowrap" }}>
        <label className="footnote" style={{ display: "inline-flex", gap: 6, alignItems: "center", marginRight: 12 }}>
          <input type="checkbox" checked={lote.activo} disabled={busy}
            onChange={(e) => onChange(lote.id, { activo: e.target.checked })} />
          Activo
        </label>
        <button className="btn btn--sm btn--danger" disabled={busy} onClick={() => onDelete(lote)}>Borrar</button>
      </td>
    </tr>
  );
}

function NuevoLoteForm({ catalogo, onCreate, busy }) {
  const [form, setForm] = useState(() => ({ nombre: "", ...rangoMesActual(), clasificaciones: [] }));
  const valido = form.fecha_inicio && form.fecha_fin && form.fecha_inicio <= form.fecha_fin;

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <h3 className="h4" style={{ marginTop: 0 }}>Nuevo lote</h3>
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: "var(--space-4)", alignItems: "end" }}>
        <div>
          <label className="footnote text-secondary" style={{ display: "block", marginBottom: 6 }}>Nombre (opcional)</label>
          <input className="input" value={form.nombre} placeholder="Ej. Promoción octubre"
            onChange={(e) => setForm((f) => ({ ...f, nombre: e.target.value }))} />
        </div>
        <div>
          <label className="footnote text-secondary" style={{ display: "block", marginBottom: 6 }}>Desde</label>
          <input type="date" className="input" value={form.fecha_inicio}
            onChange={(e) => setForm((f) => ({ ...f, fecha_inicio: e.target.value }))} aria-label="Nuevo desde" />
        </div>
        <div>
          <label className="footnote text-secondary" style={{ display: "block", marginBottom: 6 }}>Hasta</label>
          <input type="date" className="input" value={form.fecha_fin}
            onChange={(e) => setForm((f) => ({ ...f, fecha_fin: e.target.value }))} aria-label="Nuevo hasta" />
        </div>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", marginTop: 16 }}>
        {form.clasificaciones.map((c) => (
          <Chip key={c} label={c}
            onRemove={() => setForm((f) => ({ ...f, clasificaciones: f.clasificaciones.filter((x) => x !== c) }))} />
        ))}
        <ClasificacionPicker catalogo={catalogo} excluir={form.clasificaciones}
          onPick={(c) => setForm((f) => ({ ...f, clasificaciones: [...f.clasificaciones, c] }))} />
        <button className="btn btn--primary" style={{ marginLeft: "auto" }} disabled={!valido || busy}
          onClick={() => onCreate(form).then(() => setForm({ nombre: "", ...rangoMesActual(), clasificaciones: [] }))}>
          Crear lote
        </button>
      </div>
      {!valido && <p className="caption" style={{ color: "var(--danger-text)", margin: "8px 0 0" }}>⚠ La fecha final debe ser igual o posterior a la inicial.</p>}
    </div>
  );
}

export default function LotesCompra({ onToast }) {
  const [lotes, setLotes] = useState([]);
  const [catalogo, setCatalogo] = useState({ anio_mes: null, items: [] });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const hoy = hoyIso();

  async function recargar() {
    const res = await api.sugeridos.lotes.lista();
    setLotes(res.items || []);
  }

  useEffect(() => {
    Promise.all([recargar(), api.sugeridos.lotes.clasificaciones().then(setCatalogo)])
      .catch((e) => onToast({ kind: "danger", text: e.message }))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function ejecutar(fn, okText) {
    setBusy(true);
    try {
      await fn();
      await recargar();
      if (okText) onToast({ kind: "success", text: okText });
    } catch (e) {
      onToast({ kind: "danger", text: e.message });
    } finally {
      setBusy(false);
    }
  }

  const crear = (form) => ejecutar(() => api.sugeridos.lotes.crear(form), "Lote creado.");
  const actualizar = (id, cambios) => ejecutar(() => api.sugeridos.lotes.actualizar(id, cambios), "Lote actualizado.");
  const borrar = (lote) => {
    if (!window.confirm(`¿Borrar el lote "${lote.nombre}"?`)) return;
    ejecutar(() => api.sugeridos.lotes.borrar(lote.id), "Lote borrado.");
  };

  return (
    <div>
      <p className="footnote text-secondary" style={{ marginTop: 0 }}>
        Define qué clasificaciones entran a Sugeridos en cada rango de fechas. Al generar, solo se consideran materiales cuya
        clasificación del mes esté en un lote <strong>activo</strong> que cubra la fecha. Si ningún lote cubre la fecha, no se filtra.
        {catalogo.anio_mes && <> Conteo de materiales por clasificación al mes <strong>{catalogo.anio_mes}</strong>.</>}
      </p>

      <NuevoLoteForm catalogo={catalogo.items} onCreate={crear} busy={busy} />

      <div className="card" style={{ padding: 0, overflow: "visible" }}>
        <table className="table" data-testid="tabla-lotes">
          <thead>
            <tr>
              <th>Lote</th>
              <th>Rango de fechas</th>
              <th>Clasificaciones habilitadas</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={4}><div className="skeleton skeleton--text" /></td></tr>
            )}
            {!loading && lotes.length === 0 && (
              <tr><td colSpan={4} className="footnote text-tertiary">Sin lotes: Sugeridos considera todas las clasificaciones.</td></tr>
            )}
            {lotes.map((l) => (
              <LoteRow key={l.id} lote={l} catalogo={catalogo.items} hoy={hoy} onChange={actualizar} onDelete={borrar} busy={busy} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
