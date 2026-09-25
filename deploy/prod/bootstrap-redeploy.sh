#!/usr/bin/env bash
# Se instala como ~/comprasai-deploy/redeploy.sh (fuera de git). Solo trae
# origin/main y delega al redeploy versionado, para que el script que corre
# sea siempre el de main (bash no debe ejecutar un archivo que git reescribe).
set -euo pipefail
cd ~/comprasai-deploy
git fetch origin && git reset --hard origin/main
git log --oneline -1
exec bash deploy/prod/redeploy.sh
