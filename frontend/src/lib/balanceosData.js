/**
 * Fuente de datos para la pantalla Balanceos & Remates.
 *
 * Intenta consumir la API real de T4 (backend/motores_c1.py):
 *   GET /api/balanceos/propuestas
 *   GET /api/remates/detectar
 * Si el endpoint aún no existe (404) o falla la red, cae a un dataset mock
 * construido con el MISMO motor de reglas (remateEngine.js) que usará T4 en
 * Python — así los números que se ven en el demo respetan la minuta GAM
 * exacta y son 1:1 reemplazables por datos reales sin tocar la pantalla.
 */

import { buildRemateLine, computeTransferenciaCorredor } from "./remateEngine";

// Tabla de ruteo GAM: corredor -> {cedis, remate}. En producción vive en BD
// (editable, según T4); aquí es un mock razonable por corredor.
export const RUTAS_GAM = {
  "Corredor Noreste": { cedis: "CEDIS Monterrey Centro", remate: "Sanimex Saltillo Centro" },
  "Corredor Bajío": { cedis: "CEDIS León Centro", remate: "Sanimex Celaya Centro" },
  "Corredor Centro": { cedis: "CEDIS CDMX Iztapalapa", remate: "Sanimex Pachuca Centro" },
  "Corredor Occidente": { cedis: "CEDIS Guadalajara Zapopan", remate: "Sanimex Colima Centro" },
  default: { cedis: "CEDIS Regional", remate: "Sucursal de Remate Regional" },
};

const ORG_LABEL = { GAM: "GAM", GSA: "GSA", SA: "SA", GAMN: "GAMN" };

