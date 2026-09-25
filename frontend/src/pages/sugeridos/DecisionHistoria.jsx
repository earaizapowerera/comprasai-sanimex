import React from "react";
import { diasSinInventarioBadge, fmtDate, fmtInt, fmtM2 } from "./formato.js";

function FilaDiasSinInventario({ dd, hist }) {
  return (
    <tr>
      <td className="footnote text-secondary" title="Días del mes con saldo de inventario en cero (fuente: kardex diario)">
        Días sin inventario
      </td>
      {hist.meses.map((m, i) => {
        const punto = dd.inventario_fin_mes?.[i];
        const b = diasSinInventarioBadge(punto);
        return (
          <td key={m} className="num" title={b.titulo}>
            {b.cls ? <span className={`badge ${b.cls}`} style={{ height: "auto", padding: "1px 6px" }}>{b.texto}</span> : b.texto}
          </td>
        );
      })}
    </tr>
  );
}

function FilaPromedio2({ hist }) {
  return (
    <tr>
      <td className="footnote text-secondary" title="Promedio de los últimos 2 meses">Promedio 2</td>
      {hist.meses.map((m, i) => {
        const incluido = !!hist.promedio_2?.incluidos?.[i];
        return (
          <td key={m} className="num tnum" style={{ opacity: incluido ? 1 : 0.35, fontWeight: incluido ? "var(--fw-semibold)" : "normal" }}>
            {incluido ? fmtInt.format(hist.consumo[i]) : "—"}
          </td>
        );
      })}
    </tr>
  );
}

function FilaPromedio3({ hist }) {
  return (
    <tr>
      <td className="footnote text-secondary" title="Promedio de los 5 meses restando la venta mayor de cada mes">Promedio 3</td>
      {hist.meses.map((m, i) => {
        const ajuste = hist.promedio_3?.ajustes?.[i];
        const tieneAjuste = !!ajuste && (ajuste.ajuste_cajas || 0) > 0;
        const titulo = tieneAjuste
          ? `Se resta la venta mayor: ${fmtInt.format(ajuste.ajuste_cajas)} caj${ajuste.fecha_pico ? ` el ${fmtDate(ajuste.fecha_pico)}` : ""}`
          : "Sin ajuste (no hubo venta atípica que restar)";
        return (
          <td key={m} className="num tnum" title={titulo}>
            {fmtInt.format(ajuste?.valor_ajustado ?? hist.consumo[i])}
            {tieneAjuste && <sup style={{ marginLeft: 2 }}>−{fmtInt.format(ajuste.ajuste_cajas)}</sup>}
          </td>
        );
      })}
    </tr>
  );
}

function PieHistoria({ dd, hist }) {
  return (
    <tfoot>
      <tr>
        <td className="footnote text-secondary">→ Promedio 1</td>
        <td className="num tnum" colSpan={hist.meses.length}>{fmtInt.format(hist.promedio_1?.valor || 0)}</td>
      </tr>
      <tr>
        <td className="footnote text-secondary">→ Promedio 2</td>
        <td className="num tnum" colSpan={hist.meses.length}>{fmtInt.format(hist.promedio_2?.valor || 0)}</td>
      </tr>
      <tr>
        <td className="footnote text-secondary">→ Promedio 3</td>
        <td className="num tnum" colSpan={hist.meses.length}>{fmtInt.format(hist.promedio_3?.valor || 0)}</td>
      </tr>
      <tr style={{ background: "var(--accent-soft)" }}>
        <td className="footnote" style={{ fontWeight: "var(--fw-semibold)" }}>PROMEDIO GENERAL</td>
        <td className="num tnum" colSpan={hist.meses.length} style={{ fontWeight: "var(--fw-semibold)" }}>
          {fmtInt.format(dd.promedio_general || 0)}
        </td>
      </tr>
    </tfoot>
  );
}

/** Tabla histórica Consumo/Promedio 1/2/3 del popup de decisión (T28, waykee
 * 291765), con marcas de qué mes entra a cada promedio. */
export default function DecisionHistoria({ dd, hist }) {
  return (
    <div style={{ marginTop: 14 }}>
      <div className="footnote text-secondary" style={{ marginBottom: 4 }}>
        Histórico de consumo y promedios (cajas), {dd.meses_con_venta ?? "—"}/{dd.meses_historia ?? hist.meses.length} meses con venta
      </div>
      <table className="table table--compact">
        <thead>
          <tr>
            <th></th>
            {hist.meses.map((m) => <th key={m} className="num">{m}</th>)}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="footnote text-secondary">Consumo (caj)</td>
            {hist.consumo.map((v, i) => (
              <td key={hist.meses[i]} className="num tnum">{fmtInt.format(v)}</td>
            ))}
          </tr>
          <tr>
            <td className="footnote text-secondary">Consumo (m²)</td>
            {(hist.consumo_m2 || []).map((v, i) => (
              <td key={hist.meses[i]} className="num tnum text-tertiary">{v == null ? "—" : fmtM2.format(v)}</td>
            ))}
          </tr>
          <FilaDiasSinInventario dd={dd} hist={hist} />
          <tr>
            <td className="footnote text-secondary" title={`Promedio simple de los ${hist.meses.length} meses`}>
              Promedio 1
            </td>
            {hist.meses.map((m, i) => <td key={m} className="num tnum" style={{ opacity: 0.55 }}>{fmtInt.format(hist.consumo[i])}</td>)}
          </tr>
          <FilaPromedio2 hist={hist} />
          <FilaPromedio3 hist={hist} />
        </tbody>
        <PieHistoria dd={dd} hist={hist} />
      </table>
    </div>
  );
}
