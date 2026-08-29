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
CONTROL_DIR="/var/lib/ladder-dragon/control"
ACTION="${1:-update}"
UPDATE_COMMIT="${2:-${BOT_UPDATE_COMMIT:-}}"
MYBOT_WAS_ACTIVE=0
DASHBOARD_WAS_ACTIVE=0
MYBOT_WAS_ENABLED=0
DASHBOARD_WAS_ENABLED=0
WATCHDOG_WAS_ACTIVE=0
WATCHDOG_WAS_ENABLED=0
SERVICES_STOPPED=0
PREVIOUS_HEAD=""
CHECKOUT_ADVANCED=0
EXTERNAL_DEPLOYMENT_MUTATED=0
MIGRATE_RECONCILE_TOLERANCE=0
MIGRATE_DASHBOARD_RATE_LIMIT=0

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

set_env_value() {
  local file="$1"
  local name="$2"
  local value="$3"
  local temporary line found=0
  [[ "${name}" =~ ^[A-Z][A-Z0-9_]*$ ]] \
    || fail "invalid environment variable name"
  [[ "${value}" != *$'\n'* && "${value}" != *$'\r'* ]] \
    || fail "environment value contains a line break"
  temporary="$(mktemp "${file}.tmp.XXXXXX")"
  while IFS= read -r line || [[ -n "${line}" ]]; do
    if [[ "${line}" == "${name}="* ]]; then
      printf '%s=%s\n' "${name}" "${value}" >>"${temporary}"
      found=1
    else
      printf '%s\n' "${line}" >>"${temporary}"
    fi
  done <"${file}"
  if [[ "${found}" == "0" ]]; then
    printf '%s=%s\n' "${name}" "${value}" >>"${temporary}"
  fi
  chown --reference="${file}" "${temporary}"
  chmod --reference="${file}" "${temporary}"
  mv -f -- "${temporary}" "${file}"
}

