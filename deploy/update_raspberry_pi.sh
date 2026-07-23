#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: update an existing Raspberry Pi deployment.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/bot/apps/binance_bot}"
WEB_ROOT="${WEB_ROOT:-/var/www/bot}"
DASHBOARD_ENV="${PROJECT_DIR}/.env.dashboard"
BOT_HOSTNAME="${BOT_HOSTNAME:-$(hostname -s).local}"
BOT_USER="${BOT_USER:-$(stat -c '%U' "${PROJECT_DIR}" 2>/dev/null || echo bot)}"
UPDATE_TRUST_CONFIG="/etc/ladder-dragon/update-trust.conf"
BREAK_GLASS_MARKER="/run/ladder-dragon/update-break-glass"
ACTION="${1:-update}"
UPDATE_COMMIT="${2:-${BOT_UPDATE_COMMIT:-}}"
MYBOT_WAS_ACTIVE=0
DASHBOARD_WAS_ACTIVE=0
MYBOT_WAS_ENABLED=0
DASHBOARD_WAS_ENABLED=0
WATCHDOG_WAS_ACTIVE=0
WATCHDOG_WAS_ENABLED=0
SERVICES_STOPPED=0

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

verify_trusted_commit() {
  local commit="$1"
  local signer="$2"
  local verification
  [[ "${signer}" =~ ^[0-9A-Fa-f]{40,64}$ ]] \
    || fail "root update trust config must contain a full GPG fingerprint"
  verification="$(runuser -u "${BOT_USER}" -- git verify-commit --raw "${commit}" 2>&1)" \
    || fail "Git signature verification failed for ${commit}"
  grep -Eiq "\[GNUPG:\] VALIDSIG [^[:cntrl:]]*${signer}([[:space:]]|$)" <<<"${verification}" \
    || fail "commit ${commit} is not signed by trusted fingerprint ${signer}"
}

load_trusted_signer() {
  [[ -f "${UPDATE_TRUST_CONFIG}" ]] \
    || fail "missing root update trust config: ${UPDATE_TRUST_CONFIG}"
  [[ "$(stat -c '%u' "${UPDATE_TRUST_CONFIG}")" == "0" ]] \
    || fail "update trust config must be owned by root"
  [[ "$(stat -c '%a' "${UPDATE_TRUST_CONFIG}")" == "600" ]] \
    || fail "update trust config must have mode 0600"
  python3 deploy/read_update_trust.py "${UPDATE_TRUST_CONFIG}" \
    || fail "invalid update trust config"
}

consume_break_glass() {
  local commit="${1,,}"
  [[ -f "${BREAK_GLASS_MARKER}" ]] || return 1
  [[ "$(stat -c '%u' "${BREAK_GLASS_MARKER}")" == "0" ]] \
    || fail "break-glass marker must be owned by root"
  [[ "$(stat -c '%a' "${BREAK_GLASS_MARKER}")" == "600" ]] \
    || fail "break-glass marker must have mode 0600"
  [[ "$(tr -d '\r\n' <"${BREAK_GLASS_MARKER}")" == "${commit}" ]] \
    || fail "break-glass marker does not authorize commit ${commit}"
  rm -f "${BREAK_GLASS_MARKER}"
  logger --priority authpriv.warning --tag ladder-dragon-update \
    "BREAK_GLASS consumed unsigned update commit=${commit}"
  echo "[BREAK-GLASS] consuming one-use authorization for ${commit}" >&2
  return 0
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
  WATCHDOG_WAS_ACTIVE="$(service_flag is-active pi-watchdog-v3.timer)"
  WATCHDOG_WAS_ENABLED="$(service_flag is-enabled pi-watchdog-v3.timer)"
}

restore_autostart() {
  # Preserve the administrator's boot policy instead of silently enabling units.
  local unit state
  for unit in mybot pi-healthd pi-watchdog-v3.timer; do
    case "${unit}" in
      mybot) state="${MYBOT_WAS_ENABLED}" ;;
      pi-healthd) state="${DASHBOARD_WAS_ENABLED}" ;;
      pi-watchdog-v3.timer) state="${WATCHDOG_WAS_ENABLED}" ;;
    esac
    if [[ "${state}" == "1" ]]; then
      systemctl enable "${unit}" >/dev/null
    else
      systemctl disable "${unit}" >/dev/null
    fi
  done
}

