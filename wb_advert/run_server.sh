#!/usr/bin/env bash
# Linux-аналог run_server.ps1: запуск дашборда wb_advert.
# Порт: env WB_ADVERT_PORT (по умолчанию 8765). Хост: WB_ADVERT_HOST (127.0.0.1).
# Reload: WB_ADVERT_RELOAD=1 (по умолчанию выкл — для прода).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # .../wb_advert
PARENT="$(dirname "$ROOT")"                            # корень репо
cd "$PARENT"

python -m pip install -q -r "$ROOT/requirements.txt"

HOST="${WB_ADVERT_HOST:-127.0.0.1}"
PORT="${WB_ADVERT_PORT:-8765}"
RELOAD_FLAG=""
[ "${WB_ADVERT_RELOAD:-0}" = "1" ] && RELOAD_FLAG="--reload"

echo "Advert dashboard: http://${HOST}:${PORT}"
echo "  /  или  /advert  — главная"
echo "  /advert/decisions — audit log"
exec python -m uvicorn wb_advert.app:app --host "$HOST" --port "$PORT" $RELOAD_FLAG