prepare_persistent_control() {
  local name source target
  install -d -o "${BOT_USER}" -g "${BOT_USER}" -m 0700 "${CONTROL_DIR}"
  for name in circuit_halt.json risk_state.json risk_alerts.ndjson; do
    source="/run/mybot/${name}"
    target="${CONTROL_DIR}/${name}"
    [[ -f "${source}" ]] || continue
    if [[ -f "${target}" ]]; then
      cmp -s "${source}" "${target}" \
        || fail "runtime and persistent control evidence conflict: ${name}"
      continue
    fi
    install -o "${BOT_USER}" -g "${BOT_USER}" -m 0600 \
      "${source}" "${target}"
  done
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

bootstrap_verified_target_runner() {
  local commit="$1"
  local runner trusted_signer upstream
  # Break-glass remains on the already installed immutable updater. Never
  # execute unsigned target code before its one-use authorization is consumed.
  [[ ! -f "${BREAK_GLASS_MARKER}" ]] || return 1
  [[ "${commit}" =~ ^[0-9a-fA-F]{40}$ ]] \
    || fail "update requires an exact 40-character commit SHA"
  [[ -z "$(runuser -u "${BOT_USER}" -- git status --porcelain --untracked-files=no)" ]] \
    || fail "tracked project files have local changes; commit or stash them first"
  runuser -u "${BOT_USER}" -- git fetch --prune origin
  runuser -u "${BOT_USER}" -- git cat-file -e "${commit}^{commit}"
  upstream="$(runuser -u "${BOT_USER}" -- git rev-parse --abbrev-ref '@{upstream}')"
  runuser -u "${BOT_USER}" -- git merge-base --is-ancestor HEAD "${commit}" \
    || fail "requested commit is not a fast-forward from current HEAD"
  runuser -u "${BOT_USER}" -- git merge-base --is-ancestor "${commit}" "${upstream}" \
    || fail "requested commit is not contained in ${upstream}"
  trusted_signer="$(load_trusted_signer)"
  verify_trusted_commit "${commit}" "${trusted_signer}"
  runner="$(mktemp /tmp/ladder-dragon-target-update.XXXXXX)"
  runuser -u "${BOT_USER}" -- git show \
    "${commit}:deploy/update_raspberry_pi.sh" >"${runner}" \
    || {
      rm -f "${runner}"
      fail "verified target commit has no updater"
    }
  chmod 0700 "${runner}"
  exec env BOT_UPDATE_TARGET_RUNNER=1 PROJECT_DIR="${PROJECT_DIR}" \
    WEB_ROOT="${WEB_ROOT}" BOT_HOSTNAME="${BOT_HOSTNAME}" \
    BOT_USER="${BOT_USER}" bash "${runner}" update "${commit}"
}

run_preupdate_backup() {
  local commit="$1" backup_runner backup_status
  if [[ "${BOT_UPDATE_TARGET_RUNNER:-0}" != "1" ]]; then
    PROJECT_DIR="${PROJECT_DIR}" deploy/backup_raspberry_pi.sh
    return
  fi

  # The verified target backup must enforce new retention before checkout.
  backup_runner="$(mktemp /tmp/ladder-dragon-target-backup.XXXXXX)"
  runuser -u "${BOT_USER}" -- git show \
    "${commit}:deploy/backup_raspberry_pi.sh" >"${backup_runner}" \
    || {
      rm -f "${backup_runner}"
      fail "verified target commit has no backup runner"
    }
  chmod 0700 "${backup_runner}"
  if PROJECT_DIR="${PROJECT_DIR}" bash "${backup_runner}"; then
    backup_status=0
  else
    backup_status=$?
  fi
  rm -f "${backup_runner}"
  return "${backup_status}"
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

restore_previous_checkout() {
  local current_head
  [[ "${ACTION}" == "update" && "${CHECKOUT_ADVANCED}" == "1" ]] || return 0
  [[ "${PREVIOUS_HEAD}" =~ ^[0-9a-fA-F]{40}$ ]] || return 1
  current_head="$(runuser -u "${BOT_USER}" -- git rev-parse HEAD)" || return 1
  [[ "${current_head}" != "${PREVIOUS_HEAD}" ]] || return 0
  echo "[RECOVERY] restoring previous commit and dependency lock" >&2
  runuser -u "${BOT_USER}" -- git reset --hard "${PREVIOUS_HEAD}" || return 1
  [[ "$(runuser -u "${BOT_USER}" -- git rev-parse HEAD)" == "${PREVIOUS_HEAD}" ]] \
    || return 1
  runuser -u "${BOT_USER}" -- .venv/bin/python -m pip install \
    --require-hashes -r requirements/raspberry.lock || return 1
  runuser -u "${BOT_USER}" -- .venv/bin/python -m pip install \
    --no-deps --no-build-isolation -e . || return 1
  runuser -u "${BOT_USER}" -- .venv/bin/python -m pip check || return 1
  runuser -u "${BOT_USER}" -- .venv/bin/python -m compileall -q \
    bin ladder_dragon FastAPI/pi-dashboard || return 1
}

start_recovery_dashboard() {
  systemctl daemon-reload || true
  systemctl stop mybot pi-watchdog-v3.timer || true
  restore_autostart || true
  if ! systemctl start pi-healthd; then
    echo "[RECOVERY-BLOCKED] dashboard could not be started" >&2
  fi
}

recover_after_failure() {
  local status=$?
  local rollback_ok=1
  trap - ERR INT TERM
  if [[ "${SERVICES_STOPPED}" == "1" ]]; then
    if ! restore_previous_checkout; then
      rollback_ok=0
    fi
    if [[ "${rollback_ok}" == "1" && "${EXTERNAL_DEPLOYMENT_MUTATED}" == "0" ]]; then
      echo "[RECOVERY] previous release restored; restoring prior service state" >&2
      start_previous_services || true
    else
      start_recovery_dashboard
      echo "[RECOVERY-BLOCKED] mybot remains stopped because a coherent previous runtime could not be proven" >&2
      echo "[RECOVERY-BLOCKED] repair dependencies/deployment assets, verify HEAD, then restart explicitly" >&2
    fi
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
    ready_states = {
        "RUNNING", "AUTH_BACKOFF", "PREFLIGHT_BACKOFF", "IP_BLOCKED",
        "RECOVERY_BLOCKED", "RISK_PENDING"
    }
    raise SystemExit(
        0 if status.get("state") in ready_states and 0 <= age <= 90 else 1
    )
except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
PY
  do
    (( SECONDS >= deadline )) \
      && fail "fresh RUNNING/fail-closed heartbeat was not received in ${timeout_sec}s"
    sleep 2
  done
}

dashboard_database_status() {
  local dashboard_token
  dashboard_token="$(
    sed -n 's/^DASHBOARD_AUTH_TOKEN=//p' "${DASHBOARD_ENV}" | head -1
  )"
  [[ "${dashboard_token}" =~ ^[0-9a-fA-F]{64,}$ ]] \
    || fail "malformed DASHBOARD_AUTH_TOKEN"
  # Pass the credential over stdin, never argv, logs or a temporary file.
  printf '%s\n' \
    'silent' \
    'output = "/dev/null"' \
    'write-out = "%{http_code}"' \
    "header = \"Authorization: Bearer ${dashboard_token}\"" \
    'url = "http://127.0.0.1:8081/api/trades/symbols?hours=1"' \
    | curl --config - 2>/dev/null || true
}

wait_for_dashboard_database() {
  local timeout_sec="${1:-30}"
  local deadline=$((SECONDS + timeout_sec))
  local status=""
  while true; do
    status="$(dashboard_database_status)"
    [[ "${status}" == "200" ]] && return 0
    if [[ "${status}" == "401" || "${status}" == "403" ]]; then
      fail "authenticated dashboard database readiness was rejected: HTTP ${status}"
    fi
    (( SECONDS >= deadline )) \
      && fail "dashboard database did not become ready in ${timeout_sec}s (HTTP ${status:-000})"
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
  local runtime_state
  runtime_state="$(python3 -c \
    'import json; print(json.load(open("/run/mybot/ai_status.json"))["state"])')"
  if [[ "${runtime_state}" != "RUNNING" ]]; then
    echo "[WARN] supervisor is alive but fail-closed: ${runtime_state}" >&2
  fi
  wait_for_dashboard_database 30
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

publish_verified_deployment_status() {
  local commit version runtime_state publish_status
  commit="$(runuser -u "${BOT_USER}" -- git rev-parse HEAD)"
  version="$(runuser -u "${BOT_USER}" -- .venv/bin/python -c \
    'from product_version import __version__; print(__version__)')"
  runtime_state="$(python3 -c \
    'import json; print(json.load(open("/run/mybot/ai_status.json"))["state"])')"
  if .venv/bin/python -m ladder_dragon.deployment.status \
    --commit "${commit}" --version "${version}" \
    --runtime-state "${runtime_state}"; then
    return 0
  else
    publish_status="$?"
  fi
  if [[ "${publish_status}" == "2" ]]; then
    echo "[WARN] deployment status passed, but its Telegram notice was not delivered" >&2
    return 0
  fi
  fail "verified deployment status could not be published"
}

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo --preserve-env=PROJECT_DIR,WEB_ROOT,BOT_HOSTNAME,BOT_USER,BOT_UPDATE_COMMIT "$0" "$@"
fi

[[ -d "${PROJECT_DIR}" ]] || fail "project directory not found: ${PROJECT_DIR}"
cd "${PROJECT_DIR}"

# Execute the updater from the verified target commit before any backup or
# service mutation. New deployment steps therefore apply on the first update,
# while the target script remains immutable when the checkout fast-forwards.
if [[ "${ACTION}" == "update" && "${BOT_UPDATE_TARGET_RUNNER:-0}" != "1" ]]; then
  if bootstrap_verified_target_runner "${UPDATE_COMMIT}"; then
    fail "target updater unexpectedly returned"
  fi
fi

# Unsigned break-glass and explicit apply retain the installed immutable
# updater; they never execute unverified target code.
if [[ ( "${ACTION}" == "update" || "${ACTION}" == "apply" ) \
  && "${BOT_UPDATE_TARGET_RUNNER:-0}" != "1" \
  && "${BOT_UPDATE_RUNNER:-0}" != "1" ]]; then
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

# Hold shared recovery authority across both backups and the complete update.
# The exclusive network guard cannot reconnect or reboot during this interval.
install -d -m 0755 /var/lib/ladder-dragon
exec 19>>/var/lib/ladder-dragon/network-recovery.lock
flock -s -w 45 19 || fail "network recovery is active; update deferred"
if [[ -r /var/lib/pi-watchdog/network-reboot.boot ]] && \
  cmp -s /var/lib/pi-watchdog/network-reboot.boot /proc/sys/kernel/random/boot_id; then
  fail "network reboot is pending; update deferred"
fi

[[ -f .env ]] || fail "configure ${PROJECT_DIR}/.env before deployment"
if ! grep -q '^RISK_RECONCILE_TOLERANCE_FRACTION=' .env; then
  legacy_reconcile_tolerance="$(
    sed -n 's/^RISK_RECONCILE_TOLERANCE_PCT=//p' .env | head -1
  )"
  case "${legacy_reconcile_tolerance}" in
    ""|0.02) MIGRATE_RECONCILE_TOLERANCE=1 ;;
    *) fail "custom legacy reconciliation tolerance requires explicit migration" ;;
  esac
