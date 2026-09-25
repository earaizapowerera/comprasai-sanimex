#!/usr/bin/env bash
# Redeploy de ComprasAI en comprassanimexai.powerera.com (waykee 292300).
# Idempotente. Corre DESPUÉS de que el bootstrap (~/comprasai-deploy/redeploy.sh)
# dejó el checkout en origin/main.
#   - Backend sobre SQL Server (snapshot diario), sin dataset congelado.
#   - HANA en vivo al abrir artículos (túnel desde la Mac; si no está, cada
#     respuesta cae al snapshot marcada live=false).
set -euo pipefail
cd "$(dirname "$0")/../.."
B=https://comprassanimexai.powerera.com/comprasAI
COMPOSE=(docker-compose -f docker-compose.yml -f deploy/prod/docker-compose.prod.yml)

for f in secrets/sqlserver.env secrets/hana.env; do
  [ -s "$f" ] || { echo "FALTA $f (credenciales fuera de git)"; exit 2; }
  [ "$(stat -c %a "$f")" = 600 ] || { echo "$f debe ser modo 600"; exit 2; }
done

echo "== build frontend (Vite base=/comprasAI/) =="
(cd frontend && npm ci --no-audit --no-fund >/dev/null 2>&1 && npm run build 2>&1 | tail -3)

echo "== levantar backend (:8010) sobre SQL Server =="
"${COMPOSE[@]}" up -d --build --force-recreate --remove-orphans 2>&1 | tail -3
for _ in $(seq 1 30); do
  curl -fs -o /dev/null "$B/api/kpis" && break
  sleep 2
done

echo "== health =="
curl -fsS -o /dev/null -w "  /comprasAI/          -> HTTP %{http_code}\n" "$B/"
curl -fsS -o /dev/null -w "  /comprasAI/api/kpis  -> HTTP %{http_code}  (%{time_total}s)\n" "$B/api/kpis"
docker exec comprasai-backend python -c "from app.core import sqlserver; assert sqlserver.enabled(), 'backend NO esta en SQL Server'; print('  backend: SQL Server')"
if docker logs --since 2m comprasai-backend 2>&1 | grep -E "Traceback|Error" | grep -v "INFO"; then
  echo "REVISAR ERRORES EN EL LOG"; exit 1
fi

echo "== prewarm =="
for ep in api/kpis api/tendencias/ganadores api/engines/forecast/precision api/semaforo/resumen api/inventarios/cobertura/resumen; do
  curl -s -o /dev/null "$B/$ep"
done
echo "== done =="
