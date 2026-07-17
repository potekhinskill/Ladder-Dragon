#!/usr/bin/env bash
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.
set -euo pipefail

# Жёстко привязываемся к директории скрипта: относительные пути стабильны
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# -----------------------------
# Выбор интерпретатора Python
# -----------------------------
PY="${PYTHON:-python3}"
# Если активирован venv — используем его python
if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python3" ]]; then
  PY="${VIRTUAL_ENV}/bin/python3"
fi
# Если рядом с проектом есть .venv — используем его python
if [[ -x ".venv/bin/python3" ]]; then
  PY=".venv/bin/python3"
fi
# Проверим, что python доступен
command -v "${PY}" >/dev/null 2>&1 || { echo "Python not found: ${PY}"; exit 127; }

SUP="ai_supervisor.py"
RUNNER="ai_plan_runner.py"
PNL="pnl_reporter.py"
# systemd ProtectSystem=strict оставляет для записи только db/, logs/ и /run/mybot.
# Поэтому служебные логи не должны лежать в корне checkout: ExecStop иначе
# завершится с status=1 даже при успешной остановке дочерних процессов.
LOG="${SUPERVISOR_LOG:-${SCRIPT_DIR}/logs/supervisor.log}"
PNL_LOG="${PNL_LOG_PATH:-${SCRIPT_DIR}/logs/pnl.log}"
LOCK="/tmp/ai_supervisor.lock"

mkdir -p "$(dirname -- "${LOG}")" "$(dirname -- "${PNL_LOG}")"