fi
[[ -f .env.service ]] \
  || fail ".env.service is missing; run install_raspberry_pi.sh migrate first"
systemctl cat mybot 2>/dev/null | grep -q 'deploy/run_bot_service.sh' \
  || fail "legacy mybot.service detected; run install_raspberry_pi.sh migrate first"
if [[ ! -f "${DASHBOARD_ENV}" ]]; then
  install -m 0600 .env.dashboard.example "${DASHBOARD_ENV}"
  fail "created ${DASHBOARD_ENV}; replace placeholder dashboard tokens/keys, then run again"
fi
dashboard_rate_limit="$(
  sed -n 's/^DASHBOARD_RATE_LIMIT_PER_MIN=//p' "${DASHBOARD_ENV}" | head -1
)"
case "${dashboard_rate_limit}" in
  ""|120) MIGRATE_DASHBOARD_RATE_LIMIT=1 ;;
  *) : ;;
esac

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
run_preupdate_backup "${UPDATE_COMMIT}"

# Copy authoritative control evidence before stopping the legacy unit:
# systemd removes an unpreserved RuntimeDirectory during stop.
prepare_persistent_control

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
  PREVIOUS_HEAD="$(runuser -u "${BOT_USER}" -- git rev-parse HEAD)"
  runuser -u "${BOT_USER}" -- git merge --ff-only "${UPDATE_COMMIT}"
  if [[ "$(runuser -u "${BOT_USER}" -- git rev-parse HEAD)" != "${PREVIOUS_HEAD}" ]]; then
    CHECKOUT_ADVANCED=1
  fi
  runuser -u "${BOT_USER}" -- .venv/bin/python -m pip install \
    --require-hashes -r requirements/raspberry.lock
  runuser -u "${BOT_USER}" -- .venv/bin/python -m pip install \
    --no-deps --no-build-isolation -e .
