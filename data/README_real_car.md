# Dataset real CAR PRD (branch `data/real-car`)

`comprasai.db` generado por `extract_real_car.py` **no se sube a git**: pesa
198 MB y excede el límite de 100 MB por blob de GitHub (ventas_mensuales +
sus 4 índices concentran ~182 MB de esos 198 MB). Se descartó instalar
git-lfs de forma unilateral (rompería clones de bots/CI que no lo tengan
configurado) y se descartó recortar el alcance (24 meses / sucursales
completas) porque contradice el mandato explícito del PM.

Entrega real:
- `extract_real_car.py` — script de extracción, en este branch.
- `comprasai.db` — adjunto directamente en el waykee ticket 288699 (canal
  también autorizado explícitamente por el PM para este entregable).

Para regenerar el .db localmente: correr `extract_real_car.py` con VPN
activa contra CAR PRD (credenciales vía variables de entorno, ver header
del script). Ver el reporte a 290066 (bridge, 2026-08-23) para el
detalle de qué campos/tablas son reales vs. sintéticos, hallazgos de
calidad de datos y validación de interop con el motor de sugeridos.

## Credenciales HANA — Waykee Secrets (v3)

Los scripts **ya NO** llevan credenciales hardcodeadas: se leen de variables
de entorno resueltas por los markers de Waykee Secrets en bash:

```bash
H={SanimexHanaHost} P={SanimexCARHanaPuerto} U={SanimexCARUser} PW={SanimexCARPassword} \
  python3 extract_real_car.py
```

## data-real-car-v3 — tabla kardex_diario (T23 / waykee 290120)

`build_kardex_v3.py` parte del `.db` de la release v2 (todas las tablas
intactas) y agrega **una tabla nueva** `kardex_diario` con el kardex diario
por material-centro (solo días con movimiento), reconstruido desde
`SAPS4H.MATDOC` y anclado al stock actual real de T17
(`InventoryVisibilityCurrentStock.UnresUseStockQuantity`).

```
kardex_diario(material_id, plant, fecha, entradas, salidas, saldo_fin_dia)
```

- Universo: HAWA (7,421) × centros (233), BUDAT ≥ 2024-08 (24 meses).
- 4,535,059 filas · rango 2024-08-01 → 2026-08-23.
- Saldo EXACTO: `saldo_fin_dia(d) = S_now − Σ(neto de días posteriores)`.
  Anclaje verificado: 99.91% de los combos (140,057/140,189) tienen el
  último saldo == `inventarios.disponible` real.
- Residuo (por movimientos de tránsito 641 / stock especial que el stock
  libre no refleja): 10,634 filas con saldo<0 (0.234%), en 969 combos
  (0.46%). Neutro al umbral de desabasto (la X piezas / N días la aplica
  el backend cuando compras responda el cuestionario T21).

### Parte B — MOQ/empaque y política de inventario (reporte de cobertura)

Medido en vivo contra CAR PRD (2026-08-23). Todo por debajo del umbral
>50% → se conserva el sintético de v2 y la habilitación se escala vía
cuestionario T21 §7 (NO se agregaron columnas reales):

- `moq_cajas` (EINE MINBM/NORBM/BSTRF): **0%** — la tabla EINE (condiciones
  de compra) NO existe en la instancia HANA del réplica.
- `cajas_por_pallet` (derivable de MARM PAL/CS): **35.9%** (2,665/7,421).
- `punto_reorden` (MARC.MINBE): **2.9%** (213/7,421).
- `stock_seguridad` (MARC.EISBE): **0%**; MABST 0.7%, BSTMI/BSTMA 0%.

Regenerar v3: `H=.. P=.. U=.. PW=.. python3 build_kardex_v3.py <v2.db> <v3.db>`
