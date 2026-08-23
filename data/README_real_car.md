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
