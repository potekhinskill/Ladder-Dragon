#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/bot/apps/binance_bot}"
BACKUP_DIR="${BACKUP_DIR:-/var/lib/ladder-dragon/backups}"
PUBLIC_BACKUP_DIR="${PUBLIC_BACKUP_DIR:-/var/lib/ladder-dragon/backups-public}"
BACKUP_AGE_RECIPIENT="${BACKUP_AGE_RECIPIENT:-}"
BACKUP_EXTERNAL_MOUNT="${BACKUP_EXTERNAL_MOUNT:-}"
BACKUP_EXTERNAL_DIR="${BACKUP_EXTERNAL_DIR:-}"
BACKUP_EXTERNAL_RETENTION_DAYS="${BACKUP_EXTERNAL_RETENTION_DAYS:-90}"
STAMP="$(date -u +%Y-%m-%d-%H%M%S)"
DEST="${BACKUP_DIR}/${STAMP}"

# В DEST временно находятся расшифрованные env/SQLite. Удаляем staging даже
# при ошибке внешнего mirror, чтобы аварийный backup не оставил секреты на SD.
cleanup_staging() {
  rm -rf -- "${DEST}"
}
trap cleanup_staging EXIT

[[ "${EUID}" -eq 0 ]] || exec sudo "$0" "$@"
command -v age >/dev/null || {
  echo "[FAIL] age is required for encrypted backups" >&2
  exit 1
}
[[ "${BACKUP_AGE_RECIPIENT}" == age1* ]] || {
  echo "[FAIL] BACKUP_AGE_RECIPIENT is missing or invalid" >&2
  exit 1
}
if [[ -n "${BACKUP_EXTERNAL_MOUNT}" || -n "${BACKUP_EXTERNAL_DIR}" ]]; then
  [[ "${BACKUP_EXTERNAL_RETENTION_DAYS}" =~ ^[0-9]+$ ]] || {
    echo "[FAIL] BACKUP_EXTERNAL_RETENTION_DAYS must be a non-negative integer" >&2
    exit 1
  }
  [[ -n "${BACKUP_EXTERNAL_MOUNT}" && -n "${BACKUP_EXTERNAL_DIR}" ]] || {
    echo "[FAIL] BACKUP_EXTERNAL_MOUNT and BACKUP_EXTERNAL_DIR must be set together" >&2
    exit 1
  }
  case "${BACKUP_EXTERNAL_DIR}" in
    "${BACKUP_EXTERNAL_MOUNT}"/*) ;;
    *)
      echo "[FAIL] BACKUP_EXTERNAL_DIR must be below BACKUP_EXTERNAL_MOUNT" >&2
      exit 1
      ;;
  esac
  mounted_at="$(findmnt -T "${BACKUP_EXTERNAL_MOUNT}" -no TARGET 2>/dev/null || true)"
  [[ "${mounted_at}" == "${BACKUP_EXTERNAL_MOUNT}" ]] || {
    echo "[FAIL] external backup disk is not mounted at ${BACKUP_EXTERNAL_MOUNT}" >&2
    exit 1
  }
  mount_options="$(findmnt -T "${BACKUP_EXTERNAL_MOUNT}" -no OPTIONS 2>/dev/null || true)"
  case ",${mount_options}," in
    *,ro,*)
      echo "[FAIL] external backup disk is mounted read-only at ${BACKUP_EXTERNAL_MOUNT}" >&2
      exit 1
      ;;
  esac
  # exFAT не поддерживает chmod; права внешнего каталога задаются mount-опциями.
  mkdir -p "${BACKUP_EXTERNAL_DIR}"
fi
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
import time
from pathlib import Path

project = Path(sys.argv[1])
dest = Path(sys.argv[2])
for source in sorted((project / "db").glob("*.db")) + sorted((project / "db").glob("*.sqlite3")):
    target = dest / source.name
    # На активной SQLite WAL короткая гонка закрытия/записи может временно
    # вернуть «unable to open database file». Повторяем online backup, но после
    # исчерпания попыток завершаем backup с ошибкой, не публикуя неполный архив.
    for attempt in range(3):
        try:
            with sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30) as src:
                with sqlite3.connect(target, timeout=30) as out:
                    src.backup(out, pages=100, sleep=0.2)
            break
        except sqlite3.OperationalError:
            if attempt == 2:
                raise
            time.sleep(1)
    os.chmod(target, 0o600)
PY

# Архив никогда не записывается на диск открытым: tar сразу передаётся в age.
tar -C "${BACKUP_DIR}" -czf - "${STAMP}" \
  | age -r "${BACKUP_AGE_RECIPIENT}" \
      -o "${BACKUP_DIR}/ladder-dragon-${STAMP}.tgz.age"

# Храним checksum с относительным именем. Такой файл можно проверить и на
# SD-карте, и на внешнем диске, и после скачивания из /backups/.
archive_name="ladder-dragon-${STAMP}.tgz.age"
(cd "${BACKUP_DIR}" && sha256sum "${archive_name}" >"${archive_name}.sha256")
chmod 0600 "${BACKUP_DIR}/${archive_name}" "${BACKUP_DIR}/${archive_name}.sha256"

# До публикации удаляем только просроченные локальные копии, затем
# синхронизируем весь оставшийся набор, а не только последний архив. Это
# автоматически восстанавливает исторические файлы после миграции.
find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'ladder-dragon-*.tgz.age*' \
  -mtime +14 -delete

mirror_external_archive() {
  local source_archive="$1"
  local name
  name="$(basename "${source_archive}")"
  # --preserve=timestamps не пытается менять владельца exFAT-файла.
  cp --preserve=timestamps -f "${source_archive}" "${BACKUP_EXTERNAL_DIR}/${name}"
  # checksum пересоздаётся в каталоге назначения, поэтому путь остаётся
  # переносимым и не содержит локальных путей Raspberry Pi.
  (cd "${BACKUP_EXTERNAL_DIR}" && sha256sum "${name}" >"${name}.sha256")
  (cd "${BACKUP_EXTERNAL_DIR}" && sha256sum -c "${name}.sha256" >/dev/null)
}

publish_public_archive() {
  local source_archive="$1"
  local name
  name="$(basename "${source_archive}")"
  cp --preserve=timestamps -f "${source_archive}" "${PUBLIC_BACKUP_DIR}/${name}"
  chown root:www-data "${PUBLIC_BACKUP_DIR}/${name}"
  chmod 0640 "${PUBLIC_BACKUP_DIR}/${name}"
  (cd "${PUBLIC_BACKUP_DIR}" && sha256sum "${name}" >"${name}.sha256")
  chown root:www-data "${PUBLIC_BACKUP_DIR}/${name}.sha256"
  chmod 0640 "${PUBLIC_BACKUP_DIR}/${name}.sha256"
  (cd "${PUBLIC_BACKUP_DIR}" && sha256sum -c "${name}.sha256" >/dev/null)
}

shopt -s nullglob
for source_archive in "${BACKUP_DIR}"/*.tgz.age; do
  [[ -f "${source_archive}" ]] || continue
  if [[ -n "${BACKUP_EXTERNAL_DIR}" ]]; then
    # Внешний диск получает все age-архивы, включая preinstall-снимки.
    mirror_external_archive "${source_archive}"
  fi
  # В HTTP-каталог попадают только регулярные ladder-dragon-архивы.
  # preinstall остаётся внешней/локальной копией и не публикуется.
  if [[ "$(basename "${source_archive}")" == ladder-dragon-*.tgz.age ]]; then
    publish_public_archive "${source_archive}"
  fi
done
shopt -u nullglob

if [[ -n "${BACKUP_EXTERNAL_DIR}" ]]; then
  # Внешний диск также получает inventory без секретов. При отключённом
  # mountpoint скрипт завершается выше и не пишет незаметно на SD-карту.
  cp --preserve=timestamps -f "${DEST}/inventory.txt" \
    "${BACKUP_EXTERNAL_DIR}/inventory-${STAMP}.txt"
  find "${BACKUP_EXTERNAL_DIR}" -maxdepth 1 -type f \
    \( -name 'ladder-dragon-*.tgz.age*' -o -name 'preinstall-*.tgz.age*' -o -name 'inventory-*.txt' \) \
    -mtime +"${BACKUP_EXTERNAL_RETENTION_DAYS}" -delete
fi

# Веб-каталог содержит только зашифрованные архивы, checksum и безопасный
# inventory без env/ключей. Старые файлы удаляются до построения индекса.
install -o root -g www-data -m 0640 \
  "${DEST}/inventory.txt" \
  "${PUBLIC_BACKUP_DIR}/inventory-${STAMP}.txt"
find "${PUBLIC_BACKUP_DIR}" -maxdepth 1 -type f \
  \( -name 'ladder-dragon-*.tgz.age*' -o -name 'inventory-*.txt' \) \
  -mtime +14 -delete
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
echo "${BACKUP_DIR}/ladder-dragon-${STAMP}.tgz.age"