# -----------------------------
# Нормализация значений .env
# -----------------------------
sanitize_env_var() {
  local name="$1"
  local val="${!name-}"
  # убрать CR/LF
  val="${val//$'\r'/}"
  val="${val//$'\n'/}"
  # обрезать пробелы по краям
  val="${val#"${val%%[![:space:]]*}"}"
  val="${val%"${val##*[![:space:]]}"}"
  # снять парные кавычки
  [[ "${val}" == \"*\" ]] && val="${val#\"}" && val="${val%\"}"
  [[ "${val}" == \'*\' ]] && val="${val#\'}" && val="${val%\'}"
  printf -v "$name" '%s' "$val"
  export "$name"
}

# -----------------------------
# Автоподхват из .env (если есть)
# -----------------------------
if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
  # нормализуем ключевые переменные
  sanitize_env_var "BINANCE_API_KEY"
  sanitize_env_var "BINANCE_API_SECRET"
  sanitize_env_var "BINANCE_API_BASE"
  # безопасная диагностика (без утечки секретов)
  {
    _k="${BINANCE_API_KEY-}"; _s="${BINANCE_API_SECRET-}"; _b="${BINANCE_API_BASE-}"
    echo "[env-check] key_len=${#_k} sec_len=${#_s} base=${_b:-<unset>}"
    unset _k _s _b
  } >> "${LOG}"
fi

usage() {
  cat <<'USAGE'
Usage: ./supervisor_ctl.sh <command> [args...]

Commands (supervisor):
  start [args...] Запустить ai_supervisor.py (nohup, лог в supervisor.log)
  status          Показать процессы, lock и хвост supervisor.log
  logs            tail -f supervisor.log
  stop-old        Остановить САМЫЙ РАННИЙ ai_supervisor.py (+чистка lock при совпадении PID)
  stop-new        Остановить САМЫЙ ПОЗДНИЙ ai_supervisor.py
  stop-all        Остановить ВСЕ ai_supervisor.py и удалить lock

Runner helper:
  start-runner -- <args> Запустить ai_plan_runner.py (после -- передаётся всё как есть)

PnL reporter:
  pnl -- <args>    Запустить pnl_reporter.py в фоне (лог в pnl.log)
                   Пример:
                     ./supervisor_ctl.sh pnl -- --symbols SOLUSDT,ETHUSDT --days 30 --quote USDT
  pnl-logs         tail -f pnl.log
  pnl-status       Показать активные процессы pnl_reporter.py
  pnl-stop         Остановить все pnl_reporter.py

Подсказка: типовой запуск supervisor (DRY-RUN):
  ./supervisor_ctl.sh start \
    --singleton \
    --symbols SOLUSDT,ETHUSDT,BNBUSDT \
    --ladder-mode pct \
    --ladder-pct "SOLUSDT=-3,-6,-10,-15;ETHUSDT=-2.5,-5.5,-9;BNBUSDT=-3,-6.5,-11" \
    --rolling-ladder --ppbs-guard --auto-oco-holdings \
    --atr-window 14 --atr-interval 1h \
    --tp1-min 0.05 --tp1-max 0.35 --sl-max 0.18 \
    --max-oco-per-symbol 5 --only-new-fills \
    --child-loop-minutes 3 --interval-seconds 60 \
    --oco-fallback prefer-tp1

Реальные заявки: добавь --live
  ./supervisor_ctl.sh start ... --live
USAGE
}

# Более точные pgrep-шаблоны, чтобы не ловить лишнее
pids_sup() { pgrep -fl "[/ ]${SUP}" || true; }
pids_pnl() { pgrep -fl "[/ ]${PNL}" || true; }

print_lock_status() {
  if [[ -f "${LOCK}" ]]; then
    local lpid alive
    lpid="$(cat "${LOCK}" 2>/dev/null || true)"
    alive="stale?"
    if [[ -n "${lpid}" ]]; then
      if [[ -d "/proc/${lpid}" ]]; then
        alive="alive"
      elif ps -p "${lpid}" >/dev/null 2>&1; then
        alive="alive"
      fi
    fi
    echo "[status] lock найден: ${LOCK} -> ${lpid} (${alive})"
  else
    echo "[status] lock ${LOCK} отсутствует"
  fi
}

# Унифицированный лог с timestamp
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "${LOG}"
}

# Лёгкая ротация логов (по 5 МБ)
rotate_log_if_big() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  local size
  size=$(wc -c <"$f" || echo 0)
  if (( size > 5242880 )); then
    mv -f "$f" "${f}.1" || true
    : > "$f"
    echo "[log-rotate] rotated ${f}" >> "$f"
  fi
}

# Проверка BNB-баланса без зависимости от bc; учитываем BINANCE_API_BASE; не блокируем запуск при сетевой ошибке
check_bnb() {
  if [[ -n "${USE_BNB_FOR_FEES-}" && "${USE_BNB_FOR_FEES}" = "1" ]]; then
    rotate_log_if_big "${LOG}"
    log "Checking BNB balance for fees..."
    BNB_BALANCE="$("${PY}" - <<'EOF'
import os, time, hmac, hashlib, urllib.parse
try:
    import requests
except Exception:
    print("NA"); raise SystemExit

API_KEY = os.getenv('BINANCE_API_KEY','')
API_SECRET = os.getenv('BINANCE_API_SECRET','')
BASE = os.getenv('BINANCE_API_BASE','https://api.binance.com').rstrip('/')

def signed_get(path, params=None):
    if params is None: params = {}
    params['timestamp'] = int(time.time() * 1000)
    params['recvWindow'] = 5000
    query = urllib.parse.urlencode(params)
    signature = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    q = f"{query}&signature={signature}"
    headers = {'X-MBX-APIKEY': API_KEY}
    r = requests.get(f"{BASE}{path}?{q}", headers=headers, timeout=10)
    r.raise_for_status()
    return r.json()

try:
    acct = signed_get('/api/v3/account')
    bnb = next((float(b['free']) for b in acct.get('balances',[]) if b.get('asset')=='BNB'), 0.0)
    print(bnb)
except Exception:
    print("NA")
EOF
)"
    if [[ "${BNB_BALANCE}" == "NA" ]]; then
      log "WARN: Could not verify BNB balance (network/requests missing). Continuing."
    else
      case "${BNB_BALANCE}" in
        ''|*[!0-9.]*)
          log "WARN: Unexpected BNB balance '${BNB_BALANCE}', continuing."
          ;;
        *)
          # порог 0.1 BNB
          awk -v v="${BNB_BALANCE}" 'BEGIN{ if (v+0 < 0.1) exit 1 }' \
            || { log "ERROR: Low BNB balance (${BNB_BALANCE}) for fees. Aborting start."; exit 1; }
          log "BNB balance OK: ${BNB_BALANCE}"
          ;;
      esac
    fi
  fi
}

cmd_start() {
  rotate_log_if_big "${LOG}"
  check_bnb
  log "Starting supervisor..."
  echo "./supervisor_ctl.sh logs # живой хвост"
  echo "[start] nohup ${PY} -u ${SUP} $@ </dev/null >> ${LOG} 2>&1 & disown"
  nohup "${PY}" -u "${SUP}" "$@" </dev/null >> "${LOG}" 2>&1 & disown
  sleep 0.4
  local npid
  npid="$(pgrep -n -f "[/ ]${SUP}" || true)"
  if [[ -n "${npid}" ]]; then
    if [[ -f "${LOCK}" ]]; then
      echo "[start] pid=${npid}, lock=${LOCK}"
    else
      echo "[start] pid=${npid}"
    fi
    ps -o pid,etime,command -p "${npid}" | sed '1 s/^/ /'
  else
    echo "[start] предупреждение: PID не найден (возможно, процесс сразу завершился — см. логи)"
  fi
}

cmd_status() {
  echo "./supervisor_ctl.sh logs # живой хвост"
  echo "[status] процессы ${SUP}:"
  if pgrep -fl "[/ ]${SUP}" >/dev/null 2>&1; then
    ps -o pid,etime,command -p $(pgrep -f "[/ ]${SUP}" | tr '\n' ' ') | sed '1 s/^/ /'
  else
    echo "  нет"
  fi
  print_lock_status
  echo "[status] tail ${LOG}:"
  tail -n 60 "${LOG}" || true
}

cmd_logs() {
  # Если увидел "zsh: suspended ./supervisor_ctl.sh logs" — это Ctrl+Z.
  # Верни в передний план: 'fg', либо открой новую вкладку и сделай:
  # tail -f supervisor.log
  tail -f "${LOG}"
}

cmd_stop_old() {
  local pid
  pid=$(pgrep -o -f "[/ ]${SUP}" || true)
  if [[ -z "${pid}" ]]; then
    echo "[stop-old] нет запущенных ${SUP}"
    return 0
  fi
  echo "[stop-old] kill -TERM ${pid}"
  kill -TERM "${pid}" || true
  sleep 2
  if [[ -f "${LOCK}" ]] && [[ "$(cat "${LOCK}" 2>/dev/null || true)" == "${pid}" ]]; then
    rm -f "${LOCK}" && echo "[stop-old] lock очищен (${LOCK})"
  fi
}

cmd_stop_new() {
  local pid
  pid=$(pgrep -n -f "[/ ]${SUP}" || true)
  if [[ -z "${pid}" ]]; then
    echo "[stop-new] нет запущенных ${SUP}"
    return 0
  fi
  echo "[stop-new] kill -TERM ${pid}"
  kill -TERM "${pid}" || true
}

cmd_stop_all() {
  local p
  p=$(pgrep -f "[/ ]${SUP}" || true)
  if [[ -z "${p}" ]]; then
    echo "[stop-all] нет запущенных ${SUP}"
  else
    echo "[stop-all] kill -TERM ${p}"
    kill -TERM ${p} || true
    sleep 2
  fi
  rm -f "${LOCK}" && echo "[stop-all] lock удалён (${LOCK})" || true
}

cmd_start_runner() {
  if [[ "${1:-}" != "--" ]]; then
    echo "[start-runner] usage: ./supervisor_ctl.sh start-runner -- <args для ai_plan_runner.py>"
    exit 2
  fi
  shift
  rotate_log_if_big "${LOG}"
  echo "[start-runner] nohup ${PY} -u ${RUNNER} --base-script autosize_universal.py -- $@ >> ${LOG} 2>&1 & disown"
  nohup "${PY}" -u "${RUNNER}" --base-script autosize_universal.py -- "$@" >> "${LOG}" 2>&1 & disown
}

# ---------- PnL reporter ----------
cmd_pnl() {
  if [[ "${1:-}" == "--" ]]; then shift; fi
  rotate_log_if_big "${PNL_LOG}"
  echo "[pnl] nohup ${PY} -u ${PNL} $@ >> ${PNL_LOG} 2>&1 & disown"
  nohup "${PY}" -u "${PNL}" "$@" >> "${PNL_LOG}" 2>&1 & disown
  sleep 0.3
  pids_pnl | tail -1 || true
}

cmd_pnl_logs() {
  tail -f "${PNL_LOG}"
}

cmd_pnl_status() {
  echo "[pnl-status] процессы ${PNL}:"
  if pgrep -fl "[/ ]${PNL}" >/dev/null 2>&1; then
    ps -o pid,etime,command -p $(pgrep -f "[/ ]${PNL}" | tr '\n' ' ') | sed '1 s/^/ /'
  else
    echo "[pnl-status] ${PNL} не запущен"
  fi
  echo "[pnl-status] tail ${PNL_LOG}:"
  tail -n 40 "${PNL_LOG}" || true
}

cmd_pnl_stop() {
  local p
  p=$(pgrep -f "[/ ]${PNL}" || true)
  if [[ -z "${p}" ]]; then
    echo "[pnl-stop] нет запущенных ${PNL}"
    return 0
  fi
  echo "[pnl-stop] kill -TERM ${p}"
  kill -TERM ${p} || true
}

# ---------- main ----------
cmd="${1:-}"
shift || true
case "${cmd}" in
  start)        cmd_start "$@" ;;
  status)       cmd_status ;;
  logs)         cmd_logs ;;
  stop-old)     cmd_stop_old ;;
  stop-new)     cmd_stop_new ;;
  stop-all)     cmd_stop_all ;;
  start-runner) cmd_start_runner "$@" ;;
  pnl)          cmd_pnl "$@" ;;
  pnl-logs)     cmd_pnl_logs ;;
  pnl-status)   cmd_pnl_status ;;
  pnl-stop)     cmd_pnl_stop ;;
  ""|help|-h|--help) usage ;;
  *) echo "Unknown command: ${cmd}"; usage; exit 2 ;;
esac
