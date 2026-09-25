import { useEffect, useRef, useState } from "react";
import { api } from "../../lib/api.js";

/** Combobox de materiales (Grid 1): busca contra GET /api/materiales — a
 * diferencia del Combobox genérico de Sugeridos.jsx (array plano de strings),
 * aquí las opciones son objetos {material_id, descripcion, ...} traídos de
 * la API con debounce, porque el catálogo es demasiado grande para precargar. */
export default function MaterialCombobox({ value, onSelect }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(value ? `${value.material_id} — ${value.descripcion}` : "");
  const [opciones, setOpciones] = useState([]);
  const [loading, setLoading] = useState(false);
  const ref = useRef(null);
  const debounceRef = useRef(null);

  useEffect(() => {
    function onClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  useEffect(() => {
    if (!open) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setLoading(true);
      api.materiales
        .buscar(text.trim())
        .then((res) => setOpciones(res.items || []))
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(debounceRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, open]);

  return (
    <div className="combobox" ref={ref} style={{ minWidth: 320 }}>
      <label className="footnote text-secondary" style={{ display: "block", marginBottom: 6 }}>
        Material
      </label>
      <div className="select-trigger" onClick={() => setOpen(true)} role="button" tabIndex={0}>
        <input
          className="body"
          style={{ border: "none", background: "transparent", width: "100%", outline: "none", padding: 0, height: "100%" }}
          placeholder="Buscar SKU o descripción…"
          value={text}
          onFocus={() => setOpen(true)}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      {open && (
        <div className="combobox__panel">
          {loading && <div className="combobox__empty">Buscando…</div>}
          {!loading && opciones.length === 0 && <div className="combobox__empty">Sin resultados</div>}
          {!loading &&
            opciones.map((m) => (
              <div
                key={m.material_id}
                className="combobox__option"
                aria-selected={value?.material_id === m.material_id}
                onClick={() => {
                  onSelect(m);
                  setText(`${m.material_id} — ${m.descripcion}`);
                  setOpen(false);
                }}
              >
                {m.material_id} — {m.descripcion}
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
