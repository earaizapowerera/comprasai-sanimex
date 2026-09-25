#!/usr/bin/env bash
# Tunel inverso HANA CAR -> VM de prod ComprasAI (waykee 292300).
#
# El VM (waykee2-api-vm, Azure) no tiene ruta a HANA CAR de Sanimex; la Mac si
# (VPN). Este proceso publica HANA en el VM en 172.17.0.1:${TUNNEL_PORT} (IP
# del bridge docker: la alcanzan el host y sus contenedores, no internet).
# El backend lo usa via SANIMEX_CAR_HOST=host-gateway en secrets/hana.env.
#
# Solo mueve bytes: las credenciales de HANA nunca pasan por aqui. Host/puerto
# de HANA se leen de ~/.config/comprasai/hana.env (modo 600, mismo archivo del
# pipeline diario). Lo corre launchd con KeepAlive (com.powerera.comprasai.hana-tunnel).
# Si la Mac se duerme o cae la VPN, el backend responde con el snapshot y
# live=false; al volver, launchd relanza el tunel.
set -euo pipefail

ENV_FILE="${COMPRASAI_HANA_ENV:-$HOME/.config/comprasai/hana.env}"
VM="${COMPRASAI_VM:-earaiza@comprassanimexai.powerera.com}"
KEY="${COMPRASAI_VM_KEY:-$HOME/.ssh/id_claude_automation}"
TUNNEL_BIND="${COMPRASAI_TUNNEL_BIND:-172.17.0.1}"
TUNNEL_PORT="${COMPRASAI_TUNNEL_PORT:-30015}"

HANA_HOST=$(grep -E '^SANIMEX_CAR_HOST=' "$ENV_FILE" | cut -d= -f2-)
HANA_PORT=$(grep -E '^SANIMEX_CAR_PORT=' "$ENV_FILE" | cut -d= -f2-)
[ -n "$HANA_HOST" ] && [ -n "$HANA_PORT" ] || { echo "hana.env sin SANIMEX_CAR_HOST/PORT" >&2; exit 1; }

exec /usr/bin/ssh -N -T \
  -i "$KEY" \
  -o BatchMode=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=20 \
  -o ServerAliveCountMax=3 \
  -o ConnectTimeout=15 \
  -R "${TUNNEL_BIND}:${TUNNEL_PORT}:${HANA_HOST}:${HANA_PORT}" \
  "$VM"
