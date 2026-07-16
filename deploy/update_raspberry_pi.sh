#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/bot/apps/binance_bot}"
WEB_ROOT="${WEB_ROOT:-/var/www/bot}"
DASHBOARD_ENV="${PROJECT_DIR}/.env.dashboard"
ACTION="${1:-apply}"

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

check_link() {
  systemctl is-active --quiet mybot || fail "mybot is not active"
  systemctl is-active --quiet pi-healthd || fail "pi-healthd is not active"
  runuser -u bot -- test -r /run/mybot/ai_status.json \
    || fail "bot user cannot read /run/mybot/ai_status.json"
  runuser -u bot -- test -r "${DASHBOARD_ENV}" \
    || fail "bot user cannot read ${DASHBOARD_ENV}"
  grep -q '^DASHBOARD_FOLLOW_BOT_PATHS=1$' "${DASHBOARD_ENV}" \
    || fail "DASHBOARD_FOLLOW_BOT_PATHS=1 is missing"
  python3 -m json.tool /run/mybot/ai_status.json >/dev/null \
    || fail "AI runtime heartbeat is invalid"
  local anonymous_status
  anonymous_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    http://127.0.0.1:8081/api/health)"
  [[ "${anonymous_status}" == "401" ]] \
    || fail "expected protected API HTTP 401, got ${anonymous_status}"
  echo "[OK] bot/dashboard heartbeat, permissions and protected API are ready"
  python3 -m json.tool /run/mybot/ai_status.json
}

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo --preserve-env=PROJECT_DIR,WEB_ROOT "$0" "$@"
fi

[[ -d "${PROJECT_DIR}" ]] || fail "project directory not found: ${PROJECT_DIR}"
cd "${PROJECT_DIR}"

if [[ "${ACTION}" == "check" ]]; then
  check_link
  exit 0
fi
[[ "${ACTION}" == "apply" ]] || fail "usage: $0 [apply|check]"

[[ -f .env ]] || fail "configure ${PROJECT_DIR}/.env before deployment"
if [[ ! -f "${DASHBOARD_ENV}" ]]; then
  install -m 0600 .env.dashboard.example "${DASHBOARD_ENV}"
  fail "created ${DASHBOARD_ENV}; replace placeholder dashboard tokens/keys, then run again"
fi

if grep -q '^BOT_TESTNET_RUN_DIR=' .env; then
  sed -i 's|^BOT_TESTNET_RUN_DIR=.*|BOT_TESTNET_RUN_DIR=/run/mybot/testnet|' .env
else
  printf '\nBOT_TESTNET_RUN_DIR=/run/mybot/testnet\n' >>.env
fi
if grep -q '^AI_RUNTIME_STATUS_FILE=' .env; then
  sed -i 's|^AI_RUNTIME_STATUS_FILE=.*|AI_RUNTIME_STATUS_FILE=/run/mybot/ai_status.json|' .env
else
  printf 'AI_RUNTIME_STATUS_FILE=/run/mybot/ai_status.json\n' >>.env
fi
chmod 0600 .env

if grep -q '^AI_RUNTIME_STATUS_FILE=' "${DASHBOARD_ENV}"; then
  sed -i 's|^AI_RUNTIME_STATUS_FILE=.*|AI_RUNTIME_STATUS_FILE=/run/mybot/ai_status.json|' "${DASHBOARD_ENV}"
else
  printf '\nAI_RUNTIME_STATUS_FILE=/run/mybot/ai_status.json\n' >>"${DASHBOARD_ENV}"
fi
if grep -q '^DASHBOARD_FOLLOW_BOT_PATHS=' "${DASHBOARD_ENV}"; then
  sed -i 's/^DASHBOARD_FOLLOW_BOT_PATHS=.*/DASHBOARD_FOLLOW_BOT_PATHS=1/' "${DASHBOARD_ENV}"
else
  printf 'DASHBOARD_FOLLOW_BOT_PATHS=1\n' >>"${DASHBOARD_ENV}"
fi
chmod 0600 "${DASHBOARD_ENV}"

install -d -o bot -g bot -m 0700 db logs FastAPI/pi-dashboard/data
install -d -o root -g root -m 0755 "${WEB_ROOT}"
install -d -o root -g root -m 0755 /etc/systemd/system/mybot.service.d
install -m 0644 FRONT/index.html FRONT/help.html FRONT/readme.html "${WEB_ROOT}/"
install -m 0644 deploy/mybot-dashboard-link.conf \
  /etc/systemd/system/mybot.service.d/dashboard-link.conf
install -m 0644 deploy/pi-dashboard.service /etc/systemd/system/pi-healthd.service

systemctl daemon-reload
systemctl restart mybot
systemctl restart pi-healthd
systemctl reload nginx

check_link
