#!/usr/bin/env bash
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.
set -euo pipefail

# Мягкий watchdog: проверяет сеть и heartbeat, но не трогает здоровый mybot.
STRIKES=${STRIKES:-3}
MIN_UPTIME=${MIN_UPTIME:-10}
HEARTBEAT_MAX_AGE_SEC=${HEARTBEAT_MAX_AGE_SEC:-420}
HOST_LABEL="${HOST_LABEL:-binance_bot:}"
LOG="${WATCHDOG_LOG:-/var/log/pi-watchdog.log}"
STATE="${WATCHDOG_STATE:-/run/pi-watchdog_v3.state}"
STATEDIR="${WATCHDOG_STATE_DIR:-/var/lib/pi-watchdog}"
ALERT_STATE="${WATCHDOG_ALERT_STATE:-${STATEDIR}/telegram-alert.state}"
ALERT_COOLDOWN_SEC=${WATCHDOG_ALERT_COOLDOWN_SEC:-1800}
ALERT_LOAD_THRESHOLD=${WATCHDOG_ALERT_LOAD_THRESHOLD:-2.0}
ALERT_TEMP_THRESHOLD_C=${WATCHDOG_ALERT_TEMP_THRESHOLD_C:-70}
ALERT_LOAD_DELTA=${WATCHDOG_ALERT_LOAD_DELTA:-0.5}
ALERT_TEMP_DELTA_C=${WATCHDOG_ALERT_TEMP_DELTA_C:-2}
TELEGRAM_OUTBOX="${WATCHDOG_TELEGRAM_OUTBOX:-${STATEDIR}/telegram-outbox}"
TELEGRAM_OUTBOX_MAX_FLUSH=${WATCHDOG_TELEGRAM_OUTBOX_MAX_FLUSH:-10}
REASON_FILE="${STATEDIR}/reason.txt"
HEARTBEAT="${AI_RUNTIME_STATUS_FILE:-/run/mybot/ai_status.json}"
UPTIME_SOURCE="${WATCHDOG_UPTIME_SOURCE:-/proc/uptime}"

[ -f /etc/bot-alerts.env ] && . /etc/bot-alerts.env || true

mkdir -p "${STATEDIR}"
touch "${LOG}" 2>/dev/null || true
log() { printf '%s %s\n' "$1" "$2" >>"${LOG}"; }

# Отправка вынесена в отдельную функцию, чтобы при отсутствии сети сохранить
# текст сообщения локально и не потерять причину аварии.
telegram_post() {
  local msg="$1"
  curl -sS -m 5 "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TG_CHAT_ID}" \
    --data-urlencode "text=${msg}" >/dev/null
}

queue_telegram_message() {
  local msg="$1" digest tmp target
  mkdir -p "${TELEGRAM_OUTBOX}"
  digest="$(printf '%s' "${msg}" | sha256sum | awk '{print $1}')"
  target="${TELEGRAM_OUTBOX}/$(date +%s)-$$-${digest}.msg"
  tmp="${target}.tmp"
  printf '%s\n' "${msg}" >"${tmp}"
  mv -f "${tmp}" "${target}"
  log "[telegram]" "queued undelivered alert ${target}"
}

flush_telegram_outbox() {
  local count path queued sent=0
  [[ -n "${TG_BOT_TOKEN:-}" && -n "${TG_CHAT_ID:-}" ]] || return 0
  [[ -d "${TELEGRAM_OUTBOX}" ]] || return 0
  count="$(find "${TELEGRAM_OUTBOX}" -maxdepth 1 -type f -name '*.msg' | wc -l | tr -d ' ')"
  (( count > 0 )) || return 0
  telegram_post "✅ Telegram connection restored
Отложенных уведомлений: ${count}" || return 1
  while IFS= read -r path; do
    queued="$(cat "${path}")"
    telegram_post "📨 Отложенное уведомление:
${queued}" || return 1
    rm -f -- "${path}"
    sent=$((sent + 1))
    if (( sent >= TELEGRAM_OUTBOX_MAX_FLUSH )); then
      break
    fi
  done < <(find "${TELEGRAM_OUTBOX}" -maxdepth 1 -type f -name '*.msg' -print | sort)
  log "[telegram]" "flushed ${sent}/${count} queued alerts"
}

