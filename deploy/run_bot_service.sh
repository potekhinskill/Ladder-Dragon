#!/usr/bin/env bash
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/bot/apps/binance_bot}"
PYTHON="${PROJECT_DIR}/.venv/bin/python"
VENUE="${BOT_SERVICE_VENUE:-testnet}"
EXECUTION="${BOT_SERVICE_EXECUTION:-dry}"
SYMBOLS="${BOT_SERVICE_SYMBOLS:-SOLUSDT,ETHUSDT,TONUSDT}"

[[ "${VENUE}" == "testnet" || "${VENUE}" == "mainnet" ]] || {
  echo "BOT_SERVICE_VENUE must be testnet or mainnet" >&2
  exit 2
}
[[ "${EXECUTION}" == "dry" || "${EXECUTION}" == "live" ]] || {
  echo "BOT_SERVICE_EXECUTION must be dry or live" >&2
  exit 2
}
[[ -x "${PYTHON}" ]] || {
  echo "Python virtual environment is missing: ${PYTHON}" >&2
  exit 2
}

if [[ "${VENUE}" == "testnet" ]]; then
  export BOT_STATS_DB="${BOT_TESTNET_STATS_DB:-${PROJECT_DIR}/db/testnet_bot_stats.db}"
  export BOT_ORDER_JOURNAL="${BOT_TESTNET_ORDER_JOURNAL:-${PROJECT_DIR}/db/testnet_order_intents.sqlite3}"
  export BOT_RUN_DIR="${BOT_TESTNET_RUN_DIR:-/run/mybot/testnet}"
fi

"${PYTHON}" "${PROJECT_DIR}/db_migrate.py"

args=(
  "${PROJECT_DIR}/ai_supervisor.py"
  --singleton
  "--${VENUE}"
  --symbols "${SYMBOLS}"
  --base-script "${PROJECT_DIR}/autosize_universal.py"
  --grid-density 24
  --smart-rolling
  --auto-cap
  --attach-oco-on-fill
  --auto-oco-holdings
  --enforce-target-buys
  --enforce-sell-limit
)

if [[ "${EXECUTION}" == "live" ]]; then
  [[ "${BOT_LIVE_CONFIRMED:-NO}" == "YES" ]] || {
    echo "LIVE blocked: BOT_LIVE_CONFIRMED=YES is required" >&2
    exit 2
  }
  args+=(--live)
fi

# Дополнительные аргументы допустимы только из root-owned service env.
# shellcheck disable=SC2206
extra_args=(${BOT_SERVICE_EXTRA_ARGS:-})
args+=("${extra_args[@]}")

exec "${PYTHON}" -u "${args[@]}"
