#!/usr/bin/env bash
# Linux-аналог run_import.ps1: установка зависимостей + импорт пилота.
# Все доп. аргументы прокидываются в scripts.import_pilot.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

LOCAL_ENV="$ROOT/.env"
PROBE_ENV="$ROOT/../wb_advert_probe/.env"

if [ -f "$LOCAL_ENV" ]; then
    echo "Token: wb_advert/.env"
elif [ -f "$PROBE_ENV" ]; then
    echo "Token: wb_advert_probe/.env (auto-loaded)"
else
    cp -n "$ROOT/.env.example" "$LOCAL_ENV" 2>/dev/null || true
    echo "ВНИМАНИЕ: добавьте WB_API_TOKEN в wb_advert/.env" >&2
fi

python -m pip install -q -r requirements.txt
exec python -m scripts.import_pilot "$@"