start_previous_services() {
  restore_autostart
  if [[ "${MYBOT_WAS_ACTIVE}" == "1" ]]; then
    systemctl start mybot
  fi
  if [[ "${DASHBOARD_WAS_ACTIVE}" == "1" ]]; then
    systemctl start pi-healthd
  fi
  # A watchdog must never revive a bot that was intentionally stopped.
  if [[ "${MYBOT_WAS_ACTIVE}" == "1" && "${WATCHDOG_WAS_ACTIVE}" == "1" ]]; then
    systemctl start pi-watchdog-v3.timer
  fi
}

verify_previous_service_state() {
  local unit expected
  for unit in mybot pi-healthd; do
    case "${unit}" in
      mybot) expected="${MYBOT_WAS_ACTIVE}" ;;
      pi-healthd) expected="${DASHBOARD_WAS_ACTIVE}" ;;
    esac
    if [[ "${expected}" == "1" ]]; then
      wait_for_service "${unit}" 90
    elif systemctl is-active --quiet "${unit}"; then
      fail "${unit} was stopped before update but became active"
    fi
  done
  if [[ "${MYBOT_WAS_ACTIVE}" == "0" ]] \
    && systemctl is-active --quiet pi-watchdog-v3.timer; then
    fail "watchdog timer is active while the previously stopped bot remains stopped"
  fi
  for unit in mybot pi-healthd pi-watchdog-v3.timer; do
    case "${unit}" in
      mybot) expected="${MYBOT_WAS_ENABLED}" ;;
      pi-healthd) expected="${DASHBOARD_WAS_ENABLED}" ;;
      pi-watchdog-v3.timer) expected="${WATCHDOG_WAS_ENABLED}" ;;
    esac
    [[ "$(service_flag is-enabled "${unit}")" == "${expected}" ]] \
      || fail "${unit} autostart policy changed during update"
  done
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
    ready_states = {"RUNNING", "AUTH_BACKOFF"}
    raise SystemExit(
        0 if status.get("state") in ready_states and 0 <= age <= 90 else 1
    )
except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
PY
  do
    (( SECONDS >= deadline )) \
      && fail "fresh RUNNING/AUTH_BACKOFF heartbeat was not received in ${timeout_sec}s"
    sleep 2
  done
}

check_link() {
  systemctl is-active --quiet mybot || fail "mybot is not active"
  systemctl is-active --quiet pi-healthd || fail "pi-healthd is not active"
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
  local forged_proxy_status
  forged_proxy_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    -H 'X-Authenticated-User: dashboard' \
    http://127.0.0.1:8081/api/health)"
  [[ "${forged_proxy_status}" == "401" ]] \
    || fail "forged local proxy header was accepted: HTTP ${forged_proxy_status}"
  local anonymous_logs_status
  anonymous_logs_status="$(
    curl --insecure --silent --output /dev/null --write-out '%{http_code}' \
      --resolve "${BOT_HOSTNAME}:443:127.0.0.1" \
      "https://${BOT_HOSTNAME}/logs/"
  )"
  [[ "${anonymous_logs_status}" == "401" ]] \
    || fail "expected protected logs HTTP 401, got ${anonymous_logs_status}"
  local anonymous_backups_status
  anonymous_backups_status="$(
    curl --insecure --silent --output /dev/null --write-out '%{http_code}' \
      --resolve "${BOT_HOSTNAME}:443:127.0.0.1" \
      "https://${BOT_HOSTNAME}/backups/"
  )"
  [[ "${anonymous_backups_status}" == "401" ]] \
    || fail "expected protected backups HTTP 401, got ${anonymous_backups_status}"
  test -r /var/lib/ladder-dragon/backups-public/index.txt \
    || fail "public backup manifest is missing"
  test -r /var/lib/ladder-dragon/logs/current.log \
    || fail "sanitized current.log is missing"
  echo "[OK] bot/dashboard heartbeat, permissions and protected API are ready"
  python3 -m json.tool /run/mybot/ai_status.json
}

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo --preserve-env=PROJECT_DIR,WEB_ROOT,BOT_HOSTNAME,BOT_USER,BOT_UPDATE_COMMIT "$0" "$@"
fi

[[ -d "${PROJECT_DIR}" ]] || fail "project directory not found: ${PROJECT_DIR}"
cd "${PROJECT_DIR}"

