import React, { useEffect } from "react";
import FuenteBadge from "../../components/FuenteBadge.jsx";
import useArticuloVivo from "../../hooks/useArticuloVivo.js";
import { api } from "../../lib/api.js";
import DecisionHistoria from "./DecisionHistoria.jsx";
import DrillDown from "./DrillDown.jsx";
import { BACKORDER_COLUMNAS, PEDIDOS_COLUMNAS, fmtDate, fmtInt, fmtM2, m2Suffix } from "./formato.js";

function EncabezadoDecision({ row, dd, esDecidido, onClose }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
      <div>
        <h3 className="h3 modal__title" style={{ margin: 0 }}>
          ✨ Por qué se sugiere esta cantidad{" "}
          <span className={`layer layer--${(row.capa || "c1").toLowerCase()}`}>{row.capa}</span>
        </h3>
        <p className="footnote text-secondary" style={{ marginTop: 6 }}>
          SKU {row.material_id} · {row.descripcion} · Sucursal {row.plant} · ABC {row.abc}
          {dd?.categoria && (
            <>
              {" "}· Categoría <span className="badge badge--neutral">{dd.categoria.valor}</span>
              {dd.categoria.anio_mes && ` (${dd.categoria.anio_mes})`}
            </>
          )}
        </p>
        {esDecidido && (
          <p className="footnote" style={{ marginTop: 4 }}>
            <span className={`badge ${row.estado === "aprobado" ? "badge--success" : "badge--danger"}`}>
              {row.estado === "aprobado" ? "Aprobado" : "Rechazado"}
            </span>
            {row.aprobado_por && <> · por {row.aprobado_por}</>}
            {row.actualizado && <> · {fmtDate(row.actualizado)}</>}
          </p>
        )}
      </div>
      <button type="button" className="app-icon-btn" onClick={onClose} aria-label="Cerrar">✕</button>
    </div>
  );
}

/** Posición de HOY (HANA en vivo, waykee 292300) sobre la que se muestra el
 * resumen; el valor con el que corrió el sugerido queda como referencia. */
function posicionActual(vivo, row, inv) {
  if (!vivo?.fuente?.live) return inv;
  const p = vivo.posiciones.find((x) => x.plant === row.plant) || {};
  return { disponible: p.disponible || 0, transito: p.transito || 0, comprometido: p.comprometido || 0 };
}

function AlSugerir({ actual, alSugerir }) {
  if (actual === alSugerir || alSugerir == null) return null;
  return <div className="caption text-tertiary">al sugerir: {fmtInt.format(alSugerir)} caj</div>;
}

