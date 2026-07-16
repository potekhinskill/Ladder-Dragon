#!/usr/bin/env bash
set -euo pipefail

ACTION="install"
PROJECT_DIR="${PROJECT_DIR:-/home/bot/apps/binance_bot}"
REPO_URL="${REPO_URL:-https://github.com/potekhinskill/binance_bot.git}"
BRANCH="${BRANCH:-codex/safety-hardening}"
COMMIT="${COMMIT:-}"
BOT_HOSTNAME="${BOT_HOSTNAME:-bot.local}"
BOT_USER="${BOT_USER:-bot}"
PRESERVE_LIVE=0
SKIP_APT=0

usage() {
  cat <<'EOF'
Usage:
  sudo bash deploy/install_raspberry_pi.sh [install|migrate|audit] [options]

Options:
  --project-dir PATH       Canonical checkout (default /home/bot/apps/binance_bot)
  --repo-url URL           Git repository used for a fresh checkout
  --branch NAME            Git branch (default codex/safety-hardening)
  --commit SHA             Required exact 40-character Git commit allowlist
  --hostname NAME.local    Dashboard hostname (default bot.local)
  --preserve-live          Preserve detected Mainnet LIVE only with BOT_LIVE_CONFIRMED=YES
  --skip-apt               Do not install Debian packages

Fresh installs are Testnet DRY. Migration also becomes DRY unless --preserve-live
is supplied and the existing secret env contains BOT_LIVE_CONFIRMED=YES.
EOF
}

while (($#)); do
  case "$1" in
    install|migrate|audit) ACTION="$1"; shift ;;
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    --repo-url) REPO_URL="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --commit) COMMIT="$2"; shift 2 ;;
    --hostname) BOT_HOSTNAME="$2"; shift 2 ;;
    --preserve-live) PRESERVE_LIVE=1; shift ;;
    --skip-apt) SKIP_APT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

if [[ "${EUID}" -ne 0 ]]; then
  fail "run this installer with sudo"
