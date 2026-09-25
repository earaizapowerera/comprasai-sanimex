// Formateadores y semáforo compartidos por las vistas de Balanceos.
export const fmtInt = new Intl.NumberFormat("es-MX");
export const fmtM2 = new Intl.NumberFormat("es-MX", { maximumFractionDigits: 1 });
export const fmtMeses = new Intl.NumberFormat("es-MX", { maximumFractionDigits: 2 });

export function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("es-MX");
}

// Mismos umbrales que estado_semaforo_balanceo (balanceos.py) / COBERTURA_CTE.
// No hay .sem--info ni .sem--neutral definidas en components.css: exceso y
// sin_dato reusan sem--ok / sin clase en vez de referenciar clases inexistentes.
export function estadoBalanceoSem(estado) {
  switch (estado) {
    case "quiebre":
      return { cls: "sem--stop", label: "Quiebre" };
    case "riesgo":
      return { cls: "sem--warn", label: "Riesgo" };
    case "exceso":
      return { cls: "sem--ok", label: "Exceso" };
    case "sin_dato":
      return { cls: "", label: "Sin dato" };
    default:
      return { cls: "sem--ok", label: "OK" };
  }
}
