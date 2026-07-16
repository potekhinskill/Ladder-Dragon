#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/bot/apps/binance_bot}"
BACKUP_DIR="${BACKUP_DIR:-/var/lib/ladder-dragon/backups}"
STAMP="$(date -u +%Y-%m-%d-%H%M%S)"
DEST="${BACKUP_DIR}/${STAMP}"

[[ "${EUID}" -eq 0 ]] || exec sudo "$0" "$@"
install -d -m 0700 "${DEST}"

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
  echo "root_disk=$(df -h / | awk 'NR==2{print $2\",\"$3\",\"$5}')"
} >"${DEST}/inventory.txt"

ss -lntup >"${DEST}/network-listeners.txt" 2>/dev/null || true
systemctl list-unit-files --state=enabled >"${DEST}/enabled-units.txt" 2>/dev/null || true

install -d -m 0700 "${DEST}/rootfs" "${DEST}/project"
for path in \
  /etc/systemd/system/mybot.service \
  /etc/systemd/system/mybot.service.d \
  /etc/systemd/system/pi-healthd.service \
  /etc/systemd/system/ladder-dragon-log-export.service \
  /etc/systemd/system/ladder-dragon-log-export.timer \
  /etc/nginx/sites-available \
  /etc/nginx/snippets/pi_api.conf \
  /etc/nginx/.htpasswd-ladder-dragon \
  /etc/systemd/journald.conf.d/ladder-dragon.conf \
  /etc/fail2ban/jail.d/sshd.local \
  /etc/default/zramswap; do
  [[ -e "${path}" ]] && cp -a --parents "${path}" "${DEST}/rootfs/"
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

tar -C "${BACKUP_DIR}" -czf "${BACKUP_DIR}/ladder-dragon-${STAMP}.tgz" "${STAMP}"
sha256sum "${BACKUP_DIR}/ladder-dragon-${STAMP}.tgz" \
  >"${BACKUP_DIR}/ladder-dragon-${STAMP}.sha256"
chmod 0600 "${BACKUP_DIR}/ladder-dragon-${STAMP}".*
rm -rf "${DEST}"

# 14 ежедневных архивов; месячные/внешние копии должны делаться отдельно.
find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'ladder-dragon-*' -mtime +14 -delete
echo "${BACKUP_DIR}/ladder-dragon-${STAMP}.tgz"
