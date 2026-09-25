import React, { useEffect, useMemo, useRef, useState } from "react";

/** Dropdown searchable genérico (regla UX: >5 opciones => filtro por texto). */
export default function Combobox({ label, value, options, onChange, placeholder }) {
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
