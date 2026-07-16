#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/bot/apps/binance_bot}"
WEB_ROOT="${WEB_ROOT:-/var/www/bot}"
DASHBOARD_ENV="${PROJECT_DIR}/.env.dashboard"
BOT_HOSTNAME="${BOT_HOSTNAME:-$(hostname -s).local}"
BOT_USER="${BOT_USER:-$(stat -c '%U' "${PROJECT_DIR}" 2>/dev/null || echo bot)}"
ACTION="${1:-update}"
MYBOT_WAS_ACTIVE=0
DASHBOARD_WAS_ACTIVE=0
MYBOT_WAS_ENABLED=0
DASHBOARD_WAS_ENABLED=0
SERVICES_STOPPED=0

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

service_flag() {
  local operation="$1"
  local unit="$2"
  if systemctl "${operation}" --quiet "${unit}"; then
    echo 1
  else
    echo 0
  fi
}

remember_service_state() {
  MYBOT_WAS_ACTIVE="$(service_flag is-active mybot)"
  DASHBOARD_WAS_ACTIVE="$(service_flag is-active pi-healthd)"
  MYBOT_WAS_ENABLED="$(service_flag is-enabled mybot)"
  DASHBOARD_WAS_ENABLED="$(service_flag is-enabled pi-healthd)"
}

restore_autostart() {
  # Оба компонента составляют один контур и должны переживать reboot.
  systemctl enable mybot pi-healthd >/dev/null
}

start_previous_services() {
  restore_autostart
  if [[ "${MYBOT_WAS_ACTIVE}" == "1" ]]; then
    systemctl start mybot
  fi
  if [[ "${DASHBOARD_WAS_ACTIVE}" == "1" ]]; then
    systemctl start pi-healthd
  fi
  SERVICES_STOPPED=0
}

recover_after_failure() {
  local status=$?
  trap - ERR INT TERM
  if [[ "${SERVICES_STOPPED}" == "1" ]]; then
    echo "[RECOVERY] update failed; starting services that were active before update" >&2
    start_previous_services || true
  fi
  exit "${status}"
}

wait_for_service() {
  local unit="$1"
  local timeout_sec="${2:-90}"
  local deadline=$((SECONDS + timeout_sec))
  until systemctl is-active --quiet "${unit}"; do
    (( SECONDS >= deadline )) && fail "${unit} did not become active in ${timeout_sec}s"
    sleep 2
  done
}

wait_for_heartbeat() {
  local timeout_sec="${1:-120}"
  local deadline=$((SECONDS + timeout_sec))
  until runuser -u "${BOT_USER}" -- python3 - /run/mybot/ai_status.json <<'PY'
import json
import sys
from datetime import datetime, timezone

try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        status = json.load(stream)
    updated = datetime.fromisoformat(status["updated_at"])
    age = (datetime.now(timezone.utc) - updated).total_seconds()
    raise SystemExit(0 if status.get("state") == "RUNNING" and 0 <= age <= 90 else 1)
except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
PY
  do
    (( SECONDS >= deadline )) && fail "fresh RUNNING heartbeat was not received in ${timeout_sec}s"
    sleep 2
  done
}