# Разрешаем первое уведомление, изменение показателей или повтор после cooldown.
# Состояние хранится отдельно от heartbeat, поэтому одинаковая авария не спамит
# Telegram каждые пять минут, но важный рост нагрузки/температуры не теряется.
alert_gate() {
  local key="$1" load_key="$2" temp="$3" now old_key old_sent old_repeat old_load old_temp
  local repeat=0 should_send=0 full_snapshot=0 changed=0 high=0 state_load state_temp
  now="$(date +%s)"
  old_key=""; old_sent=0; old_repeat=0; old_load=""; old_temp=""
  if [[ -r "${ALERT_STATE}" ]]; then
    read -r old_key old_sent old_repeat old_load old_temp <"${ALERT_STATE}" || true
    [[ "${old_sent:-}" =~ ^[0-9]+$ ]] || old_sent=0
    [[ "${old_repeat:-}" =~ ^[0-9]+$ ]] || old_repeat=0
  fi

  if [[ "${old_key}" != "${key}" ]]; then
    should_send=1
    full_snapshot=1
  else
    repeat=$((old_repeat + 1))
    if awk -v old="${old_load//,/ }" -v new="${load_key//,/ }" \
      -v delta="${ALERT_LOAD_DELTA}" \
      'BEGIN { split(old, a, " "); split(new, b, " "); exit !((b[1] - a[1] >= delta) || (a[1] - b[1] >= delta)) }' ||
      awk -v old="${old_temp:-unknown}" -v new="${temp:-unknown}" \
      -v delta="${ALERT_TEMP_DELTA_C}" \
      'BEGIN { if (old == "unknown" || new == "unknown") exit 1; exit !(((new + 0) - (old + 0) >= delta) || ((old + 0) - (new + 0) >= delta)) }'; then
      changed=1
    fi
    if (( now - old_sent >= ALERT_COOLDOWN_SEC )); then
      should_send=1
      full_snapshot=1
    fi
    if awk -v value="${load_key//,/ }" -v limit="${ALERT_LOAD_THRESHOLD}" \
      'BEGIN { split(value, a, " "); exit !((a[1] + 0) >= limit) }' ||
      awk -v value="${temp:-0}" -v limit="${ALERT_TEMP_THRESHOLD_C}" \
      'BEGIN { exit !((value + 0) >= limit) }'; then
      high=1
    fi
    if (( changed || high )); then
      should_send=1
      full_snapshot=1
    fi
  fi

  state_load="${old_load}"
  state_temp="${old_temp}"
  if (( should_send )); then
    old_sent="${now}"
    state_load="${load_key}"
    state_temp="${temp}"
  fi
  mkdir -p "$(dirname "${ALERT_STATE}")"
  local tmp="${ALERT_STATE}.tmp.$$"
  printf '%s %s %s %s %s\n' "${key}" "${old_sent}" "${repeat}" "${state_load}" "${state_temp}" >"${tmp}"
  mv -f "${tmp}" "${ALERT_STATE}"
  printf '%s %s %s\n' "${should_send}" "${full_snapshot}" "${repeat}"
}

send_tg() {
  local txt="${1:-}"
  local event_key="${2:-${txt}}"
  [ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ] || return 0
  local uptime_human load ip temp msg host_label load_key gate should_send full_snapshot repeat
  uptime_human="$(uptime -p 2>/dev/null || true)"
  load="$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || true)"
  # В Telegram нужен только основной адрес; Docker-сети не помогают диагностике.
  ip="$(ip -4 -o addr show scope global 2>/dev/null | awk 'NR == 1 {print $4}')"
  temp="$([ -x /usr/bin/vcgencmd ] && /usr/bin/vcgencmd measure_temp 2>/dev/null | tr -cd 0-9. || true)"
  load_key="${load// /,}"
  gate="$(alert_gate "$(printf '%s' "${event_key}" | sha256sum | awk '{print $1}')" "${load_key}" "${temp:-unknown}")"
  read -r should_send full_snapshot repeat <<<"${gate}"
  (( should_send )) || return 0
  host_label="${HOST_LABEL%:}"
  if (( full_snapshot )); then
    msg="${host_label} ${txt}
время: $(date '+%Y-%m-%d %H:%M:%S %Z')
uptime: ${uptime_human}
load: ${load:-unknown}
temp: ${temp:-unknown}°C
ip: ${ip:-unknown}"
  else
    msg="${host_label} ${txt}
повтор: ${repeat}; показатели без изменений"
  fi
  if ! telegram_post "${msg}"; then
    queue_telegram_message "${msg}"
  fi
}

echo "=== $(LC_ALL=C date) [v3] ===" >>"${LOG}"
read -r up <"${UPTIME_SOURCE}"
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
network_reason="ok"
gw_ip="$(ip r | awk '/^default/ {print $3; exit}')"
: "${gw_ip:=192.168.8.1}"
gw_rc=0; ping -4 -c1 -W1 "${gw_ip}" >/dev/null 2>&1 || gw_rc=$?
dns_rc=0; ping -4 -c1 -W2 1.1.1.1 >/dev/null 2>&1 || dns_rc=$?
api_rc=0; curl --ipv4 --connect-timeout 2 -m 3 -sS \
  https://api.binance.com/api/v3/ping >/dev/null || api_rc=$?
reason="ok"
if (( gw_rc != 0 || dns_rc != 0 || api_rc != 0 )); then
  net_fails=$((prev_net + 1))
  network_reason="network gw=${gw_rc} dns=${dns_rc} api=${api_rc}"
  printf '%s\n' "${network_reason}" >"${REASON_FILE}"
else
  [[ -f "${REASON_FILE}" ]] && rm -f "${REASON_FILE}"
  if (( prev_net > 0 )); then
    flush_telegram_outbox || true
    send_tg "✅ network recovered; gateway, DNS and Binance API are reachable" \
      "network-recovered"
  fi
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
    send_tg "✅ mybot heartbeat recovered" "heartbeat-recovered"
  fi
fi

# Один краткий сбой не должен убивать торговый контур. Перезапуск только после
# STRIKES последовательных плохих heartbeat-проверок.
if (( health_fails >= STRIKES )); then
  send_tg "⚠️ mybot unhealthy: ${reason}; restarting after ${health_fails} strikes" \
    "mybot-health:${reason}"
  systemctl restart mybot.service || true
  systemctl is-active --quiet mybot.service && \
    send_tg "🔁 mybot restarted (service active; heartbeat проверяется следующим циклом)" \
      "mybot-restarted"
  health_fails=0
fi

if (( net_fails >= STRIKES )); then
  send_tg "⚠️ network failure: ${network_reason} (fails=${net_fails})" \
    "network:${network_reason}"
  logger "[WATCHDOG] network failure: ${network_reason}"
fi

printf '%s %s\n' "${net_fails}" "${health_fails}" >"${STATE}"
exit 0
