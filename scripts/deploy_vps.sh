#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/deploy_vps.sh <VPS_HOST> <SSH_USER> <BOT_TOKEN> <ADMIN_CHAT_IDS>
# Example:
#   ./scripts/deploy_vps.sh 1.2.3.4 root 123:ABC 111111,222222

VPS_HOST=${1:-}
SSH_USER=${2:-root}
TELEGRAM_BOT_TOKEN=${3:-}
ADMIN_CHAT_IDS=${4:-}

if [[ -z "$VPS_HOST" || -z "$TELEGRAM_BOT_TOKEN" ]]; then
  echo "Usage: $0 <VPS_HOST> <SSH_USER> <BOT_TOKEN> <ADMIN_CHAT_IDS>"
  exit 1
fi

PROJECT=orders-bot

ssh -o StrictHostKeyChecking=no ${SSH_USER}@${VPS_HOST} "mkdir -p ~/${PROJECT}"

rsync -az --delete \
  --exclude '.git' \
  --exclude 'data/*' \
  ./ ${SSH_USER}@${VPS_HOST}:~/${PROJECT}/

ssh -o StrictHostKeyChecking=no ${SSH_USER}@${VPS_HOST} bash -lc "\
  cd ~/${PROJECT} && \
  docker compose build && \
  TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN} ADMIN_CHAT_IDS=${ADMIN_CHAT_IDS} docker compose up -d --remove-orphans \
"

echo "Deployed to ${VPS_HOST}. Use: docker logs -f orders-bot"


