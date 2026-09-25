"""Evaluación de UNA línea material+plant candidata: RN-01, compra sugerida,
RN-02, redondeo a pallet, explicación C3 y payload datos_decision."""

from __future__ import annotations

from typing import Optional

from .calculos import calc_cobertura_meses, calc_compra_sugerida, calc_redondeo_pallets_completos
from .cargas import _categoria_para_linea
from .constantes import DEFAULT_PALLET, MESES_HISTORIA
from .datos_decision import build_datos_decision
from .demanda import ContextoDemanda
from .estadistica import calc_confianza, calc_tendencia
from .series import _fusionar_dias_sin_inventario_tabla, _saldos_fin_mes, calc_dias_sin_inventario_por_mes
from .transferencias import AsignadorTransferencias


def evaluar_linea(r, info: dict, demanda: ContextoDemanda, asignador: AsignadorTransferencias,
                  tabla_categorias: dict, solo_criticos: bool) -> Optional[dict]:
    """None cuando la línea no genera sugerido (RN-01 o filtro de críticos)."""
    cobertura = info["cobertura"]
    objetivo = r["meses_objetivo"]
    if cobertura is None:
        return None  # sin demanda reciente: no hay base para sugerir (ni RN-01 aplica)
    if cobertura >= objetivo:
        return None  # RN-01: cobertura ya cubre el objetivo, SUGERIDO=0
    if solo_criticos and cobertura > 0:
        return None

    c = _cantidades(r, info, asignador)
    serie_pts = demanda.serie.get((r["material_id"], r["plant"]), [])[-MESES_HISTORIA:]
    c["tendencia"] = calc_tendencia([v for _, v in serie_pts])
    c["meses_con_venta"] = sum(1 for _, v in serie_pts if v > 0)
    c["confianza"] = calc_confianza(c["meses_con_venta"], MESES_HISTORIA)
    c["capa"] = "C3" if (c["cantidad_transferir"] > 0 or c["cantidad_final"] != c["cantidad_comprar_bruta"]) else "C2"
    c["costo_unitario"] = r["costo"] or 0
    c["costo_estimado"] = round(c["cantidad_final"] * c["costo_unitario"], 2)
    c["explicacion"] = _explicacion(r, info, c)
    datos_decision = _datos_decision(r, info, demanda, tabla_categorias, c)
    return _item(r, cobertura, objetivo, c, datos_decision)


def _cantidades(r, info: dict, asignador: AsignadorTransferencias) -> dict:
    # T28 (waykee 291765): compra sugerida = fórmula del Excel de compras
    # (MesesObjetivo x PROMEDIO_GENERAL - Disponible - Tránsito,
    # sin netear de antemano -- ver calc_compra_sugerida), NO el faltante de
    # cobertura*demanda de la versión anterior. La cobertura sigue viniendo
    # de calc_cobertura_meses (RN-01, disponible_neto/dem) para decidir SI
    # se sugiere; el MONTO ya no depende de ese neteo.
    # T29 (waykee 291788, punto 4): 'comprometido' YA NO participa en el
    # MONTO -- ver docstring de calc_compra_sugerida.
    compra_sugerida = calc_compra_sugerida(
        r["meses_objetivo"], info["demanda_mensual"], r["disponible"], r["transito"]
    )
    # RN-02: transferencia antes que compra, dentro del mismo corredor.
    cantidad_transferir, detalle_transferencias = asignador.asignar(r, compra_sugerida)
    cantidad_comprar_bruta = round(max(0.0, compra_sugerida - cantidad_transferir), 2)
    # T28: redondeo SOLO a pallet completo (sin MOQ -- el Excel de compras
    # no aplica mínimo de proveedor, solo múltiplo de pallet).
    cantidad_final = calc_redondeo_pallets_completos(cantidad_comprar_bruta, int(r["cajas_por_pallet"]))
    cajas_por_pallet_int = int(r["cajas_por_pallet"]) or DEFAULT_PALLET
    n_pallets = cantidad_final // cajas_por_pallet_int if cajas_por_pallet_int else 0
    return {
        "compra_sugerida": compra_sugerida,
        "cantidad_transferir": cantidad_transferir,
        "detalle_transferencias": detalle_transferencias,
        "cantidad_comprar_bruta": cantidad_comprar_bruta,
        "cantidad_final": cantidad_final,
        "cajas_por_pallet_int": cajas_por_pallet_int,
        "n_pallets": n_pallets,
    }


