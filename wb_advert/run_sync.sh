#!/usr/bin/env bash
# Linux-аналог run_sync.ps1: разовая синхронизация одной кампании.
# Использование: ./run_sync.sh <ADVERT_ID>
set -euo pipefail

if [ "${1:-}" = "" ]; then
    echo "Использование: $0 <ADVERT_ID>" >&2
    exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [ ! -f "$ROOT/.env" ] && [ -f "$ROOT/../wb_advert_probe/.env" ]; then
    echo "Token: wb_advert_probe/.env (auto-loaded)"
fi

exec python -m scripts.sync_once --advert-id "$1"
