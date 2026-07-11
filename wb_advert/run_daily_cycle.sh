#!/usr/bin/env bash
# Linux-аналог run_daily_cycle.ps1: дневной цикл пилота.
# sync rotate -> optimizer -> parse positions -> stocks -> snapshots.
# Предназначен для запуска по cron / systemd timer на сервере.
#
# Параметры через env:
#   SYNC_PAUSE   (по умолчанию 8)   — пауза синка
#   PARSE_LIMIT  (по умолчанию 0)   — лимит SKU для парсинга (0 = все primary x регионы)
#   SKIP_SYNC / SKIP_PARSE / SKIP_STOCKS = 1 — пропустить шаг
#   FORCE_PARSE  = 1                — форсировать парсинг
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

SYNC_PAUSE="${SYNC_PAUSE:-8}"
PARSE_LIMIT="${PARSE_LIMIT:-0}"

echo "=== WB Advert daily cycle ==="

if [ "${SKIP_SYNC:-0}" != "1" ]; then
    echo; echo "[1/5] Sync rotate (1 campaign + fullstats if due)..."
    python -m scripts.sync_pilot --rotate --pause "$SYNC_PAUSE" --limit 1
fi

echo; echo "[2/5] Optimizer (suggest-only)..."
python -m scripts.run_optimizer

if [ "${SKIP_PARSE:-0}" != "1" ]; then
    echo; echo "[3/5] Parse positions..."
    PARSE_ARGS=(--all-regions --skip-fresh)
    [ "$PARSE_LIMIT" -gt 0 ] && PARSE_ARGS+=(--limit "$PARSE_LIMIT")
    [ "${FORCE_PARSE:-0}" = "1" ] && PARSE_ARGS+=(--force)
    python -m scripts.parse_positions "${PARSE_ARGS[@]}" || {
        echo "[3/5] Parse positions failed (best-effort), continuing..."
    }
fi

if [ "${SKIP_STOCKS:-0}" != "1" ]; then
    echo; echo "[4/5] Stocks report (skip if synced <24h)..."
    python -m scripts.sync_stocks
fi

echo; echo "[5/5] Capture snapshots (memory)..."
python -m scripts.capture_snapshots

echo; echo "Done."