# The update may replace this script. Continue from an immutable copy in /tmp,
# so bash does not read the second half from a newly installed version.
if [[ "${ACTION}" == "update" && "${BOT_UPDATE_RUNNER:-0}" != "1" ]]; then
  runner="$(mktemp /tmp/ladder-dragon-update.XXXXXX)"
  install -m 0700 "$0" "${runner}"
  exec env BOT_UPDATE_RUNNER=1 PROJECT_DIR="${PROJECT_DIR}" WEB_ROOT="${WEB_ROOT}" \
    BOT_HOSTNAME="${BOT_HOSTNAME}" BOT_USER="${BOT_USER}" \
    bash "${runner}" update "${UPDATE_COMMIT}"
fi

if [[ "${ACTION}" == "check" ]]; then
  check_link
  exit 0
fi
[[ "${ACTION}" == "update" || "${ACTION}" == "apply" ]] \
  || fail "usage: $0 [update COMMIT_SHA|apply|check]"
if [[ "${ACTION}" == "update" ]]; then
  [[ "${UPDATE_COMMIT}" =~ ^[0-9a-fA-F]{40}$ ]] \
    || fail "update requires an exact 40-character commit SHA"
fi

[[ -f .env ]] || fail "configure ${PROJECT_DIR}/.env before deployment"
[[ -f .env.service ]] \
  || fail ".env.service is missing; run install_raspberry_pi.sh migrate first"
systemctl cat mybot 2>/dev/null | grep -q 'deploy/run_bot_service.sh' \
  || fail "legacy mybot.service detected; run install_raspberry_pi.sh migrate first"
if [[ ! -f "${DASHBOARD_ENV}" ]]; then
  install -m 0600 .env.dashboard.example "${DASHBOARD_ENV}"
  fail "created ${DASHBOARD_ENV}; replace placeholder dashboard tokens/keys, then run again"
fi

[[ -r /etc/ladder-dragon/backup.env ]] \
  || fail "/etc/ladder-dragon/backup.env is missing; run installer migrate"
python3 deploy/read_backup_env.py /etc/ladder-dragon/backup.env >/dev/null
mapfile -d '' -t backup_values < <(
  python3 deploy/read_backup_env.py /etc/ladder-dragon/backup.env
)
[[ "${#backup_values[@]}" -eq 4 ]] || fail "backup.env validation failed"
export BACKUP_AGE_RECIPIENT="${backup_values[0]}"
export BACKUP_EXTERNAL_MOUNT="${backup_values[1]}"
export BACKUP_EXTERNAL_DIR="${backup_values[2]}"
export BACKUP_EXTERNAL_RETENTION_DAYS="${backup_values[3]}"
PROJECT_DIR="${PROJECT_DIR}" deploy/backup_raspberry_pi.sh

# First record the systemd state. `systemctl stop` does not remove enabled:
# autostart remains configured, while Restart=always cannot mix versions during the update.
remember_service_state
trap recover_after_failure ERR INT TERM
SERVICES_STOPPED=1
systemctl stop mybot
systemctl stop pi-healthd
systemctl stop pi-watchdog-v3.timer

if [[ "${ACTION}" == "update" ]]; then
  [[ -z "$(runuser -u "${BOT_USER}" -- git status --porcelain --untracked-files=no)" ]] \
    || fail "tracked project files have local changes; commit or stash them first"
  runuser -u "${BOT_USER}" -- git fetch --prune origin
  runuser -u "${BOT_USER}" -- git cat-file -e "${UPDATE_COMMIT}^{commit}"
  upstream="$(runuser -u "${BOT_USER}" -- git rev-parse --abbrev-ref '@{upstream}')"
  runuser -u "${BOT_USER}" -- git merge-base --is-ancestor HEAD "${UPDATE_COMMIT}" \
    || fail "requested commit is not a fast-forward from current HEAD"
  runuser -u "${BOT_USER}" -- git merge-base --is-ancestor "${UPDATE_COMMIT}" "${upstream}" \
    || fail "requested commit is not contained in ${upstream}"
  if consume_break_glass "${UPDATE_COMMIT}"; then
    :
  else
    trusted_signer="$(load_trusted_signer)"
    verify_trusted_commit "${UPDATE_COMMIT}" "${trusted_signer}"
  fi
  runuser -u "${BOT_USER}" -- git merge --ff-only "${UPDATE_COMMIT}"
  runuser -u "${BOT_USER}" -- .venv/bin/python -m pip install \
    --require-hashes -r requirements/raspberry.lock
  runuser -u "${BOT_USER}" -- .venv/bin/python -m pip install \
    --no-deps --no-build-isolation -e .