check_link() {
  systemctl is-active --quiet mybot || fail "mybot is not active"
  systemctl is-active --quiet pi-healthd || fail "pi-healthd is not active"
  systemctl is-enabled --quiet mybot || fail "mybot autostart is not enabled"
  systemctl is-enabled --quiet pi-healthd || fail "pi-healthd autostart is not enabled"
  runuser -u "${BOT_USER}" -- test -r /run/mybot/ai_status.json \
    || fail "bot user cannot read /run/mybot/ai_status.json"
  runuser -u "${BOT_USER}" -- test -r "${DASHBOARD_ENV}" \
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
  exec sudo --preserve-env=PROJECT_DIR,WEB_ROOT,BOT_HOSTNAME,BOT_USER "$0" "$@"
fi

[[ -d "${PROJECT_DIR}" ]] || fail "project directory not found: ${PROJECT_DIR}"
cd "${PROJECT_DIR}"

# `git pull` может обновить сам скрипт. Продолжаем из неизменяемой копии в /tmp,
# чтобы bash не дочитал вторую половину уже из новой версии файла.
if [[ "${ACTION}" == "update" && "${BOT_UPDATE_RUNNER:-0}" != "1" ]]; then
  runner="$(mktemp /tmp/ladder-dragon-update.XXXXXX)"
  install -m 0700 "$0" "${runner}"
  exec env BOT_UPDATE_RUNNER=1 PROJECT_DIR="${PROJECT_DIR}" WEB_ROOT="${WEB_ROOT}" \
    BOT_HOSTNAME="${BOT_HOSTNAME}" BOT_USER="${BOT_USER}" \
    bash "${runner}" update
fi

if [[ "${ACTION}" == "check" ]]; then
  check_link
  exit 0
fi
[[ "${ACTION}" == "update" || "${ACTION}" == "apply" ]] \
  || fail "usage: $0 [update|apply|check]"

[[ -f .env ]] || fail "configure ${PROJECT_DIR}/.env before deployment"
[[ -f .env.service ]] \
  || fail ".env.service is missing; run install_raspberry_pi.sh migrate first"
systemctl cat mybot 2>/dev/null | grep -q 'deploy/run_bot_service.sh' \
  || fail "legacy mybot.service detected; run install_raspberry_pi.sh migrate first"
if [[ ! -f "${DASHBOARD_ENV}" ]]; then
  install -m 0600 .env.dashboard.example "${DASHBOARD_ENV}"
  fail "created ${DASHBOARD_ENV}; replace placeholder dashboard tokens/keys, then run again"
fi

PROJECT_DIR="${PROJECT_DIR}" deploy/backup_raspberry_pi.sh

# Сначала фиксируем состояние systemd. `systemctl stop` не отменяет enabled:
# автозапуск сохранится, но на время обновления Restart=always не смешает версии.
remember_service_state
[[ "${MYBOT_WAS_ENABLED}" == "1" ]] || fail "mybot autostart must be enabled before update"
trap recover_after_failure ERR INT TERM
SERVICES_STOPPED=1
systemctl stop mybot
systemctl stop pi-healthd

if [[ "${ACTION}" == "update" ]]; then
  [[ -z "$(runuser -u "${BOT_USER}" -- git status --porcelain --untracked-files=no)" ]] \
    || fail "tracked project files have local changes; commit or stash them first"
  runuser -u "${BOT_USER}" -- git pull --ff-only
  runuser -u "${BOT_USER}" -- .venv/bin/python -m pip install -e '.[dashboard]'
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
if grep -q '^DASHBOARD_TRUST_PROXY_AUTH=' "${DASHBOARD_ENV}"; then
  sed -i 's/^DASHBOARD_TRUST_PROXY_AUTH=.*/DASHBOARD_TRUST_PROXY_AUTH=1/' "${DASHBOARD_ENV}"
else
  printf 'DASHBOARD_TRUST_PROXY_AUTH=1\n' >>"${DASHBOARD_ENV}"
fi
if grep -q '^DASHBOARD_ENABLE_LOGS=' "${DASHBOARD_ENV}"; then
  sed -i 's/^DASHBOARD_ENABLE_LOGS=.*/DASHBOARD_ENABLE_LOGS=0/' "${DASHBOARD_ENV}"
else
  printf 'DASHBOARD_ENABLE_LOGS=0\n' >>"${DASHBOARD_ENV}"
fi
chmod 0600 "${DASHBOARD_ENV}"

install -d -o "${BOT_USER}" -g "${BOT_USER}" -m 0700 db logs FastAPI/pi-dashboard/data
install -d -o root -g root -m 0755 "${WEB_ROOT}"
install -m 0644 FRONT/index.html FRONT/help.html "${WEB_ROOT}/"
rm -f "${WEB_ROOT}/readme.html"
[[ -f /etc/nginx/.htpasswd-ladder-dragon ]] \
  || fail "nginx dashboard auth is missing; run installer migrate"
[[ -s "/etc/nginx/certs/${BOT_HOSTNAME}.pem" ]] \
  || fail "TLS certificate for ${BOT_HOSTNAME} is missing"
sed "s/__BOT_HOSTNAME__/${BOT_HOSTNAME}/g" deploy/nginx/bot.local.conf \
  >/etc/nginx/sites-available/bot.local
install -m 0644 deploy/nginx/pi_api.conf /etc/nginx/snippets/pi_api.conf
ln -sfn /etc/nginx/sites-available/bot.local /etc/nginx/sites-enabled/bot.local
rm -f /etc/nginx/sites-enabled/default
install -d -m 0755 /etc/systemd/journald.conf.d /etc/fail2ban/jail.d
install -m 0644 deploy/system/journald-ladder-dragon.conf \
  /etc/systemd/journald.conf.d/ladder-dragon.conf
install -m 0644 deploy/system/fail2ban-sshd.local /etc/fail2ban/jail.d/sshd.local
[[ -d /etc/default ]] && install -m 0644 deploy/system/zramswap /etc/default/zramswap

render_unit() {
  sed \
    -e "s#/home/bot/apps/binance_bot#${PROJECT_DIR}#g" \
    -e "s/^User=bot$/User=${BOT_USER}/" \
    -e "s/^Group=bot$/Group=${BOT_USER}/" \
    "$1" >"$2"
  chmod 0644 "$2"
}
render_unit deploy/mybot.service /etc/systemd/system/mybot.service
render_unit deploy/pi-dashboard.service /etc/systemd/system/pi-healthd.service
render_unit deploy/ladder-dragon-backup.service \
  /etc/systemd/system/ladder-dragon-backup.service
install -m 0644 deploy/ladder-dragon-backup.timer \
  /etc/systemd/system/ladder-dragon-backup.timer
rm -f /etc/systemd/system/mybot.service.d/dashboard-link.conf

if [[ -d "${WEB_ROOT}/backups" ]]; then
  legacy_dest="/var/lib/ladder-dragon/backups/legacy-public-$(date -u +%Y%m%d%H%M%S)"
  mv "${WEB_ROOT}/backups" "${legacy_dest}"
  chmod -R go-rwx "${legacy_dest}"
fi

runuser -u "${BOT_USER}" -- .venv/bin/python -m compileall -q \
  ai_supervisor.py autosize_universal.py FastAPI/pi-dashboard
runuser -u "${BOT_USER}" -- .venv/bin/python ai_supervisor.py --version
nginx -t

systemctl daemon-reload
systemctl disable --now make-pi-backup.timer make-pi-backup.service 2>/dev/null || true
restore_autostart
systemctl enable ladder-dragon-backup.timer >/dev/null
systemctl start mybot
systemctl start pi-healthd
systemctl start ladder-dragon-backup.timer
systemctl restart systemd-journald
systemctl try-restart fail2ban || true
systemctl try-restart zramswap || true
systemctl reload nginx

wait_for_service mybot 90
wait_for_service pi-healthd 90
wait_for_heartbeat 120
check_link
SERVICES_STOPPED=0
trap - ERR INT TERM
