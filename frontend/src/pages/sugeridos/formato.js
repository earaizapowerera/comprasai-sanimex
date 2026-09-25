/** Constantes, formateadores y helpers puros de la pantalla Sugeridos. */

export const ETAPAS = [
  { key: "C1", label: "Reglas de negocio", detail: "Cobertura, MOQ, transferencias (RN-01/RN-02)" },
  { key: "C2", label: "Forecast", detail: "Demanda proyectada y tendencia" },
  { key: "C3", label: "Explicación", detail: "Razonamiento en lenguaje natural" },
];

// Waykee 292251: vistas de primer nivel de la pantalla.
export const VISTAS = [
  { key: "sugeridos", label: "Sugeridos" },
  { key: "lotes", label: "Lotes de Compra" },
];

export const TABS = [
  { key: "propuesto", label: "Propuestos" },
  { key: "aprobado", label: "Aprobados" },
  { key: "rechazado", label: "Rechazados" },
];

export const fmtInt = new Intl.NumberFormat("es-MX");
export const fmtMoney = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN", maximumFractionDigits: 0 });

export function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("es-MX");
}

// T25 (waykee 290148): columnas del drill-down, mismo nombre de campo que
// backorder_detalle/pedidos_compra_detalle (dataset v5, waykee 290147).
export const BACKORDER_COLUMNAS = [
  { key: "documento", label: "Doc." },
  { key: "posicion", label: "Pos." },
  { key: "cliente", label: "Cliente" },
  { key: "cantidad_pendiente", label: "Cant.", num: true, fmt: (v) => fmtInt.format(v || 0) },
  { key: "fecha_entrega_comprometida", label: "Entrega compr.", fmt: fmtDate },
];
export const PEDIDOS_COLUMNAS = [
  { key: "po", label: "PO" },
  { key: "posicion", label: "Pos." },
  { key: "proveedor", label: "Proveedor" },
  { key: "cantidad_pendiente", label: "Cant.", num: true, fmt: (v) => fmtInt.format(v || 0) },
  { key: "fecha_entrega_estimada", label: "Entrega est.", fmt: fmtDate },
];

export function coberturaSem(row) {
  const objetivo = row.cobertura_objetivo || 0;
  const ratio = objetivo > 0 ? (row.cobertura_actual || 0) / objetivo : 0;
  if ((row.cobertura_actual || 0) <= 0) return { cls: "sem--stop", label: "Sin cobertura" };
  if (ratio < 0.5) return { cls: "sem--stop", label: "Crítico" };
  if (ratio < 0.85) return { cls: "sem--warn", label: "Ajustado" };
  return { cls: "sem--ok", label: "Cerca del objetivo" };
}

export const fmtM2 = new Intl.NumberFormat("es-MX", { maximumFractionDigits: 1 });

export function m2Suffix(m2) {
  return m2 == null ? "" : ` (${fmtM2.format(m2)} m²)`;
}

// T29 (waykee 291788, punto 3): semáforo de días sin inventario -- rojo si
// hubo quiebre relevante en el mes, ámbar si fue parcial/leve, gris si no
// hay dato (sin kardex_diario ni tabla v7 para ese mes).
export function diasSinInventarioBadge(punto) {
  if (!punto || punto.dias_sin_inventario == null) {
    return { cls: "", texto: "—", titulo: "Sin dato (sin kardex para este mes)" };
  }
  const dias = punto.dias_sin_inventario;
  const titulo = punto.cobertura_parcial
    ? `${dias} día${dias === 1 ? "" : "s"} sin inventario -- cobertura parcial del mes (el kardex no cubre todo el mes)`
    : `${dias} día${dias === 1 ? "" : "s"} sin inventario de ${punto.dias_mes ?? "—"} del mes`;
  let cls = "badge--success";
  if (dias >= 10) cls = "badge--danger";
  else if (dias > 0) cls = "badge--warning";
  return { cls, texto: String(dias), titulo };
}

export function tendenciaBadge(t) {
  if (t === "alza") return { cls: "badge--accent", icon: "▲", label: "Alza" };
  if (t === "baja") return { cls: "badge--warning", icon: "▼", label: "Baja" };
  return { cls: "badge--neutral", icon: "▬", label: "Estable" };
}

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function textoGenerado(res) {
  return res.items?.length
    ? `${res.items.length} línea${res.items.length === 1 ? "" : "s"} generada${res.items.length === 1 ? "" : "s"}.`
    : res.lote?.aplicado
      ? `No hay líneas por debajo de su cobertura objetivo en las clasificaciones del lote (${res.lote.clasificaciones.join(", ") || "ninguna"}).`
      : "No hay líneas por debajo de su cobertura objetivo con estos filtros.";
}