def _explicacion(r, info: dict, c: dict) -> str:
    dem = info["demanda_mensual"]
    partes = [
        f"Cobertura actual {info['cobertura']:.1f} meses vs objetivo {r['meses_objetivo']:.1f} meses "
        f"(PROMEDIO general {dem:.0f} cajas/mes, disponible neto {info['disponible_neto']:.0f} cajas)."
    ]
    if c["cantidad_transferir"] > 0:
        origenes = ", ".join(f"{d['desde_plant']} ({d['cantidad']:.0f})" for d in c["detalle_transferencias"])
        partes.append(f"Se cubren {c['cantidad_transferir']:.0f} cajas por transferencia desde {origenes} antes de comprar (RN-02).")
    if c["cantidad_comprar_bruta"] > 0:
        partes.append(f"Faltante a comprar: {c['cantidad_comprar_bruta']:.0f} cajas, redondeado a {c['cantidad_final']} cajas ({c['n_pallets']} pallet(s) de {c['cajas_por_pallet_int']}) del proveedor {r['proveedor'] or 's/proveedor'}.")
    if c["tendencia"] == "alza":
        partes.append("La demanda muestra tendencia al alza en el último mes.")
    elif c["tendencia"] == "baja":
        partes.append("La demanda muestra tendencia a la baja en el último mes.")
    return " ".join(partes)


def _dias_sin_inventario(r, demanda: ContextoDemanda) -> dict:
    key = (r["material_id"], r["plant"])
    if demanda.kardex_disponible:
        dias = calc_dias_sin_inventario_por_mes(demanda.kardex_por_linea.get(key, []), demanda.meses_display)
    else:
        # Sin kardex_diario: "sin dato" (None), no "cero días de quiebre"
        # -- mismo criterio que saldo=None en _saldos_fin_mes.
        dias = {
            mes: {"dias": None, "dias_con_dato": None, "dias_mes": None, "cobertura_parcial": None}
            for mes in demanda.meses_display
        }
    if demanda.tabla_dsi:
        dias = _fusionar_dias_sin_inventario_tabla(dias, demanda.tabla_dsi, r["material_id"], r["plant"])
    return dias


def _datos_decision(r, info: dict, demanda: ContextoDemanda, tabla_categorias: dict, c: dict) -> dict:
    key = (r["material_id"], r["plant"])
    promedios = info["promedios"]
    return build_datos_decision(
        historia_meses=demanda.meses_display,
        historia_consumo=promedios["consumo"],
        promedio_1=promedios["promedio_1"],
        promedio_2=promedios["promedio_2"],
        promedio_3=promedios["promedio_3"],
        promedio_3_ajustes=promedios["promedio_3_ajustes"],
        promedio_general=info["demanda_mensual"],
        meses_actual=calc_cobertura_meses(r["disponible"] or 0.0, info["demanda_mensual"]),
        meses_con_venta=c["meses_con_venta"],
        meses_historia=MESES_HISTORIA,
        inventario_fin_mes=_saldos_fin_mes(demanda.kardex_por_linea.get(key, []), demanda.meses_display),
        kardex_disponible=demanda.kardex_disponible,
        dias_sin_inventario=_dias_sin_inventario(r, demanda),
        disponible=r["disponible"],
        transito=r["transito"],
        comprometido=r["comprometido"],
        disponible_neto=info["disponible_neto"],
        cobertura_actual=info["cobertura"],
        meses_objetivo=r["meses_objetivo"],
        meses_objetivo_fuente=r["meses_objetivo_fuente"],
        compra_sugerida=c["compra_sugerida"],
        proveedor=r["proveedor"],
        moq_cajas=int(r["moq_cajas"]),
        cajas_por_pallet=c["cajas_por_pallet_int"],
        lead_time_dias=r["lead_time_dias"],
        m2_por_caja=r["m2_por_caja"],
        costo_unitario=c["costo_unitario"],
        cantidad_transferir=c["cantidad_transferir"],
        detalle_transferencias=c["detalle_transferencias"],
        cantidad_comprar_bruta=c["cantidad_comprar_bruta"],
        cantidad_final=c["cantidad_final"],
        n_pallets=c["n_pallets"],
        categoria=_categoria_para_linea(tabla_categorias, r["material_id"], demanda.mes_ref),
    )


def _item(r, cobertura: float, objetivo: float, c: dict, datos_decision: dict) -> dict:
    return {
        "material_id": r["material_id"],
        "descripcion": r["descripcion"],
        "abc": r["abc"],
        "plant": r["plant"],
        "corredor": r["corredor"],
        "proveedor": r["proveedor"],
        "cobertura_actual": round(cobertura, 2),
        "cobertura_objetivo": objetivo,
        "cantidad_transferir": c["cantidad_transferir"],
        "detalle_transferencias": c["detalle_transferencias"],
        "cantidad_comprar_bruta": c["cantidad_comprar_bruta"],
        "cantidad_final": c["cantidad_final"],
        "moq_cajas": r["moq_cajas"],
        "costo_estimado": c["costo_estimado"],
        "confianza": c["confianza"],
        "tendencia": c["tendencia"],
        "capa": c["capa"],
        "explicacion": c["explicacion"],
        "datos_decision": datos_decision,
        "_faltante_bruto": c["compra_sugerida"],
        "_costo_unitario": c["costo_unitario"],
    }
