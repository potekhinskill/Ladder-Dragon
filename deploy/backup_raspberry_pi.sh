#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/bot/apps/binance_bot}"
BACKUP_DIR="${BACKUP_DIR:-/var/lib/ladder-dragon/backups}"
PUBLIC_BACKUP_DIR="${PUBLIC_BACKUP_DIR:-/var/lib/ladder-dragon/backups-public}"
BACKUP_AGE_RECIPIENT="${BACKUP_AGE_RECIPIENT:-}"
STAMP="$(date -u +%Y-%m-%d-%H%M%S)"
DEST="${BACKUP_DIR}/${STAMP}"

[[ "${EUID}" -eq 0 ]] || exec sudo "$0" "$@"
command -v age >/dev/null || {
  echo "[FAIL] age is required for encrypted backups" >&2
  exit 1
}
[[ "${BACKUP_AGE_RECIPIENT}" == age1* ]] || {
  echo "[FAIL] BACKUP_AGE_RECIPIENT is missing or invalid" >&2
  exit 1
}
install -d -m 0700 "${DEST}"
install -d -o root -g www-data -m 0750 "${PUBLIC_BACKUP_DIR}"

# Инвентарь не содержит значений секретных переменных.
{
  echo "created_at=${STAMP}"
  echo "hostname=$(hostname)"
  echo "architecture=$(dpkg --print-architecture 2>/dev/null || uname -m)"
  echo "os=$(sed -n 's/^PRETTY_NAME=//p' /etc/os-release | tr -d '\"')"
  echo "kernel=$(uname -r)"
  echo "project_dir=${PROJECT_DIR}"
  echo "git_commit=$(git -C "${PROJECT_DIR}" rev-parse HEAD 2>/dev/null || true)"
  echo "mybot_enabled=$(systemctl is-enabled mybot 2>/dev/null || true)"
  echo "mybot_active=$(systemctl is-active mybot 2>/dev/null || true)"
  echo "dashboard_enabled=$(systemctl is-enabled pi-healthd 2>/dev/null || true)"
  echo "dashboard_active=$(systemctl is-active pi-healthd 2>/dev/null || true)"
  echo "memory=$(free -h | awk '/^Mem:/{print $2}')"
  echo "root_disk=$(df -h / | awk 'NR==2 {print $2 "," $3 "," $5}')"
} >"${DEST}/inventory.txt"

ss -lntup >"${DEST}/network-listeners.txt" 2>/dev/null || true
systemctl list-unit-files --state=enabled >"${DEST}/enabled-units.txt" 2>/dev/null || true

install -d -m 0700 "${DEST}/rootfs" "${DEST}/project"
copy_rootfs_path() {
  local source="$1"
  local relative="${source#/}"
  local target="${DEST}/rootfs/${relative}"
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
  /etc/systemd/system/mybot.service.d \
  /etc/systemd/system/pi-healthd.service \
  /etc/systemd/system/ladder-dragon-log-export.service \
  /etc/systemd/system/ladder-dragon-log-export.timer \
	  /etc/nginx/sites-available \
	  /etc/nginx/snippets/pi_api.conf \
	  /etc/nginx/snippets/ladder_dragon_proxy_secret.conf \
  /etc/nginx/.htpasswd-ladder-dragon \
  /etc/systemd/journald.conf.d/ladder-dragon.conf \
  /etc/fail2ban/jail.d/sshd.local \
  /etc/default/zramswap; do
  [[ -e "${path}" ]] && copy_rootfs_path "${path}"
done

# Старый watchdog и его Telegram-конфигурация сохраняются только внутри
# зашифрованного age-архива. Они никогда не попадают в HTTP-каталог.
for path in \
  /etc/bot-alerts.env \
  /etc/ladder-dragon/telegram.env \
  /etc/systemd/system/pi-watchdog-v3.service \
  /etc/systemd/system/pi-watchdog-v3.timer \
  /etc/systemd/system/pi-watchdog-v3.service.d \
  /etc/logrotate.d/pi-watchdog \
  /usr/local/bin/pi-watchdog_v3.sh \
  /var/log/pi-watchdog.log; do
  [[ -e "${path}" ]] && copy_rootfs_path "${path}"
done

for name in .env .env.service .env.dashboard; do
  [[ -f "${PROJECT_DIR}/${name}" ]] \
    && install -m 0600 "${PROJECT_DIR}/${name}" "${DEST}/project/${name}"
done

# SQLite снимается через online backup API, без копирования несогласованных WAL/SHM.
python3 - "${PROJECT_DIR}" "${DEST}/project" <<'PY'
import os
import sqlite3
import sys
from pathlib import Path

project = Path(sys.argv[1])
dest = Path(sys.argv[2])
for source in sorted((project / "db").glob("*.db")) + sorted((project / "db").glob("*.sqlite3")):
    target = dest / source.name
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src:
        with sqlite3.connect(target) as out:
            src.backup(out)
    os.chmod(target, 0o600)
PY

# Архив никогда не записывается на диск открытым: tar сразу передаётся в age.
tar -C "${BACKUP_DIR}" -czf - "${STAMP}" \
  | age -r "${BACKUP_AGE_RECIPIENT}" \
      -o "${BACKUP_DIR}/ladder-dragon-${STAMP}.tgz.age"
sha256sum "${BACKUP_DIR}/ladder-dragon-${STAMP}.tgz.age" \
  >"${BACKUP_DIR}/ladder-dragon-${STAMP}.tgz.age.sha256"
chmod 0600 "${BACKUP_DIR}/ladder-dragon-${STAMP}.tgz.age"*

# Веб-каталог содержит только зашифрованный архив, checksum и безопасный
# inventory без env/ключей. Сырые backup-каталоги остаются root-only.
install -o root -g www-data -m 0640 \
  "${BACKUP_DIR}/ladder-dragon-${STAMP}.tgz.age" \
  "${PUBLIC_BACKUP_DIR}/ladder-dragon-${STAMP}.tgz.age"
install -o root -g www-data -m 0640 \
  "${BACKUP_DIR}/ladder-dragon-${STAMP}.tgz.age.sha256" \
  "${PUBLIC_BACKUP_DIR}/ladder-dragon-${STAMP}.tgz.age.sha256"
install -o root -g www-data -m 0640 \
  "${DEST}/inventory.txt" \
  "${PUBLIC_BACKUP_DIR}/inventory-${STAMP}.txt"
manifest_tmp="$(mktemp "${PUBLIC_BACKUP_DIR}/.index.XXXXXX")"
{
  echo "Ladder Dragon encrypted backups"
  echo "Generated: ${STAMP} UTC"
  echo "Archives are age-encrypted; inventory files contain no secrets."
  find "${PUBLIC_BACKUP_DIR}" -maxdepth 1 -type f \
    \( -name '*.tgz.age' -o -name '*.tgz.age.sha256' -o -name 'inventory-*.txt' \) \
    -printf '%f\n' | sort
} >"${manifest_tmp}"
install -o root -g www-data -m 0640 "${manifest_tmp}" "${PUBLIC_BACKUP_DIR}/index.txt"
rm -f "${manifest_tmp}"
rm -rf "${DEST}"

# 14 ежедневных архивов; месячные/внешние копии должны делаться отдельно.
find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'ladder-dragon-*.tgz.age*' -mtime +14 -delete
find "${PUBLIC_BACKUP_DIR}" -maxdepth 1 -type f \
  \( -name 'ladder-dragon-*.tgz.age*' -o -name 'inventory-*.txt' \) \
  -mtime +14 -delete
echo "${BACKUP_DIR}/ladder-dragon-${STAMP}.tgz.age"
