/**
 * Motor de reglas C1 (deterministas) para Balanceos & Remates — espejo en
 * frontend de la lógica que T4 implementa en backend/motores_c1.py.
 *
 * Fuente de verdad de negocio: minuta GAM confirmada por el PM (waykee 290066,
 * hilo T14-QA, msg 61809) —
 *   Escalas de remate (precio/caja según cajas remanentes en la línea):
 *     1-3   -> $70   (liquida en sitio)
 *     4-10  -> $80   (liquida en sitio)
 *     11-14 -> $120  (se traslada)
 *     15-30 -> $140  (se traslada)
 *   Excepciones de precio:
 *     Económico + cajas >= 30  -> $120/caja DIRECTO a remate (rompe la escala)
 *     No-económico + cajas > 30 -> $140/caja (extensión del último rango;
 *       SIN respaldo explícito en la minuta — marcar como supuesto a validar)
 *   Ruteo por organización (solo aplica si se traslada, i.e. cajas >= 11 y NO
 *   es plaza de excepción):
 *     GAM  -> Sucursal -> CEDIS del corredor -> Sucursal de remate
 *     GSA  -> todo a R1
 *     SA   -> todo a Tienda 4
 *     GAMN -> remata en la misma plaza (sin traslado)
 *   Plazas de excepción (rematan SIEMPRE en sitio, sin traslado):
 *     Juchitán, Tlapa, San Andrés, Cd. Valles, Putla, Toluca
 *
 * Este archivo NO llama red ni tiene estado — son funciones puras para que
 * T4 pueda usarlas como referencia 1:1 al portar a Python (ver golden cases
 * G9-G12 de QA en waykee 290102, msg 61807).
 */

export const ESCALAS_REMATE = [
  { min: 1, max: 3, precio: 70 },
  { min: 4, max: 10, precio: 80 },
  { min: 11, max: 14, precio: 120 },
  { min: 15, max: 30, precio: 140 },
];

export const PLAZAS_EXCEPCION = ["Juchitán", "Tlapa", "San Andrés", "Cd. Valles", "Putla", "Toluca"];

export const RUTEO_LABEL = {
  GAM: "Sucursal → CEDIS → Sucursal de remate",
  GSA: "Todo a R1",
  SA: "Todo a Tienda 4",
  GAMN: "Remata en la misma plaza",
};

/** Precio por caja aplicable a una línea de remate, según minuta GAM. */
export function precioRemate(cajas, economico) {
  if (economico && cajas >= 30) {
    return { precio: 120, esSupuesto: false, esExcepcion: true, motivo: "Económico con 30+ cajas → remate directo (regla explícita de la minuta)" };
  }
  if (!economico && cajas > 30) {
    return { precio: 140, esSupuesto: true, esExcepcion: true, motivo: "La minuta no define escala > 30 cajas para producto no económico; se extiende el último rango (15-30 → $140). Validar con Sanimex." };
  }
  const escala = ESCALAS_REMATE.find((e) => cajas >= e.min && cajas <= e.max) || ESCALAS_REMATE[0];
  return { precio: escala.precio, esSupuesto: false, esExcepcion: false, motivo: null };
}

function esPlazaExcepcion(nombrePlaza) {
  return PLAZAS_EXCEPCION.some((p) => nombrePlaza?.includes(p));
}

/**
 * Determina si una línea de remate se traslada o se liquida en sitio, y
 * calcula la ruta completa (origen → [CEDIS] → destino de remate).
 * `rutasGAM` es la tabla editable Sucursal/Corredor → {cedis, remate}.
 */
export function computeRuteoRemate({ cajas, economico, organizacion, plant, nombre, corredor }, rutasGAM) {
  const excepcionPlaza = esPlazaExcepcion(nombre);
  const enEscalaAlta = cajas >= 11; // 11-14 y 15-30 (y económico 30+) se trasladan
  const trasladar = !excepcionPlaza && enEscalaAlta && organizacion !== "GAMN";

  if (!trasladar) {
    return {
      ruta: [{ tipo: "origen", nombre, plant }],
      enSitio: true,
      excepcionPlaza,
      motivoEnSitio: excepcionPlaza
        ? `Plaza de excepción: ${nombre} remata siempre en sitio (sin traslado).`
        : organizacion === "GAMN" && enEscalaAlta
        ? "Organización GAMN: remata en la misma plaza."
        : "Escala 1-3 / 4-10 cajas: se liquida en sitio (sin traslado).",
    };
  }

  const ruta = [{ tipo: "origen", nombre, plant }];
  let destinoFinal;
  if (organizacion === "GAM") {
    const r = rutasGAM[corredor] || rutasGAM.default;
    ruta.push({ tipo: "cedis", nombre: r.cedis });
    destinoFinal = r.remate;
  } else if (organizacion === "GSA") {
    destinoFinal = "R1";
  } else if (organizacion === "SA") {
    destinoFinal = "Tienda 4";
  } else {
    destinoFinal = nombre; // fallback defensivo, no debería alcanzarse
  }
  ruta.push({ tipo: "remate", nombre: destinoFinal });
  return { ruta, enSitio: false, excepcionPlaza: false, motivoEnSitio: null };
}

/** Arma la línea completa de remate (precio + ruteo + importe) desde datos crudos. */
export function buildRemateLine(item, rutasGAM) {
  const { precio, esSupuesto, esExcepcion, motivo } = precioRemate(item.cajas, item.economico);
  const ruteo = computeRuteoRemate(item, rutasGAM);
  return {
    ...item,
    precioPorCaja: precio,
    importe: Math.round(precio * item.cajas),
    esSupuestoPrecio: esSupuesto,
    esExcepcionPrecio: esExcepcion,
    motivoPrecio: motivo,
    ...ruteo,
  };
}

/**
 * RN-02: transferencia antes que compra. Dado un déficit y el excedente
 * disponible en el corredor, regresa cuánto transferir y cuánto (si acaso)
 * comprar del remanente. Nunca compra el total si el corredor cubre parte
 * (golden cases G4/G5, waykee 290102 msg 61807).
 */
export function computeTransferenciaCorredor(deficit, excedenteCorredor) {
  const transferir = Math.min(deficit, Math.max(0, excedenteCorredor));
  const comprar = Math.max(0, deficit - transferir);
  return { transferir, comprar, cubreCompleto: comprar === 0 };
}