fi

# This helper is read from the verified target checkout after the merge. Keeping
# release-owned runtime assets outside the immutable updater prevents a previous
# updater version from omitting files introduced by the new signed release.
EXTERNAL_DEPLOYMENT_MUTATED=1
[[ -x deploy/install_runtime_assets.sh ]] \
  || fail "verified release runtime-asset installer is missing or not executable"
PROJECT_DIR="${PROJECT_DIR}" deploy/install_runtime_assets.sh

set_env_value .env BOT_TESTNET_RUN_DIR /run/mybot/testnet
set_env_value .env AI_RUNTIME_STATUS_FILE /run/mybot/ai_status.json
set_env_value .env BINANCE_AUTH_STATE_FILE \
  "${PROJECT_DIR}/db/auth_resilience.json"
if [[ "${MIGRATE_RECONCILE_TOLERANCE}" == "1" ]]; then
  set_env_value .env RISK_RECONCILE_TOLERANCE_FRACTION 0.001
fi
if ! grep -q '^BINANCE_PUBLIC_IP_ENDPOINTS=' .env; then
  printf 'BINANCE_PUBLIC_IP_ENDPOINTS=https://api.ipify.org,https://checkip.amazonaws.com\n' >>.env
fi
chmod 0600 .env

set_env_value "${DASHBOARD_ENV}" AI_RUNTIME_STATUS_FILE \
  /run/mybot/ai_status.json