fi

# This helper is read from the verified target checkout after the merge. Keeping
# release-owned runtime assets outside the immutable updater prevents a previous
# updater version from omitting files introduced by the new signed release.
[[ -x deploy/install_runtime_assets.sh ]] \
  || fail "verified release runtime-asset installer is missing or not executable"
PROJECT_DIR="${PROJECT_DIR}" deploy/install_runtime_assets.sh

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

set_env_value() {
  local file="$1"
  local name="$2"
  local value="$3"
  if grep -q "^${name}=" "${file}"; then
    sed -i "s#^${name}=.*#${name}=${value}#" "${file}"
  else
    printf '%s=%s\n' "${name}" "${value}" >>"${file}"
  fi
}

dashboard_token="$(
  sed -n 's/^DASHBOARD_AUTH_TOKEN=//p' "${DASHBOARD_ENV}" | head -1
)"
if [[ ! "${dashboard_token}" =~ ^[0-9a-fA-F]{64,}$ ]]; then
  set_env_value "${DASHBOARD_ENV}" DASHBOARD_AUTH_TOKEN "$(openssl rand -hex 32)"
fi
dashboard_proxy_secret="$(
  sed -n 's/^DASHBOARD_PROXY_AUTH_SECRET=//p' "${DASHBOARD_ENV}" | head -1
)"
if [[ ! "${dashboard_proxy_secret}" =~ ^[0-9a-fA-F]{64,}$ ]]; then
  dashboard_proxy_secret="$(openssl rand -hex 32)"
  set_env_value "${DASHBOARD_ENV}" DASHBOARD_PROXY_AUTH_SECRET "${dashboard_proxy_secret}"
fi
chmod 0600 "${DASHBOARD_ENV}"

install -d -o "${BOT_USER}" -g "${BOT_USER}" -m 0700 db logs FastAPI/pi-dashboard/data
install -d -o root -g www-data -m 0750 /var/lib/ladder-dragon/logs
install -d -o root -g www-data -m 0750 /var/lib/ladder-dragon/backups-public
if [[ ! -e /etc/ladder-dragon/telegram.env && -f /etc/bot-alerts.env ]]; then
  install -o root -g "${BOT_USER}" -m 0640 /etc/bot-alerts.env \
    /etc/ladder-dragon/telegram.env
elif [[ -e /etc/ladder-dragon/telegram.env ]]; then
  chown root:"${BOT_USER}" /etc/ladder-dragon/telegram.env
  chmod 0640 /etc/ladder-dragon/telegram.env
fi
if [[ -s /etc/ladder-dragon/telegram.env && -f /etc/bot-alerts.env ]]; then
  rm -f -- /etc/bot-alerts.env
fi
install -d -o root -g root -m 0755 "${WEB_ROOT}" "${WEB_ROOT}/vendor"
install -d -m 0755 /etc/nginx/snippets
install -o root -g www-data -m 0640 /dev/null \
  /etc/nginx/snippets/ladder_dragon_proxy_secret.conf
printf 'proxy_set_header X-Dashboard-Proxy-Secret "%s";\n' \
  "${dashboard_proxy_secret}" \
  >/etc/nginx/snippets/ladder_dragon_proxy_secret.conf
  install -m 0644 FRONT/index.html FRONT/help.html FRONT/locales.js docs/assets/ladder-dragon-logo.svg docs/assets/ladder-dragon-dashboard-icon.svg CHANGELOG.md "${WEB_ROOT}/"
install -m 0644 FRONT/vendor/chart.umd.min.js "${WEB_ROOT}/vendor/"
install -m 0644 FRONT/vendor/chart.js.LICENSE.txt "${WEB_ROOT}/vendor/"
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
render_unit deploy/ladder-dragon-log-export.service \
  /etc/systemd/system/ladder-dragon-log-export.service
install -m 0644 deploy/ladder-dragon-log-export.timer \
  /etc/systemd/system/ladder-dragon-log-export.timer
render_unit deploy/ladder-dragon-depth-archive.service \
  /etc/systemd/system/ladder-dragon-depth-archive.service
install -m 0644 deploy/ladder-dragon-depth-archive.timer \
  /etc/systemd/system/ladder-dragon-depth-archive.timer