async function tryFetch(path) {
  try {
    const res = await fetch(path, { headers: { Accept: "application/json" } });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// BALANCEOS — propuestas de transferencia dentro de corredor (RN-02)
// ---------------------------------------------------------------------------
const MOCK_BALANCEOS_RAW = [
  { material_id: "SAN-PIS-0112", descripcion: "Piso Porcelanato 60x60 Beige", abc: "A", corredor: "Corredor Noreste",
    origen: { plant: "P010", nombre: "Sanimex Monterrey Apodaca" }, destino: { plant: "P004", nombre: "Sanimex Monterrey Centro" },
    deficit: 60, excedenteCorredor: 95, precioVenta: 310, costoCajaTraslado: 38 },
  { material_id: "SAN-AZU-0087", descripcion: "Azulejo 30x60 Gris", abc: "B", corredor: "Corredor Bajío",
    origen: { plant: "P021", nombre: "Sanimex León Centro" }, destino: { plant: "P018", nombre: "Sanimex Celaya Centro" },
    deficit: 40, excedenteCorredor: 22, precioVenta: 165, costoCajaTraslado: 30 },
  { material_id: "SAN-SAN-0033", descripcion: "Sanitario Dueto Blanco", abc: "A", corredor: "Corredor Centro",
    origen: { plant: "P002", nombre: "Sanimex CDMX Coyoacán" }, destino: { plant: "P009", nombre: "Sanimex CDMX Naucalpan" },
    deficit: 18, excedenteCorredor: 25, precioVenta: 2450, costoCajaTraslado: 210 },
  { material_id: "SAN-PIS-0056", descripcion: "Piso Cerámico 45x45 Arena", abc: "B", corredor: "Corredor Occidente",
    origen: { plant: "P014", nombre: "Sanimex Guadalajara Centro" }, destino: { plant: "P027", nombre: "Sanimex Colima Centro" },
    deficit: 72, excedenteCorredor: 50, precioVenta: 128, costoCajaTraslado: 22 },
  { material_id: "SAN-FAC-0019", descripcion: "Fachada Piedra Rústica", abc: "C", corredor: "Corredor Noreste",
    origen: { plant: "P006", nombre: "Sanimex Saltillo Centro" }, destino: { plant: "P010", nombre: "Sanimex Monterrey Apodaca" },
    deficit: 30, excedenteCorredor: 30, precioVenta: 245, costoCajaTraslado: 34 },
  { material_id: "SAN-PEG-0004", descripcion: "Pegazulejo Bulto 25kg", abc: "B", corredor: "Corredor Bajío",
    origen: { plant: "P018", nombre: "Sanimex Celaya Centro" }, destino: { plant: "P021", nombre: "Sanimex León Centro" },
    deficit: 26, excedenteCorredor: 34, precioVenta: 210, costoCajaTraslado: 18 },
];

function buildBalanceos() {
  return MOCK_BALANCEOS_RAW.map((b, i) => {
    const { transferir, comprar, cubreCompleto } = computeTransferenciaCorredor(b.deficit, b.excedenteCorredor);
    const ahorroEstimado = Math.round(transferir * b.precioVenta * 0.62 - transferir * b.costoCajaTraslado);
    return {
      id: `BAL-${String(i + 1).padStart(3, "0")}`,
      ...b,
      cajasTransferir: transferir,
      cajasComprar: comprar,
      cubreCompleto,
      costoTraslado: Math.round(transferir * b.costoCajaTraslado),
      ahorroEstimado: Math.max(0, ahorroEstimado),
      estado: "pendiente",
      layer: "C3",
    };
  });
}

export async function fetchBalanceos() {
  const real = await tryFetch("/api/balanceos/propuestas");
  if (real && Array.isArray(real.items ?? real)) {
    return { items: real.items ?? real, source: "api" };
  }
  return { items: buildBalanceos(), source: "mock" };
}

// ---------------------------------------------------------------------------
// REMATES — detección de remanentes (minuta GAM) + ruteo por organización
// ---------------------------------------------------------------------------
const MOCK_REMATES_RAW = [
  { material_id: "SAN-BOQ-0021", descripcion: "Boquilla Bolsa 5kg", abc: "C", economico: true,
    organizacion: "GAM", plant: "P010", nombre: "Sanimex Monterrey Apodaca", corredor: "Corredor Noreste",
    diasSinVenta: 118, cajas: 2, precioVenta: 95 },
  { material_id: "SAN-ACC-0045", descripcion: "Crucetas 2mm (caja)", abc: "C", economico: true,
    organizacion: "GSA", plant: "P031", nombre: "Sanimex Culiacán Centro", corredor: "Corredor Pacífico",
    diasSinVenta: 96, cajas: 7, precioVenta: 78 },
  { material_id: "SAN-PIS-0078", descripcion: "Piso Cerámico 33x33 Blanco", abc: "C", economico: false,
    organizacion: "SA", plant: "P033", nombre: "Sanimex Villahermosa Centro", corredor: "Corredor Sureste",
    diasSinVenta: 140, cajas: 12, precioVenta: 105 },
  { material_id: "SAN-AZU-0102", descripcion: "Azulejo 20x30 Hueso", abc: "B", economico: false,
    organizacion: "GAMN", plant: "P022", nombre: "Sanimex Querétaro Centro", corredor: "Corredor Bajío",
    diasSinVenta: 85, cajas: 18, precioVenta: 118 },
  { material_id: "SAN-PIS-0091", descripcion: "Piso Porcelanato 80x80 Gris Humo", abc: "A", economico: false,
    organizacion: "GAM", plant: "P021", nombre: "Sanimex León Centro", corredor: "Corredor Bajío",
    diasSinVenta: 102, cajas: 25, precioVenta: 420 },
  { material_id: "SAN-SAN-0061", descripcion: "WC Unitario Color", abc: "C", economico: false,
    organizacion: "GAM", plant: "P016", nombre: "Sanimex Toluca Centro", corredor: "Corredor Centro",
    diasSinVenta: 165, cajas: 20, precioVenta: 1850 },
  { material_id: "SAN-PEG-0011", descripcion: "Pegazulejo Bulto 20kg (descontinuado)", abc: "C", economico: true,
    organizacion: "GAM", plant: "P014", nombre: "Sanimex Guadalajara Centro", corredor: "Corredor Occidente",
    diasSinVenta: 210, cajas: 34, precioVenta: 190 },
  { material_id: "SAN-FAC-0028", descripcion: "Fachada Cantera (fin de línea)", abc: "B", economico: false,
    organizacion: "SA", plant: "P009", nombre: "Sanimex CDMX Naucalpan", corredor: "Corredor Centro",
    diasSinVenta: 130, cajas: 33, precioVenta: 260 },
  { material_id: "SAN-BOQ-0009", descripcion: "Boquilla Bolsa 1kg", abc: "C", economico: true,
    organizacion: "GAMN", plant: "P025", nombre: "Sanimex Morelia Centro", corredor: "Corredor Bajío",
    diasSinVenta: 75, cajas: 5, precioVenta: 62 },
  { material_id: "SAN-PIS-0044", descripcion: "Piso Cerámico 40x40 Terracota", abc: "B", economico: false,
    organizacion: "GAM", plant: "P006", nombre: "Sanimex Saltillo Centro", corredor: "Corredor Noreste",
    diasSinVenta: 91, cajas: 13, precioVenta: 132 },
];

function buildRemates() {
  return MOCK_REMATES_RAW.map((r, i) => {
    const line = buildRemateLine(r, RUTAS_GAM);
    return {
      id: `REM-${String(i + 1).padStart(3, "0")}`,
      ...line,
      valorEnRiesgo: Math.round(r.cajas * r.precioVenta),
      estado: "pendiente",
    };
  });
}

export async function fetchRemates() {
  const real = await tryFetch("/api/remates/detectar");
  if (real && Array.isArray(real.items ?? real)) {
    return { items: real.items ?? real, source: "api" };
  }
  return { items: buildRemates(), source: "mock" };
}

export const ORGANIZACIONES = ["GAM", "GSA", "SA", "GAMN"];
export { ORG_LABEL };