/** Bloque de inventario/backorder/promedio arriba del histórico. */
function ResumenInventario({ row, dd, inv: invSugerido }) {
  const { data: vivo } = useArticuloVivo(row.material_id, row.plant);
  const esVivo = !!vivo?.fuente?.live;
  const inv = { ...invSugerido, ...posicionActual(vivo, row, invSugerido) };
  return (
    <div className="card card--flat" style={{ marginTop: 12, padding: 12 }}>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}>
        {vivo ? <FuenteBadge fuente={vivo.fuente} /> : <span className="caption text-tertiary">Consultando HANA…</span>}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
        <div>
          <div className="footnote text-secondary">Inventario actual</div>
          <strong className="tnum">
            {fmtInt.format(inv.disponible || 0)} caj{esVivo ? "" : m2Suffix(inv.disponible_m2)}
          </strong>
          <AlSugerir actual={inv.disponible} alSugerir={invSugerido.disponible} />
        </div>
        <div>
          <div className="footnote text-secondary">Backorder compra (tránsito)</div>
          <DrillDown
            label="Pedidos por cumplir"
            cantidad={inv.transito || 0}
            cargar={() => api.sugeridos.pedidosDetalle(row.material_id, row.plant)}
            columnas={PEDIDOS_COLUMNAS}
          />
          {!esVivo && inv.transito_m2 != null && <div className="caption text-tertiary">{fmtM2.format(inv.transito_m2)} m²</div>}
          <AlSugerir actual={inv.transito} alSugerir={invSugerido.transito} />
        </div>
        <div>
          <div className="footnote text-secondary">Backorder traslado (por salir)</div>
          <DrillDown
            label="Backorder"
            cantidad={inv.comprometido || 0}
            cargar={() => api.sugeridos.backorderDetalle(row.material_id, row.plant)}
            columnas={BACKORDER_COLUMNAS}
          />
          {!esVivo && inv.comprometido_m2 != null && <div className="caption text-tertiary">{fmtM2.format(inv.comprometido_m2)} m²</div>}
          <AlSugerir actual={inv.comprometido} alSugerir={invSugerido.comprometido} />
        </div>
        <div>
          <div className="footnote text-secondary">PROMEDIO general</div>
          <strong className="tnum">
            {fmtInt.format(dd.promedio_general || 0)} caj/mes{m2Suffix(dd.promedio_general_m2)}
          </strong>
        </div>
        <div>
          <div className="footnote text-secondary">Meses actual</div>
          <strong className="tnum">{(dd.meses_actual ?? 0).toFixed(2)}</strong>
        </div>
        <div>
          <div className="footnote text-secondary">Meses objetivo</div>
          <strong className="tnum">{dd.meses_objetivo?.valor ?? row.cobertura_objetivo ?? "—"}</strong>
          {dd.meses_objetivo?.fuente === "excepcion" && (
            <span className="badge badge--accent" style={{ marginLeft: 6, height: "auto", padding: "1px 6px" }}>
              Excepción
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/** Cadena Meses Objetivo -> Compra Sugerida -> Redondeo a Pallets -> Compra
 * Definitiva, más el bloque de proveedor. */
function CalculoCompra({ row, dd, inv, compra, trans, prov }) {
  return (
    <>
      <div style={{ marginTop: 14 }}>
        <div className="footnote text-secondary" style={{ marginBottom: 4 }}>Cálculo de compra</div>
        <div className="footnote">
          Meses objetivo <strong className="tnum">{dd.meses_objetivo?.valor ?? "—"}</strong> × Promedio general{" "}
          <strong className="tnum">{fmtInt.format(dd.promedio_general || 0)}</strong> − Inventario{" "}
          <strong className="tnum">{fmtInt.format(inv.disponible || 0)}</strong> − Tránsito{" "}
          <strong className="tnum">{fmtInt.format(inv.transito || 0)}</strong> = Compra sugerida{" "}
          <strong className="tnum">{fmtInt.format(compra.compra_sugerida_cajas || 0)}</strong> caj{" "}
          ({fmtInt.format(compra.compra_sugerida_m2 || 0)} m²)
        </div>
        <div className="caption text-tertiary" style={{ marginTop: 2 }}>
          El backorder traslado ({fmtInt.format(inv.comprometido || 0)} caj) no se suma a esta fórmula — no es
          demanda pendiente, es mercancía por salir de la sucursal (ver detalle arriba).
        </div>
        {trans.cantidad_transferir > 0 && (
          <div className="footnote" style={{ marginTop: 4, color: "var(--text-secondary)" }}>
            − {fmtInt.format(trans.cantidad_transferir)} cajas por transferencia (RN-02):{" "}
            {(trans.detalle_transferencias || []).map((d) => `${d.desde_plant} (${fmtInt.format(d.cantidad)})`).join(", ")}
          </div>
        )}
        <div className="footnote" style={{ marginTop: 4 }}>
          Redondeo a pallets: <strong className="tnum">{fmtInt.format(compra.n_pallets || 0)}</strong> pallet{compra.n_pallets === 1 ? "" : "s"} ×{" "}
          <strong className="tnum">{compra.cajas_por_pallet ?? "—"}</strong> caj/pallet
        </div>
        <div
          className="footnote"
          style={{ marginTop: 8, padding: "8px 12px", background: "var(--accent-soft)", borderRadius: 6, fontWeight: "var(--fw-semibold)" }}
        >
          COMPRA DEFINITIVA: {fmtInt.format(compra.cantidad_final_cajas ?? row.cantidad_final)} caj ({fmtInt.format(compra.cantidad_final_m2 || 0)} m²)
        </div>
        {compra.motivo && <div className="caption text-tertiary" style={{ marginTop: 2 }}>{compra.motivo}</div>}
      </div>

      <div style={{ marginTop: 14 }}>
        <div className="footnote text-secondary" style={{ marginBottom: 4 }}>Proveedor</div>
        <div className="footnote">
          {prov.nombre || "s/proveedor"} · MOQ {prov.moq_cajas ?? "—"} caj · Pallet {prov.cajas_por_pallet ?? "—"} caj · Lead time {prov.lead_time_dias ?? "—"} días
        </div>
      </div>
    </>
  );
}

/** T28 (waykee 291765, replanteo del motor de 3 promedios): popup rediseñado
 * para calcar la hoja de compras en Excel que usa el planeador -- bloque de
 * inventario/backorder/promedio arriba, tabla histórica Consumo/Promedio 1/2/3
 * con marcas de qué mes entra a cada promedio, y la cadena
 * Meses Objetivo → Compra Sugerida → Redondeo a Pallets → Compra Definitiva
 * abajo. Consume `datos_decision` en su forma actual (`historia`,
 * `promedio_general`, `meses_actual`, `compra`, `inventario`) -- reemplaza el
 * shape viejo (`demanda_promedio_3m`, `redondeo`, `faltante_bruto`) que ya no
 * devuelve el backend. Se abre al hacer click en cualquier parte del renglón,
 * en las 3 pestañas (Propuestos/Aprobados/Rechazados); en Aprobados/Rechazados
 * se oculta Aceptar/Descartar y se muestra el estado en el encabezado. */
export default function DecisionModal({ row, onClose, onDecidir }) {
  useEffect(() => {
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!row) return null;
  const dd = row.datos_decision;
  const tieneDatosDecision = !!(dd && Object.keys(dd).length > 0);
  const inv = dd?.inventario || {};
  const prov = dd?.proveedor || {};
  const compra = dd?.compra || {};
  const trans = dd?.transferencia || { cantidad_transferir: row.cantidad_transferir, detalle_transferencias: row.detalle_transferencias };
  const hist = dd?.historia || { meses: [], consumo: [], promedio_1: {}, promedio_2: {}, promedio_3: {} };
  const esDecidido = row.estado && row.estado !== "propuesto";

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="modal modal--lg" role="dialog" aria-modal="true" aria-label="Detalle de la decisión sugerida">
        <EncabezadoDecision row={row} dd={dd} esDecidido={esDecidido} onClose={onClose} />

        <p className="body" style={{ marginTop: 12, marginBottom: 0 }}>{row.explicacion}</p>

        {inv.sobrevendido && (
          <div className="footnote" style={{ marginTop: 10, color: "var(--danger-text)", fontWeight: "var(--fw-semibold)" }}>
            Al generar el sugerido, el backorder traslado ({fmtInt.format(inv.comprometido || 0)} caj) excedía el inventario + tránsito disponible por{" "}
            {fmtInt.format(Math.abs(inv.disponible_neto))} cajas.
          </div>
        )}

        {tieneDatosDecision ? (
          <>
            <ResumenInventario row={row} dd={dd} inv={inv} />
            <DecisionHistoria dd={dd} hist={hist} />
            <CalculoCompra row={row} dd={dd} inv={inv} compra={compra} trans={trans} prov={prov} />
          </>
        ) : (
          row.detalle_transferencias && row.detalle_transferencias.length > 0 && (
            <div className="footnote" style={{ marginTop: 12, color: "var(--text-secondary)" }}>
              Transferencias: {row.detalle_transferencias.map((d) => `${d.desde_plant} (${fmtInt.format(d.cantidad)})`).join(", ")}
            </div>
          )
        )}

        <div className="footnote text-tertiary" style={{ marginTop: 12 }}>
          SKU {row.material_id} · Sucursal {row.plant} · Confianza IA {row.confianza}%
        </div>
        <div className="modal__actions">
          <button className="btn btn--ghost" onClick={onClose}>Cerrar</button>
          {!esDecidido && (
            <>
              <button className="btn btn--danger" onClick={() => onDecidir(row, "rechazar")}>Descartar</button>
              <button className="btn btn--primary" onClick={() => onDecidir(row, "aprobar")}>Aceptar</button>
            </>
          )}
        </div>
      </div>
    </>
  );
}
