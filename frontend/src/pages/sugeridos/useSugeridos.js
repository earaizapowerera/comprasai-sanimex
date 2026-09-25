import { useEffect, useState } from "react";
import { api } from "../../lib/api.js";
import { fmtMoney, sleep, textoGenerado } from "./formato.js";

/** Estado y acciones de la pantalla Sugeridos de Compra. Las acciones reciben
 * `s` (estado + setters del render actual), igual que las funciones internas
 * del componente original cerraban sobre el estado de su render. */

function useToast() {
  const [toast, setToast] = useState(null);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);
  return [toast, setToast];
}

function useSeleccion(rows) {
  const [selected, setSelected] = useState(() => new Set());

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

  return { selected, setSelected, toggleRow, toggleAll };
}

async function loadTab(s, t) {
  s.setLoadingList(true);
  s.setSelected(new Set());
  try {
    const res = await api.sugeridos.lista({ estado: t });
    s.setRows(res.items || []);
  } catch (e) {
    s.setToast({ kind: "danger", text: e.message });
  } finally {
    s.setLoadingList(false);
  }
}

async function generar(s) {
  s.setGenerating(true);
  s.setStage(0);
  s.setSelected(new Set());
  s.setExplainRow(null);
  try {
    await sleep(420);
    s.setStage(1);
    await sleep(420);
    s.setStage(2);
    const res = await api.sugeridos.generar({ ...s.filtros, fecha: s.fecha });
    if (res.lote) s.setLoteInfo(res.lote);
    await sleep(280);
    s.setRows(res.items || []);
    s.setHasGenerated(true);
    s.setTab("propuesto");
    s.setToast({ kind: res.items?.length ? "success" : "neutral", text: textoGenerado(res) });
  } catch (e) {
    s.setToast({ kind: "danger", text: e.message });
  } finally {
    s.setGenerating(false);
    s.setStage(-1);
  }
}

function onEditSaved(s, id, cantidad_final, costo_estimado, justificacion) {
  s.setRows((prev) => prev.map((r) => (r.id === id ? { ...r, cantidad_final, costo_estimado, justificacion_edicion: justificacion } : r)));
  s.setEditRow(null);
  s.setToast({ kind: "success", text: "Cantidad actualizada." });
}

function onDecided(s, res) {
  const affected = new Set(res.items.map((i) => i.id));
  s.setRows((prev) => prev.filter((r) => !affected.has(r.id)));
  s.setSelected(new Set());
  s.setApprove(null);
  s.setExplainRow(null);
  s.setToast({
    kind: "success",
    text: `${res.afectados} línea${res.afectados === 1 ? "" : "s"} ${res.estado} · ${fmtMoney.format(res.monto_total)}`,
  });
}

function useEstado() {
  const [opciones, setOpciones] = useState({ familias: [], proveedores: [], corredores: [] });
  const [filtros, setFiltros] = useState({ familia: "", proveedor: "", corredor: "" });
  const [tab, setTab] = useState("propuesto");
  const [rows, setRows] = useState([]);
  const [loadingList, setLoadingList] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [stage, setStage] = useState(-1);
  const [explainRow, setExplainRow] = useState(null);
  const [editRow, setEditRow] = useState(null);
  const [approve, setApprove] = useState(null); // { rows, accion }
  const [hasGenerated, setHasGenerated] = useState(false);
  const [vista, setVista] = useState("sugeridos");
  const [fecha, setFecha] = useState(() => new Date().toISOString().slice(0, 10));
  const [loteInfo, setLoteInfo] = useState(null);
  return {
    opciones, setOpciones, filtros, setFiltros, tab, setTab, rows, setRows,
    loadingList, setLoadingList, generating, setGenerating, stage, setStage,
    explainRow, setExplainRow, editRow, setEditRow, approve, setApprove,
    hasGenerated, setHasGenerated, vista, setVista, fecha, setFecha, loteInfo, setLoteInfo,
  };
}

export default function useSugeridos() {
  const s = useEstado();
  Object.assign(s, useSeleccion(s.rows));

  // Waykee 292251: lote vigente a la fecha elegida (informativo antes de generar).
  useEffect(() => {
    if (s.vista !== "sugeridos" || !s.fecha) return;
    api.sugeridos.lotes.vigentes(s.fecha).then(s.setLoteInfo).catch(() => s.setLoteInfo(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.fecha, s.vista]);

  useEffect(() => {
    api.sugeridos.opciones().then(s.setOpciones).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!s.hasGenerated || s.tab !== "propuesto") {
      loadTab(s, s.tab);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.tab]);

  const [toast, setToast] = useToast();
  s.toast = toast;
  s.setToast = setToast;

  s.generar = () => generar(s);
  s.onEditSaved = (...args) => onEditSaved(s, ...args);
  s.onDecided = (res) => onDecided(s, res);
  s.selectedRows = s.rows.filter((r) => s.selected.has(r.id));
  s.totalMonto = s.selectedRows.reduce((sum, r) => sum + (r.costo_estimado || 0), 0);
  return s;
}