set_env_value "${DASHBOARD_ENV}" DASHBOARD_FOLLOW_BOT_PATHS 1
set_env_value "${DASHBOARD_ENV}" DASHBOARD_TRUST_PROXY_AUTH 1
if [[ "${MIGRATE_DASHBOARD_RATE_LIMIT}" == "1" ]]; then
  set_env_value "${DASHBOARD_ENV}" DASHBOARD_RATE_LIMIT_PER_MIN 360
fi

dashboard_token="$(
  sed -n 's/^DASHBOARD_AUTH_TOKEN=//p' "${DASHBOARD_ENV}" | head -1
)"
[[ "${dashboard_token}" =~ ^[0-9a-fA-F]{64,}$ ]] \
  || fail "malformed DASHBOARD_AUTH_TOKEN"
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
  install -m 0644 FRONT/index.html FRONT/help.html FRONT/readme.html \
    FRONT/dashboard.css FRONT/dashboard.js FRONT/help.css FRONT/readme.css \
    FRONT/locales.js docs/assets/ladder-dragon-logo.svg \
    docs/assets/ladder-dragon-dashboard-icon.svg CHANGELOG.md "${WEB_ROOT}/"
install -m 0644 FRONT/vendor/chart.umd.min.js "${WEB_ROOT}/vendor/"
install -m 0644 FRONT/vendor/chart.js.LICENSE.txt "${WEB_ROOT}/vendor/"
rm -f "${WEB_ROOT}/readme.html"
.venv/bin/python -m ladder_dragon.verification.dashboard_assets \
  --source-root "${PROJECT_DIR}" --web-root "${WEB_ROOT}" \
  || fail "published dashboard assets do not match the verified release"
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
render_unit deploy/ladder-dragon-user-stream-shadow.service \
  /etc/systemd/system/ladder-dragon-user-stream-shadow.service
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
render_unit deploy/ladder-dragon-depth-retention.service \
  /etc/systemd/system/ladder-dragon-depth-retention.service
install -m 0644 deploy/ladder-dragon-depth-retention.timer \
  /etc/systemd/system/ladder-dragon-depth-retention.timer
render_unit deploy/ladder-dragon-soak-audit.service \
  /etc/systemd/system/ladder-dragon-soak-audit.service
install -m 0644 deploy/ladder-dragon-soak-audit.timer \
  /etc/systemd/system/ladder-dragon-soak-audit.timer
render_unit deploy/ladder-dragon-daily-digest.service \
  /etc/systemd/system/ladder-dragon-daily-digest.service
install -m 0644 deploy/ladder-dragon-daily-digest.timer \
  /etc/systemd/system/ladder-dragon-daily-digest.timer
render_unit deploy/ladder-dragon-monthly-prediction.service \
  /etc/systemd/system/ladder-dragon-monthly-prediction.service
install -m 0644 deploy/ladder-dragon-monthly-prediction.timer \
  /etc/systemd/system/ladder-dragon-monthly-prediction.timer
render_unit deploy/ladder-dragon-market-scenario.service \
  /etc/systemd/system/ladder-dragon-market-scenario.service
install -m 0644 deploy/ladder-dragon-market-scenario.timer \
  /etc/systemd/system/ladder-dragon-market-scenario.timer
render_unit deploy/ladder-dragon-database-retention.service \
  /etc/systemd/system/ladder-dragon-database-retention.service
install -m 0644 deploy/ladder-dragon-database-retention.timer \
  /etc/systemd/system/ladder-dragon-database-retention.timer