install -d -o "${BOT_USER}" -g "${BOT_USER}" -m 0750 \
  /var/lib/ladder-dragon/depth-archives

backup_mount_dropin="/etc/systemd/system/ladder-dragon-backup.service.d/external-mount.conf"
rm -f "${backup_mount_dropin}"
if [[ -n "${BACKUP_EXTERNAL_MOUNT:-}" ]]; then
  [[ "${BACKUP_EXTERNAL_MOUNT}" =~ ^/[A-Za-z0-9._/@+-]+$ ]] \
    || fail "invalid BACKUP_EXTERNAL_MOUNT path"
  install -d -m 0755 "$(dirname "${backup_mount_dropin}")"
  printf '[Unit]\nRequiresMountsFor=%s\n\n[Service]\nReadWritePaths=%s\n' \
    "${BACKUP_EXTERNAL_MOUNT}" "${BACKUP_EXTERNAL_MOUNT}" \
    >"${backup_mount_dropin}"
  chmod 0644 "${backup_mount_dropin}"
fi
install -m 0644 deploy/pi-watchdog-v3.service \
  /etc/systemd/system/pi-watchdog-v3.service
install -m 0644 deploy/pi-watchdog-v3.timer \
  /etc/systemd/system/pi-watchdog-v3.timer
rm -f /etc/systemd/system/pi-watchdog-v3.service.d/rc-ok.conf
rm -f /etc/systemd/system/mybot.service.d/dashboard-link.conf
systemctl disable --now ai-supervisor.service binance-bot.service 2>/dev/null || true
rm -f /etc/systemd/system/ai-supervisor.service \
  /etc/systemd/system/binance-bot.service \
  /etc/nginx/sites-enabled/pi-dashboard \
  /etc/nginx/sites-available/pi-dashboard
if [[ -d /opt/pi-dashboard ]]; then
  install -d -m 0700 /var/lib/ladder-dragon/legacy
  mv /opt/pi-dashboard \
    "/var/lib/ladder-dragon/legacy/pi-dashboard-$(date -u +%Y%m%d%H%M%S)"
fi

if [[ -d "${WEB_ROOT}/backups" ]]; then
  legacy_dest="/var/lib/ladder-dragon/backups/legacy-public-$(date -u +%Y%m%d%H%M%S)"
  mv "${WEB_ROOT}/backups" "${legacy_dest}"
  chmod -R go-rwx "${legacy_dest}"
fi

runuser -u "${BOT_USER}" -- .venv/bin/python -m compileall -q \
  bin ladder_dragon FastAPI/pi-dashboard
runuser -u "${BOT_USER}" -- .venv/bin/python \
  deploy/validate_security_config.py "${PROJECT_DIR}"
runuser -u "${BOT_USER}" -- .venv/bin/python -m bin.ai_supervisor --version
nginx -t

systemctl daemon-reload
systemctl disable --now make-pi-backup.timer make-pi-backup.service 2>/dev/null || true
restore_autostart
systemctl enable ladder-dragon-backup.timer ladder-dragon-log-export.timer \
  ladder-dragon-depth-archive.timer \
  >/dev/null
start_previous_services
systemctl start ladder-dragon-backup.timer
systemctl start ladder-dragon-backup.service
systemctl start ladder-dragon-log-export.service ladder-dragon-log-export.timer
systemctl start ladder-dragon-depth-archive.timer
systemctl restart systemd-journald
systemctl try-restart fail2ban || true
systemctl try-restart zramswap || true
systemctl reload nginx

verify_previous_service_state
if [[ "${MYBOT_WAS_ACTIVE}" == "1" ]]; then
  wait_for_heartbeat 120
fi
test -r /var/lib/ladder-dragon/logs/current.log || fail "log export failed"
grep -q '^DASHBOARD_AUTH_TOKEN=replace_' "${DASHBOARD_ENV}" \
  && fail "placeholder dashboard token remains"
if [[ "${MYBOT_WAS_ACTIVE}" == "1" && "${DASHBOARD_WAS_ACTIVE}" == "1" ]]; then
  check_link
else
  echo "[OK] preserved service state: mybot_active=${MYBOT_WAS_ACTIVE} dashboard_active=${DASHBOARD_WAS_ACTIVE}"
fi
SERVICES_STOPPED=0
trap - ERR INT TERM
