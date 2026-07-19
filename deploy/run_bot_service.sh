#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: start the managed bot supervisor.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/bot/apps/binance_bot}"
PYTHON="${PROJECT_DIR}/.venv/bin/python"
VENUE="${BOT_SERVICE_VENUE:-testnet}"
EXECUTION="${BOT_SERVICE_EXECUTION:-dry}"
SYMBOLS="${BOT_SERVICE_SYMBOLS:-SOLUSDT,ETHUSDT,TONUSDT}"
AUTO_OCO_HOLDINGS="${BOT_SERVICE_AUTO_OCO_HOLDINGS:-0}"

[[ "${VENUE}" == "testnet" || "${VENUE}" == "mainnet" ]] || {
  echo "BOT_SERVICE_VENUE must be testnet or mainnet" >&2
  exit 2
}
[[ "${EXECUTION}" == "dry" || "${EXECUTION}" == "live" ]] || {
  echo "BOT_SERVICE_EXECUTION must be dry or live" >&2
  exit 2
}
[[ "${AUTO_OCO_HOLDINGS}" == "0" || "${AUTO_OCO_HOLDINGS}" == "1" ]] || {
  echo "BOT_SERVICE_AUTO_OCO_HOLDINGS must be 0 or 1" >&2
  exit 2
}
export PYTHONPATH="${PROJECT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

[[ -x "${PYTHON}" ]] || {
  echo "Python virtual environment is missing: ${PYTHON}" >&2
  exit 2
}

if [[ "${VENUE}" == "testnet" ]]; then
  export BOT_STATS_DB="${BOT_TESTNET_STATS_DB:-${PROJECT_DIR}/db/testnet_bot_stats.db}"
  export BOT_ORDER_JOURNAL="${BOT_TESTNET_ORDER_JOURNAL:-${PROJECT_DIR}/db/testnet_order_intents.sqlite3}"
  export BOT_RUN_DIR="${BOT_TESTNET_RUN_DIR:-/run/mybot/testnet}"
fi

"${PYTHON}" -m bin.db_migrate

args=(
  "${PROJECT_DIR}/bin/ai_supervisor.py"
  --singleton
  "--${VENUE}"
  --symbols "${SYMBOLS}"
  --base-script "${PROJECT_DIR}/bin/autosize_universal.py"
  --grid-density 24
  --smart-rolling
  --auto-cap
  --attach-oco-on-fill
  --enforce-target-buys
  --enforce-sell-limit
)

# Existing holdings may have been acquired outside Ladder Dragon or may carry
# an unreconciled cost basis. Never manage them unless the operator explicitly
# opts in after reviewing the account ledger.
if [[ "${AUTO_OCO_HOLDINGS}" == "1" ]]; then
  args+=(--auto-oco-holdings)
fi

if [[ "${EXECUTION}" == "live" ]]; then
  [[ "${BOT_LIVE_CONFIRMED:-NO}" == "YES" ]] || {
    echo "LIVE blocked: BOT_LIVE_CONFIRMED=YES is required" >&2
    exit 2
  }
  args+=(--live)
fi

# Parse only explicitly allowlisted tuning arguments. Critical venue, execution,
# script, AI, path, and credential options can never be overridden here.
"${PYTHON}" "${PROJECT_DIR}/deploy/parse_service_args.py" \
  "${BOT_SERVICE_EXTRA_ARGS:-}" >/dev/null
mapfile -d '' -t extra_args < <(
  "${PYTHON}" "${PROJECT_DIR}/deploy/parse_service_args.py" \
    "${BOT_SERVICE_EXTRA_ARGS:-}"
)
args+=("${extra_args[@]}")

exec "${PYTHON}" -u "${args[@]}"
