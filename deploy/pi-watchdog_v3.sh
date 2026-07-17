#!/usr/bin/env bash
set -euo pipefail

# Мягкий watchdog: проверяет сеть и heartbeat, но не трогает здоровый mybot.
STRIKES=${STRIKES:-3}
MIN_UPTIME=${MIN_UPTIME:-10}
HEARTBEAT_MAX_AGE_SEC=${HEARTBEAT_MAX_AGE_SEC:-420}
HOST_LABEL="${HOST_LABEL:-binance_bot:}"
LOG="${WATCHDOG_LOG:-/var/log/pi-watchdog.log}"
STATE="${WATCHDOG_STATE:-/run/pi-watchdog_v3.state}"
STATEDIR="${WATCHDOG_STATE_DIR:-/var/lib/pi-watchdog}"
REASON_FILE="${STATEDIR}/reason.txt"
HEARTBEAT="${AI_RUNTIME_STATUS_FILE:-/run/mybot/ai_status.json}"

[ -f /etc/bot-alerts.env ] && . /etc/bot-alerts.env || true

mkdir -p "${STATEDIR}"
touch "${LOG}" 2>/dev/null || true
log() { printf '%s %s\n' "$1" "$2" >>"${LOG}"; }

send_tg() {
  local txt="${1:-}"
  [ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ] || return 0
  local uptime_human load ip temp msg
  uptime_human="$(uptime -p 2>/dev/null || true)"
  load="$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || true)"
  ip="$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | paste -sd',' -)"
  temp="$([ -x /usr/bin/vcgencmd ] && /usr/bin/vcgencmd measure_temp 2>/dev/null | tr -cd 0-9. || true)"
  msg="${HOST_LABEL} ${txt}
uptime: ${uptime_human}
load: ${load}
ip: ${ip}
temp: ${temp}"
  curl -sS -m 5 "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TG_CHAT_ID}" -d "parse_mode=HTML" \
    --data-urlencode "text=${msg}" >/dev/null || true
}

echo "=== $(LC_ALL=C date) [v3] ===" >>"${LOG}"
read -r up </proc/uptime
uptime_min=$(( ${up%%.*} / 60 ))
if (( uptime_min < MIN_UPTIME )); then
  log "[v3]" "grace: ${uptime_min}m < ${MIN_UPTIME}m"
  printf '0 0\n' >"${STATE}"
  exit 0
fi

prev_net=0
prev_health=0
if [[ -f "${STATE}" ]]; then
  read -r prev_net prev_health <"${STATE}" || true
  [[ "${prev_net:-}" =~ ^[0-9]+$ ]] || prev_net=0
  [[ "${prev_health:-}" =~ ^[0-9]+$ ]] || prev_health=0
fi

net_fails=0
gw_ip="$(ip r | awk '/^default/ {print $3; exit}')"
: "${gw_ip:=192.168.8.1}"
gw_rc=0; ping -4 -c1 -W1 "${gw_ip}" >/dev/null 2>&1 || gw_rc=$?
dns_rc=0; ping -4 -c1 -W2 1.1.1.1 >/dev/null 2>&1 || dns_rc=$?
api_rc=0; curl --ipv4 --connect-timeout 2 -m 3 -sS \
  https://api.binance.com/api/v3/ping >/dev/null || api_rc=$?
reason="ok"
if (( gw_rc != 0 || dns_rc != 0 || api_rc != 0 )); then
  net_fails=$((prev_net + 1))
  reason="network gw=${gw_rc} dns=${dns_rc} api=${api_rc}"
  printf '%s\n' "${reason}" >"${REASON_FILE}"
else
  [[ -f "${REASON_FILE}" ]] && rm -f "${REASON_FILE}"
fi

health_ok=1
if ! systemctl is-active --quiet mybot.service; then
  health_ok=0
  reason="mybot inactive"
fi
if [[ "${health_ok}" == 1 && ! -r "${HEARTBEAT}" ]]; then
  health_ok=0
  reason="heartbeat missing"
fi
if [[ "${health_ok}" == 1 ]]; then
  heartbeat_ok="$(python3 - "${HEARTBEAT}" "${HEARTBEAT_MAX_AGE_SEC}" <<'PY'
import json
import sys
from datetime import datetime, timezone

try:
    payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
    updated = datetime.fromisoformat(str(payload["updated_at"]))
    age = (datetime.now(timezone.utc) - updated).total_seconds()
    ok = payload.get("state") == "RUNNING" and 0 <= age <= float(sys.argv[2])
except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
    ok = False
print("1" if ok else "0")
PY
)"
  if [[ "${heartbeat_ok}" != 1 ]]; then
    health_ok=0
    reason="heartbeat stale or not RUNNING"
  fi
fi

if (( health_ok == 0 )); then
  health_fails=$((prev_health + 1))
  log "[v3]" "health fail #${health_fails}: ${reason}"
else
  health_fails=0
  if (( prev_health > 0 )); then
    send_tg "✅ ${HOST_LABEL} mybot heartbeat recovered"
  fi
fi

# Один краткий сбой не должен убивать торговый контур. Перезапуск только после
# STRIKES последовательных плохих heartbeat-проверок.
if (( health_fails >= STRIKES )); then
  send_tg "⚠️ ${HOST_LABEL} mybot unhealthy: ${reason}; restarting after ${health_fails} strikes"
  systemctl restart mybot.service || true
  systemctl is-active --quiet mybot.service && \
    send_tg "🔁 ${HOST_LABEL} mybot restarted (OK)"
  health_fails=0
fi

if (( net_fails >= STRIKES )); then
  send_tg "⚠️ ${HOST_LABEL} network failure: ${reason} (fails=${net_fails})"
  logger "[WATCHDOG] network failure: ${reason}"
fi

printf '%s %s\n' "${net_fails}" "${health_fails}" >"${STATE}"
exit 0
