"""RN-02: transferencia antes que compra, dentro del mismo corredor."""

from __future__ import annotations

from .calculos import calc_cobertura_meses
from .demanda import ContextoDemanda


def construir_info_por_linea(candidatos: list, demanda: ContextoDemanda) -> dict:
    """Info por (material,plant) para resolver transferencias intra-corredor (RN-02)."""
    info_por_linea = {}
    for r in candidatos:
        key = (r["material_id"], r["plant"])
        disp_neto = round((r["disponible"] or 0) + (r["transito"] or 0) - (r["comprometido"] or 0), 2)
        promedios = demanda.promedios_linea(r["material_id"], r["plant"], r["m2_por_caja"])
        dem = promedios["promedio_general"]
        cobertura = calc_cobertura_meses(disp_neto, dem)
        info_por_linea[key] = {
            "row": r,
            "disponible_neto": disp_neto,
            "demanda_mensual": dem,
            "cobertura": cobertura,
            "promedios": promedios,
        }
    return info_por_linea


class AsignadorTransferencias:
    def __init__(self, info_por_linea: dict):
        self.info_por_linea = info_por_linea
        # Índice material+corredor -> lista de plants, precomputado UNA vez.
        # Antes cada línea deficitaria escaneaba TODO info_por_linea buscando a
        # sus hermanos de corredor (O(n²): con el universo sin filtrar, ~9.8k
        # líneas deficitarias x ~18k pares = ~180M iteraciones en Python puro,
        # >2 min por request) -> bajo concurrencia esto es lo que realmente
        # agotaba el busy_timeout de SQLite y producía "database is locked",
        # no solo el volumen de INSERTs. Con el índice, cada línea solo mira a
        # sus hermanos reales (O(1) promedio).
        self.plants_por_material_corredor: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for k, v in info_por_linea.items():
            corredor_h = v["row"]["corredor"]
            if corredor_h:
                self.plants_por_material_corredor.setdefault((k[0], corredor_h), []).append(k)
        # RN-02: remanente transferible por (material_id, plant) ORIGEN. Se
        # inicializa perezosamente con el excedente total de esa línea y se
        # DECREMENTA cada vez que una línea deficitaria lo consume. Sin esto,
        # cada línea deficitaria recalculaba el excedente completo del hermano
        # desde cero -> el mismo excedente se prometía varias veces a distintos
        # destinos (sobre-asignación detectada por QA 23-ago, ver waykee 290102).
        self.remanente_transferible: dict[tuple[str, str], float] = {}

    def _excedente_disponible(self, material_id: str, plant: str) -> float:
        key = (material_id, plant)
        if key not in self.remanente_transferible:
            info_origen = self.info_por_linea.get(key)
            if (
                info_origen
                and info_origen["cobertura"] is not None
                and info_origen["cobertura"] > info_origen["row"]["meses_objetivo"]
            ):
                self.remanente_transferible[key] = round(
                    (info_origen["cobertura"] - info_origen["row"]["meses_objetivo"]) * info_origen["demanda_mensual"],
                    2,
                )
            else:
                self.remanente_transferible[key] = 0.0
        return self.remanente_transferible[key]

    def asignar(self, r, compra_sugerida: float) -> tuple[float, list[dict]]:
        """Consume excedente de los hermanos de corredor (mayor excedente
        primero) hasta cubrir `compra_sugerida`. Devuelve (cantidad, detalle)."""
        cantidad_transferir = 0.0
        detalle_transferencias = []
        if not r["corredor"]:
            return cantidad_transferir, detalle_transferencias
        hermanos_keys = [
            k for k in self.plants_por_material_corredor.get((r["material_id"], r["corredor"]), [])
            if k[1] != r["plant"]
        ]
        hermanos_keys.sort(key=lambda k: -self._excedente_disponible(*k))
        restante = compra_sugerida
        for h_material, h_plant in hermanos_keys:
            if restante <= 0:
                break
            disponible = self._excedente_disponible(h_material, h_plant)
            if disponible <= 0:
                continue
            usar = min(disponible, restante)
            cantidad_transferir += usar
            restante -= usar
            self.remanente_transferible[(h_material, h_plant)] = round(disponible - usar, 2)
            detalle_transferencias.append({"desde_plant": h_plant, "cantidad": round(usar, 2)})
        return round(cantidad_transferir, 2), detalle_transferencias