fi
[[ "${BOT_HOSTNAME}" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || fail "invalid hostname"
if [[ "${ACTION}" != "audit" ]]; then
  [[ "${COMMIT}" =~ ^[0-9a-fA-F]{40}$ ]] \
    || fail "--commit with an exact 40-character Git SHA is required"
fi
command -v systemctl >/dev/null || fail "systemd is required"
[[ -r /etc/os-release ]] || fail "Linux distribution information is missing"
. /etc/os-release
[[ "${ID:-}" == "debian" || "${ID:-}" == "raspbian" ]] \
  || fail "Raspberry Pi OS/Debian is required, detected ${ID:-unknown}"

legacy_unit=0
legacy_live=0
legacy_mainnet=0
if [[ -f /etc/systemd/system/mybot.service ]]; then
  grep -qE '1\\.8_autosize|--risk-level|--copy-top-bots|key_start_bot' \
    /etc/systemd/system/mybot.service && legacy_unit=1 || true
  grep -q -- '--live' /etc/systemd/system/mybot.service && legacy_live=1 || true
  grep -q -- '--testnet' /etc/systemd/system/mybot.service || legacy_mainnet=1
fi

audit() {
  echo "os=${PRETTY_NAME:-unknown}"
  echo "arch=$(dpkg --print-architecture 2>/dev/null || uname -m)"
  echo "project_dir=${PROJECT_DIR}"
  echo "project_present=$([[ -d "${PROJECT_DIR}/.git" ]] && echo yes || echo no)"
  echo "legacy_unit=$([[ "${legacy_unit}" == 1 ]] && echo yes || echo no)"
  echo "mybot_active=$(systemctl is-active mybot 2>/dev/null || true)"
  echo "mybot_enabled=$(systemctl is-enabled mybot 2>/dev/null || true)"
  echo "dashboard_active=$(systemctl is-active pi-healthd 2>/dev/null || true)"
  echo "dashboard_enabled=$(systemctl is-enabled pi-healthd 2>/dev/null || true)"
  echo "nginx_config=$(nginx -t >/dev/null 2>&1 && echo valid || echo unavailable)"
  echo "public_backups=$([[ -d /var/www/bot/backups ]] && echo present || echo absent)"
  echo "api_port_public=$(
    ss -ltn 2>/dev/null | grep -qE '(^|[[:space:]])(0\\.0\\.0\\.0|\\[::\\]):8081' \
      && echo yes || echo no
  )"
}

if [[ "${ACTION}" == "audit" ]]; then
  audit
  exit 0
fi

if [[ "${ACTION}" == "install" && -e /etc/systemd/system/mybot.service ]]; then
  fail "existing mybot.service detected; use migrate"
fi

if [[ "${SKIP_APT}" != 1 ]]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    ca-certificates curl git nginx apache2-utils avahi-daemon openssl \
    age fail2ban python3 python3-pip python3-venv sqlite3 zram-tools
fi

if ! id "${BOT_USER}" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "${BOT_USER}"
fi
BOT_HOME="$(getent passwd "${BOT_USER}" | cut -d: -f6)"
[[ -n "${BOT_HOME}" ]] || fail "cannot determine home for ${BOT_USER}"

install -d -o "${BOT_USER}" -g "${BOT_USER}" -m 0750 "$(dirname "${PROJECT_DIR}")"
install -d -m 0700 /var/lib/ladder-dragon/backups
install -d -o root -g www-data -m 0750 /var/lib/ladder-dragon/logs
hostnamectl set-hostname "${BOT_HOSTNAME%.local}"

setup_backup_encryption() {
  local config_dir="/etc/ladder-dragon"
  local identity_dir="/root/.config/ladder-dragon"
  local identity="${identity_dir}/backup-age.key"
  local recipient
  command -v age >/dev/null || fail "age is required"
  command -v age-keygen >/dev/null || fail "age-keygen is required"
  install -d -m 0700 "${config_dir}" "${identity_dir}"
  if [[ ! -s "${identity}" ]]; then
    age-keygen -o "${identity}" >/dev/null
    chmod 0600 "${identity}"
  fi
  recipient="$(age-keygen -y "${identity}")"
  [[ "${recipient}" == age1* ]] || fail "cannot derive backup age recipient"
  install -m 0600 /dev/null "${config_dir}/backup.env"
  printf 'BACKUP_AGE_RECIPIENT=%s\n' "${recipient}" \
    >"${config_dir}/backup.env"
  export BACKUP_AGE_RECIPIENT="${recipient}"
}

setup_backup_encryption

# Временная миграционная копия переживает замену legacy-каталога на Git checkout.
migration_staging="$(mktemp -d /tmp/ladder-dragon-migration.XXXXXX)"
trap 'rm -rf "${migration_staging}"' EXIT
for name in .env .env.dashboard; do
  [[ -f "${PROJECT_DIR}/${name}" ]] \
    && install -m 0600 "${PROJECT_DIR}/${name}" "${migration_staging}/${name}"
done
[[ -f /etc/systemd/system/mybot.service ]] \
  && cp /etc/systemd/system/mybot.service "${migration_staging}/legacy-mybot.service"
[[ -f /etc/systemd/system/pi-healthd.service ]] \
  && cp /etc/systemd/system/pi-healthd.service "${migration_staging}/legacy-pi-healthd.service"
[[ -f /etc/nginx/sites-available/bot.local ]] \
  && cp /etc/nginx/sites-available/bot.local "${migration_staging}/legacy-nginx.conf"
install -d -m 0700 "${migration_staging}/sqlite"
python3 - "${PROJECT_DIR}" "${migration_staging}/sqlite" <<'PY'
import os
import sqlite3
import sys
from pathlib import Path

source_dir = Path(sys.argv[1]) / "db"
target_dir = Path(sys.argv[2])
if source_dir.is_dir():
    for source in sorted(source_dir.glob("*.db")) + sorted(source_dir.glob("*.sqlite3")):
        target = target_dir / source.name
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src:
            with sqlite3.connect(target) as out:
                src.backup(out)
        os.chmod(target, 0o600)
PY

# До первой мутации сохраняем systemd/nginx/env/SQLite в закрытом каталоге.
if [[ -x "${PROJECT_DIR}/deploy/backup_raspberry_pi.sh" ]]; then
  PROJECT_DIR="${PROJECT_DIR}" "${PROJECT_DIR}/deploy/backup_raspberry_pi.sh"
else
  stamp="$(date -u +%Y-%m-%d-%H%M%S)"
  staging="$(mktemp -d /tmp/ladder-dragon-preinstall.XXXXXX)"
  copy_rootfs_path() {
    local source="$1"
    local relative="${source#/}"
    local target="${staging}/${relative}"
    if [[ -d "${source}" ]]; then
      install -d "${target}"
      cp -a "${source}/." "${target}/"
    else
      install -d "$(dirname "${target}")"
      cp -a "${source}" "${target}"
    fi
  }
  for path in \
    /etc/systemd/system/mybot.service \
    /etc/systemd/system/pi-healthd.service \
    /etc/nginx/sites-available/bot.local \
    /etc/nginx/snippets/pi_api.conf \
    /etc/nginx/snippets/ladder_dragon_proxy_secret.conf \
    "${PROJECT_DIR}/.env" \
    "${PROJECT_DIR}/.env.dashboard"; do
    [[ -e "${path}" ]] && copy_rootfs_path "${path}"
  done
  install -d -m 0700 "${staging}/sqlite"
  python3 - "${PROJECT_DIR}" "${staging}/sqlite" <<'PY'
import os
import sqlite3
import sys
from pathlib import Path

source_dir = Path(sys.argv[1]) / "db"
target_dir = Path(sys.argv[2])
if source_dir.is_dir():
    for source in sorted(source_dir.glob("*.db")) + sorted(source_dir.glob("*.sqlite3")):
        target = target_dir / source.name
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src:
            with sqlite3.connect(target) as out:
                src.backup(out)
        os.chmod(target, 0o600)
PY
  emergency="/var/lib/ladder-dragon/backups/preinstall-${stamp}.tgz.age"
  tar -C "${staging}" -czf - . \
    | age -r "${BACKUP_AGE_RECIPIENT}" -o "${emergency}"
  chmod 0600 "${emergency}"
  rm -rf "${staging}"
fi

mybot_was_active="$(systemctl is-active mybot 2>/dev/null || true)"
dashboard_was_active="$(systemctl is-active pi-healthd 2>/dev/null || true)"
legacy_project=""
prepared_checkout=""

# Legacy-код заменяется только уже успешно скачанным checkout.
if [[ "${legacy_unit}" == 1 ]]; then
  prepared_checkout="$(dirname "${PROJECT_DIR}")/.ladder-dragon-new-$$"
  rm -rf "${prepared_checkout}"
  runuser -u "${BOT_USER}" -- git clone --branch "${BRANCH}" --single-branch \
    "${REPO_URL}" "${prepared_checkout}"
  runuser -u "${BOT_USER}" -- git -C "${prepared_checkout}" cat-file -e "${COMMIT}^{commit}"
  runuser -u "${BOT_USER}" -- git -C "${prepared_checkout}" merge-base --is-ancestor \
    "${COMMIT}" "origin/${BRANCH}"
  runuser -u "${BOT_USER}" -- git -C "${prepared_checkout}" switch -C "${BRANCH}" "${COMMIT}"
fi

rollback_install() {
  local status=$?
  trap - ERR INT TERM
  echo "[ROLLBACK] installation failed; restoring previous service and project" >&2
  systemctl stop mybot pi-healthd 2>/dev/null || true
  if [[ -n "${legacy_project}" && -d "${legacy_project}" ]]; then
    rm -rf "${PROJECT_DIR}.failed"
    [[ -e "${PROJECT_DIR}" ]] && mv "${PROJECT_DIR}" "${PROJECT_DIR}.failed"
    mv "${legacy_project}" "${PROJECT_DIR}"
  fi
  [[ -f "${migration_staging}/legacy-mybot.service" ]] \
    && cp "${migration_staging}/legacy-mybot.service" /etc/systemd/system/mybot.service
  [[ -f "${migration_staging}/legacy-pi-healthd.service" ]] \
    && cp "${migration_staging}/legacy-pi-healthd.service" /etc/systemd/system/pi-healthd.service
  [[ -f "${migration_staging}/legacy-nginx.conf" ]] \
    && cp "${migration_staging}/legacy-nginx.conf" /etc/nginx/sites-available/bot.local
  systemctl daemon-reload
  [[ "${mybot_was_active}" == "active" ]] && systemctl start mybot 2>/dev/null || true
  [[ "${dashboard_was_active}" == "active" ]] && systemctl start pi-healthd 2>/dev/null || true
  systemctl reload nginx 2>/dev/null || true
  exit "${status}"
}

trap rollback_install ERR INT TERM
systemctl stop mybot pi-healthd 2>/dev/null || true

if [[ -n "${prepared_checkout}" ]]; then
  legacy_project="$(dirname "${PROJECT_DIR}")/.binance_bot.legacy-$(date -u +%Y%m%d%H%M%S)"
  [[ -e "${PROJECT_DIR}" ]] && mv "${PROJECT_DIR}" "${legacy_project}"
  mv "${prepared_checkout}" "${PROJECT_DIR}"
  chown -R "${BOT_USER}:${BOT_USER}" "${PROJECT_DIR}"
elif [[ ! -d "${PROJECT_DIR}/.git" ]]; then
  runuser -u "${BOT_USER}" -- git clone --branch "${BRANCH}" --single-branch \
    "${REPO_URL}" "${PROJECT_DIR}"
  runuser -u "${BOT_USER}" -- git -C "${PROJECT_DIR}" cat-file -e "${COMMIT}^{commit}"
  runuser -u "${BOT_USER}" -- git -C "${PROJECT_DIR}" merge-base --is-ancestor \
    "${COMMIT}" "origin/${BRANCH}"
  runuser -u "${BOT_USER}" -- git -C "${PROJECT_DIR}" switch -C "${BRANCH}" "${COMMIT}"
else
  [[ -z "$(runuser -u "${BOT_USER}" -- git -C "${PROJECT_DIR}" status --porcelain --untracked-files=no)" ]] \
    || fail "tracked project files have local changes"
  runuser -u "${BOT_USER}" -- git -C "${PROJECT_DIR}" fetch origin "${BRANCH}"
  runuser -u "${BOT_USER}" -- git -C "${PROJECT_DIR}" cat-file -e "${COMMIT}^{commit}"
  runuser -u "${BOT_USER}" -- git -C "${PROJECT_DIR}" merge-base --is-ancestor \
    HEAD "${COMMIT}"
  runuser -u "${BOT_USER}" -- git -C "${PROJECT_DIR}" merge --ff-only "${COMMIT}"
fi

if [[ ! -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
  runuser -u "${BOT_USER}" -- python3 -m venv "${PROJECT_DIR}/.venv"
fi
runuser -u "${BOT_USER}" -- "${PROJECT_DIR}/.venv/bin/python" -m pip install -e "${PROJECT_DIR}[dashboard]"

# Новый шаблон получает прежние значения env и полезные Environment= из legacy
# unit. Значения не печатаются и не передаются через argv.
python3 - "${PROJECT_DIR}" "${migration_staging}" <<'PY'
import re
import shlex
import sys
from pathlib import Path

project = Path(sys.argv[1])
staging = Path(sys.argv[2])
name_re = re.compile(r"^[A-Z][A-Z0-9_]*$")
plain_value_re = re.compile(r"^[A-Za-z0-9_./,:;@%+?=-]*$")
locked = {
    "BOT_RUN_DIR", "BOT_TESTNET_RUN_DIR",
    "BOT_STATS_DB", "BOT_TESTNET_STATS_DB",
    "BOT_ORDER_JOURNAL", "BOT_TESTNET_ORDER_JOURNAL",
    "AI_USAGE_LOG", "AI_DECISIONS_DB", "AI_TESTNET_DECISIONS_DB",
    "AI_RUNTIME_STATUS_FILE",
    "CB_HALT_FILE", "CB_STATE_FILE", "CB_ALERTS_FILE",
}

def parse_env(path: Path) -> dict[str, str]:
    values = {}
    if not path.is_file():
        return values
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name_re.fullmatch(name.strip()):
            try:
                parsed = shlex.split(value, comments=False, posix=True)
                values[name.strip()] = parsed[0] if len(parsed) == 1 else value
            except ValueError:
                values[name.strip()] = value
    return values

def format_value(value: str) -> str:
    if plain_value_re.fullmatch(value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

def merge(template: Path, old: Path, target: Path, unit: Path | None = None) -> None:
    values = parse_env(old)
    if unit and unit.is_file():
        for raw in unit.read_text(errors="replace").splitlines():
            line = raw.strip()
            if not line.startswith("Environment="):
                continue
            try:
                entries = shlex.split(line[len("Environment="):])
            except ValueError:
                continue
            for entry in entries:
                if "=" not in entry:
                    continue
                name, value = entry.split("=", 1)
                if name_re.fullmatch(name):
                    values[name] = value
    for name in locked:
        values.pop(name, None)
    output = []
    seen = set()
    for raw in template.read_text().splitlines():
        if "=" in raw and not raw.lstrip().startswith("#"):
            name = raw.split("=", 1)[0].strip()
            if name_re.fullmatch(name):
                seen.add(name)
                if name in values:
                    raw = f"{name}={format_value(values[name])}"
        output.append(raw)
    for name in sorted(values.keys() - seen):
        output.append(f"{name}={format_value(values[name])}")
    target.write_text("\n".join(output) + "\n")

merge(
    project / ".env.example",
    staging / ".env",
    project / ".env",
    staging / "legacy-mybot.service",
)
merge(
    project / ".env.dashboard.example",
    staging / ".env.dashboard",
    project / ".env.dashboard",
)
for target in (project / ".env", project / ".env.dashboard"):
    target.write_text(
        target.read_text().replace("/home/bot/apps/binance_bot", str(project))
    )
PY

install -d -o "${BOT_USER}" -g "${BOT_USER}" -m 0700 "${PROJECT_DIR}/db"
for database in "${migration_staging}/sqlite/"*; do
  [[ -f "${database}" ]] || continue
  install -o "${BOT_USER}" -g "${BOT_USER}" -m 0600 \
    "${database}" "${PROJECT_DIR}/db/$(basename "${database}")"
done

service_venue="testnet"
service_execution="dry"
if [[ "${ACTION}" == "migrate" && "${legacy_mainnet}" == 1 ]]; then
  service_venue="mainnet"
fi
if [[ "${ACTION}" == "migrate" && "${legacy_live}" == 1 && "${PRESERVE_LIVE}" == 1 ]]; then
  grep -q '^BOT_LIVE_CONFIRMED=YES$' "${PROJECT_DIR}/.env" \
    || fail "--preserve-live requires BOT_LIVE_CONFIRMED=YES in .env"
  service_execution="live"
fi

if [[ ! -f "${PROJECT_DIR}/.env.service" ]]; then
  install -o root -g "${BOT_USER}" -m 0640 \
    "${PROJECT_DIR}/.env.service.example" "${PROJECT_DIR}/.env.service"
fi
sed -i \
  -e "s/^BOT_SERVICE_VENUE=.*/BOT_SERVICE_VENUE=${service_venue}/" \
  -e "s/^BOT_SERVICE_EXECUTION=.*/BOT_SERVICE_EXECUTION=${service_execution}/" \
  "${PROJECT_DIR}/.env.service"

# Dashboard никогда не получает торговый env. Proxy-auth включается отдельно.
sed -i \
  -e 's/^DASHBOARD_TRUST_PROXY_AUTH=.*/DASHBOARD_TRUST_PROXY_AUTH=1/' \
  -e 's/^DASHBOARD_FOLLOW_BOT_PATHS=.*/DASHBOARD_FOLLOW_BOT_PATHS=1/' \
  -e 's/^DASHBOARD_BINANCE_API_KEY=.*/DASHBOARD_BINANCE_API_KEY=/' \
  -e 's/^DASHBOARD_BINANCE_API_SECRET=.*/DASHBOARD_BINANCE_API_SECRET=/' \
  "${PROJECT_DIR}/.env.dashboard"

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

dashboard_token="$(openssl rand -hex 32)"
dashboard_proxy_secret="$(openssl rand -hex 32)"
set_env_value "${PROJECT_DIR}/.env.dashboard" DASHBOARD_AUTH_TOKEN "${dashboard_token}"
set_env_value "${PROJECT_DIR}/.env.dashboard" DASHBOARD_PROXY_AUTH_SECRET "${dashboard_proxy_secret}"
chown "${BOT_USER}:${BOT_USER}" "${PROJECT_DIR}/.env" "${PROJECT_DIR}/.env.dashboard"
chmod 0600 "${PROJECT_DIR}/.env" "${PROJECT_DIR}/.env.dashboard"
chmod 0755 "${PROJECT_DIR}/deploy/"*.sh

install -d -o "${BOT_USER}" -g "${BOT_USER}" -m 0700 \
  "${PROJECT_DIR}/db" "${PROJECT_DIR}/logs" "${PROJECT_DIR}/FastAPI/pi-dashboard/data"
install -d -m 0755 /var/www/bot /etc/nginx/certs /etc/nginx/snippets
install -o root -g www-data -m 0640 /dev/null \
  /etc/nginx/snippets/ladder_dragon_proxy_secret.conf
printf 'proxy_set_header X-Dashboard-Proxy-Secret "%s";\n' \
  "${dashboard_proxy_secret}" \
  >/etc/nginx/snippets/ladder_dragon_proxy_secret.conf
install -m 0644 "${PROJECT_DIR}/FRONT/index.html" "${PROJECT_DIR}/FRONT/help.html" \
  "${PROJECT_DIR}/CHANGELOG.md" /var/www/bot/
rm -f /var/www/bot/readme.html

if [[ -d /var/www/bot/backups ]]; then
  legacy_dest="/var/lib/ladder-dragon/backups/legacy-public-$(date -u +%Y%m%d%H%M%S)"
  mv /var/www/bot/backups "${legacy_dest}"
  chmod -R go-rwx "${legacy_dest}"
fi

if [[ -n "${DASHBOARD_PASSWORD:-}" ]]; then
  dashboard_password="${DASHBOARD_PASSWORD}"
elif [[ -f /root/ladder-dragon-dashboard-credentials.txt ]]; then
  dashboard_password="$(
    sed -n 's/^PASSWORD=//p' /root/ladder-dragon-dashboard-credentials.txt | head -1
  )"
else
  dashboard_password="$(openssl rand -base64 24 | tr -d '/+=')"
fi
[[ -n "${dashboard_password}" ]] || fail "dashboard password is empty"
htpasswd -bc /etc/nginx/.htpasswd-ladder-dragon dashboard "${dashboard_password}" >/dev/null
chmod 0640 /etc/nginx/.htpasswd-ladder-dragon
chown root:www-data /etc/nginx/.htpasswd-ladder-dragon
install -m 0600 /dev/null /root/ladder-dragon-dashboard-credentials.txt
printf 'URL=https://%s/\\nUSER=dashboard\\nPASSWORD=%s\\n' \
  "${BOT_HOSTNAME}" "${dashboard_password}" \
  >/root/ladder-dragon-dashboard-credentials.txt

cert="/etc/nginx/certs/${BOT_HOSTNAME}.pem"
key="/etc/nginx/certs/${BOT_HOSTNAME}-key.pem"
if [[ ! -s "${cert}" || ! -s "${key}" ]]; then
  openssl req -x509 -newkey rsa:3072 -nodes -days 825 \
    -subj "/CN=${BOT_HOSTNAME}" \
    -addext "subjectAltName=DNS:${BOT_HOSTNAME}" \
    -keyout "${key}" -out "${cert}" >/dev/null 2>&1
  chmod 0600 "${key}"
fi

sed "s/__BOT_HOSTNAME__/${BOT_HOSTNAME}/g" \
  "${PROJECT_DIR}/deploy/nginx/bot.local.conf" \
  >/etc/nginx/sites-available/bot.local
install -m 0644 "${PROJECT_DIR}/deploy/nginx/pi_api.conf" /etc/nginx/snippets/pi_api.conf
ln -sfn /etc/nginx/sites-available/bot.local /etc/nginx/sites-enabled/bot.local
rm -f /etc/nginx/sites-enabled/default

install -d -m 0755 /etc/systemd/journald.conf.d /etc/fail2ban/jail.d
install -m 0644 "${PROJECT_DIR}/deploy/system/journald-ladder-dragon.conf" \
  /etc/systemd/journald.conf.d/ladder-dragon.conf
install -m 0644 "${PROJECT_DIR}/deploy/system/fail2ban-sshd.local" \
  /etc/fail2ban/jail.d/sshd.local
install -m 0644 "${PROJECT_DIR}/deploy/system/zramswap" /etc/default/zramswap

render_unit() {
  sed \
    -e "s#/home/bot/apps/binance_bot#${PROJECT_DIR}#g" \
    -e "s/^User=bot$/User=${BOT_USER}/" \
    -e "s/^Group=bot$/Group=${BOT_USER}/" \
    "$1" >"$2"
  chmod 0644 "$2"
}
render_unit "${PROJECT_DIR}/deploy/mybot.service" /etc/systemd/system/mybot.service
render_unit "${PROJECT_DIR}/deploy/pi-dashboard.service" /etc/systemd/system/pi-healthd.service
render_unit "${PROJECT_DIR}/deploy/ladder-dragon-backup.service" \
  /etc/systemd/system/ladder-dragon-backup.service
install -m 0644 "${PROJECT_DIR}/deploy/ladder-dragon-backup.timer" \
  /etc/systemd/system/ladder-dragon-backup.timer
render_unit "${PROJECT_DIR}/deploy/ladder-dragon-log-export.service" \
  /etc/systemd/system/ladder-dragon-log-export.service
install -m 0644 "${PROJECT_DIR}/deploy/ladder-dragon-log-export.timer" \
  /etc/systemd/system/ladder-dragon-log-export.timer

runuser -u "${BOT_USER}" -- "${PROJECT_DIR}/.venv/bin/python" -m compileall -q "${PROJECT_DIR}"
runuser -u "${BOT_USER}" -- "${PROJECT_DIR}/.venv/bin/python" \
  "${PROJECT_DIR}/deploy/validate_security_config.py" "${PROJECT_DIR}"
runuser -u "${BOT_USER}" -- "${PROJECT_DIR}/.venv/bin/python" "${PROJECT_DIR}/ai_supervisor.py" --version
nginx -t

systemctl daemon-reload
systemctl disable --now make-pi-backup.timer make-pi-backup.service 2>/dev/null || true
systemctl enable nginx avahi-daemon fail2ban mybot pi-healthd \
  ladder-dragon-backup.timer ladder-dragon-log-export.timer >/dev/null
systemctl restart systemd-journald nginx avahi-daemon fail2ban
systemctl restart zramswap 2>/dev/null || true
systemctl start mybot pi-healthd ladder-dragon-backup.timer
systemctl start ladder-dragon-log-export.service ladder-dragon-log-export.timer

sleep 3
systemctl is-active --quiet nginx || fail "nginx failed"
systemctl is-active --quiet mybot || fail "mybot failed"
systemctl is-active --quiet pi-healthd || fail "pi-healthd failed"
test -r /var/lib/ladder-dragon/logs/current.log || fail "log export failed"
grep -q '^DASHBOARD_AUTH_TOKEN=replace_' "${PROJECT_DIR}/.env.dashboard" \
  && fail "placeholder dashboard token remains"
curl --fail --silent --show-error -u "dashboard:${dashboard_password}" \
  --resolve "${BOT_HOSTNAME}:443:127.0.0.1" --insecure \
  "https://${BOT_HOSTNAME}/api/health" >/dev/null
anonymous_logs_status="$(
  curl --insecure --silent --output /dev/null --write-out '%{http_code}' \
    --resolve "${BOT_HOSTNAME}:443:127.0.0.1" \
    "https://${BOT_HOSTNAME}/logs/"
)"
[[ "${anonymous_logs_status}" == "401" ]] \
  || fail "expected protected logs HTTP 401, got ${anonymous_logs_status}"

if [[ -d /opt/pi-dashboard ]]; then
  install -d -m 0700 /var/lib/ladder-dragon/legacy
  mv /opt/pi-dashboard \
    "/var/lib/ladder-dragon/legacy/pi-dashboard-$(date -u +%Y%m%d%H%M%S)"
fi

echo "[OK] Ladder Dragon installation is ready"
echo "mode=${service_venue}/${service_execution}"
echo "credentials=/root/ladder-dragon-dashboard-credentials.txt"
echo "backup_dir=/var/lib/ladder-dragon/backups"
if [[ "${legacy_live}" == 1 && "${service_execution}" != "live" ]]; then
  echo "[SAFE] legacy LIVE was migrated as DRY; validate and explicitly enable LIVE"
fi
trap - ERR INT TERM