install -d -o "${BOT_USER}" -g "${BOT_USER}" -m 0700 \
  /var/lib/ladder-dragon/database-archives \
  /var/lib/ladder-dragon/database-retention \
  /var/lib/ladder-dragon/depth-retention \
  /var/lib/ladder-dragon/market-analysis
install -d -o "${BOT_USER}" -g "${BOT_USER}" -m 0750 \
  /var/lib/ladder-dragon/depth-archives
install -d -o root -g "${BOT_USER}" -m 0770 /var/lib/ladder-dragon/soak

backup_mount_dropin="/etc/systemd/system/ladder-dragon-backup.service.d/external-mount.conf"
depth_retention_dropin="/etc/systemd/system/ladder-dragon-depth-retention.service.d/external-mount.conf"
rm -f "${backup_mount_dropin}"
rm -f "${depth_retention_dropin}"
if [[ -n "${BACKUP_EXTERNAL_MOUNT:-}" ]]; then
  [[ "${BACKUP_EXTERNAL_MOUNT}" =~ ^/[A-Za-z0-9._/@+-]+$ ]] \
    || fail "invalid BACKUP_EXTERNAL_MOUNT path"
  install -d -m 0755 "$(dirname "${backup_mount_dropin}")"
  printf '[Unit]\nRequiresMountsFor=%s\n\n[Service]\nReadWritePaths=%s\n' \
    "${BACKUP_EXTERNAL_MOUNT}" "${BACKUP_EXTERNAL_MOUNT}" \
    >"${backup_mount_dropin}"
  chmod 0644 "${backup_mount_dropin}"
  install -d -m 0755 "$(dirname "${depth_retention_dropin}")"
  printf '[Unit]\nRequiresMountsFor=%s\n\n[Service]\nReadWritePaths=%s\n' \
    "${BACKUP_EXTERNAL_MOUNT}" "${BACKUP_EXTERNAL_MOUNT}" \
    >"${depth_retention_dropin}"
  chmod 0644 "${depth_retention_dropin}"
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
if [[ "${MYBOT_WAS_ACTIVE}" == "1" ]]; then
  .venv/bin/python -m bin.maintenance_state clear >/dev/null
else
  .venv/bin/python -m bin.maintenance_state set \
    --reason "Service was intentionally stopped before release update" \
    >/dev/null || [[ "$?" == "2" ]]
fi
systemctl enable ladder-dragon-backup.timer ladder-dragon-log-export.timer \
  ladder-dragon-depth-archive.service ladder-dragon-soak-audit.timer \
  ladder-dragon-daily-digest.timer ladder-dragon-monthly-prediction.timer \
  ladder-dragon-market-scenario.timer ladder-dragon-database-retention.timer \
  ladder-dragon-depth-retention.timer \
  ladder-dragon-user-stream-shadow.service \
  >/dev/null
start_previous_services
systemctl start ladder-dragon-backup.timer
systemctl start ladder-dragon-backup.service
systemctl start ladder-dragon-log-export.service ladder-dragon-log-export.timer
systemctl disable --now ladder-dragon-depth-archive.timer 2>/dev/null || true
systemctl restart ladder-dragon-depth-archive.service
systemctl start ladder-dragon-soak-audit.service ladder-dragon-soak-audit.timer
systemctl start ladder-dragon-daily-digest.timer
systemctl start ladder-dragon-monthly-prediction.timer
systemctl start ladder-dragon-market-scenario.timer
systemctl start --no-block ladder-dragon-market-scenario.service
systemctl start ladder-dragon-database-retention.timer
systemctl start ladder-dragon-depth-retention.timer
systemctl restart ladder-dragon-user-stream-shadow.service
systemctl is-active --quiet ladder-dragon-user-stream-shadow.service \
  || fail "read-only User Data Stream shadow service failed"
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
  publish_verified_deployment_status
else
  echo "[OK] preserved service state: mybot_active=${MYBOT_WAS_ACTIVE} dashboard_active=${DASHBOARD_WAS_ACTIVE}"
fi
SERVICES_STOPPED=0
trap - ERR INT TERM
