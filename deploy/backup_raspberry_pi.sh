#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: create encrypted application and SQLite backups.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/bot/apps/binance_bot}"
BACKUP_DIR="${BACKUP_DIR:-/var/lib/ladder-dragon/backups}"
PUBLIC_BACKUP_DIR="${PUBLIC_BACKUP_DIR:-/var/lib/ladder-dragon/backups-public}"
BACKUP_STATUS_FILE="${PUBLIC_BACKUP_DIR}/backup_status.json"
RUNTIME_STATUS_FILE="${BACKUP_RUNTIME_STATUS_FILE:-/run/mybot/backup_status.json}"
BACKUP_AGE_RECIPIENT="${BACKUP_AGE_RECIPIENT:-}"
BACKUP_EXTERNAL_MOUNT="${BACKUP_EXTERNAL_MOUNT:-}"
BACKUP_EXTERNAL_DIR="${BACKUP_EXTERNAL_DIR:-}"
BACKUP_EXTERNAL_RETENTION_DAYS="${BACKUP_EXTERNAL_RETENTION_DAYS:-90}"
STAMP="$(date -u +%Y-%m-%d-%H%M%S)"
DEST="${BACKUP_DIR}/${STAMP}"

# DEST temporarily contains decrypted env/SQLite data. Remove staging even when
# the external mirror fails, so an emergency backup never leaves secrets on the SD card.
write_status() {
  local status="$1"
  local reason="${2:-}"
  local tmp="${PUBLIC_BACKUP_DIR}/.backup_status.$$"
  mkdir -p "${PUBLIC_BACKUP_DIR}" 2>/dev/null || return 0
  printf '{"status":"%s","reason":"%s","updated_at":"%s UTC"}\n' \
    "${status}" "${reason}" "$(date -u +%Y-%m-%dT%H:%M:%S)" >"${tmp}" 2>/dev/null || return 0
  install -o root -g www-data -m 0640 "${tmp}" "${BACKUP_STATUS_FILE}" 2>/dev/null || true
  install -d -m 0755 "$(dirname "${RUNTIME_STATUS_FILE}")" 2>/dev/null || true
  install -m 0644 "${tmp}" "${RUNTIME_STATUS_FILE}" 2>/dev/null || true
  rm -f "${tmp}"
}

cleanup_staging() {
  rm -rf -- "${DEST}"
}
on_exit() {
  local rc=$?
  if [[ "${rc}" -eq 0 ]]; then
    write_status success ""
  else
    write_status failed "backup exited with code ${rc}"
  fi
  cleanup_staging
  exit "${rc}"
}
trap on_exit EXIT

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
  # exFAT does not support chmod; external-directory permissions come from mount options.
  mkdir -p "${BACKUP_EXTERNAL_DIR}"
fi
install -d -m 0700 "${DEST}"
install -d -o root -g www-data -m 0750 "${PUBLIC_BACKUP_DIR}"

# The inventory contains no secret-variable values.
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
  if [[ -r /proc/meminfo ]]; then
    echo "memory=$(free -h | awk '/^Mem:/{print $2}')"
  else
    echo "memory=unavailable"
  fi
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
  /etc/default/zramswap \
  /usr/local/libexec/ladder-dragon/export_sanitized_logs.py; do
  [[ -e "${path}" ]] && copy_rootfs_path "${path}"
done

# The legacy watchdog and its Telegram configuration are kept only inside the
# encrypted age archive. They never enter the HTTP directory.
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

# SQLite is copied through the online backup API, without copying inconsistent WAL/SHM files.
python3 - "${PROJECT_DIR}" "${DEST}/project" <<'PY'
import os
import sqlite3
import sys
import time
from pathlib import Path

project = Path(sys.argv[1])
dest = Path(sys.argv[2])
dest.mkdir(parents=True, exist_ok=True)
for source in sorted((project / "db").glob("*.db")) + sorted((project / "db").glob("*.sqlite3")):
    if not source.is_file():
        continue
    target = dest / source.name
    temporary = target.with_name(f".{target.name}.tmp")
    # With an active SQLite WAL, a short close/write race can temporarily return
    # "unable to open database file". Retry the online backup, but after all attempts
    # fail, abort without publishing an incomplete archive.
    for attempt in range(3):
        try:
            temporary.unlink(missing_ok=True)
            with sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30) as src:
                src.execute("PRAGMA busy_timeout=30000")
                with sqlite3.connect(temporary, timeout=30) as out:
                    out.execute("PRAGMA busy_timeout=30000")
                    src.backup(out, pages=100, sleep=0.2)
            os.replace(temporary, target)
            break
        except sqlite3.OperationalError as exc:
            if attempt == 2:
                raise RuntimeError(
                    f"SQLite online backup failed for {source.name}: {exc}"
                ) from exc
            time.sleep(1)
    os.chmod(target, 0o600)
PY

# The archive is never written to disk unencrypted: tar is streamed directly into age.
tar -C "${BACKUP_DIR}" -czf - "${STAMP}" \
  | age -r "${BACKUP_AGE_RECIPIENT}" \
      -o "${BACKUP_DIR}/ladder-dragon-${STAMP}.tgz.age"

# Keep a checksum with a relative filename. It can be verified on the SD card,
# the external disk, or after downloading from /backups/.
archive_name="ladder-dragon-${STAMP}.tgz.age"
(cd "${BACKUP_DIR}" && sha256sum "${archive_name}" >"${archive_name}.sha256")
chmod 0600 "${BACKUP_DIR}/${archive_name}" "${BACKUP_DIR}/${archive_name}.sha256"

# Before publishing, remove only expired local copies, then synchronize the full
# remaining set rather than only the newest archive. This restores historical files
# after a migration automatically.
find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'ladder-dragon-*.tgz.age*' \
  -mtime +14 -delete

mirror_external_archive() {
  local source_archive="$1"
  local name
  name="$(basename "${source_archive}")"
  # --preserve=timestamps does not attempt to change exFAT file ownership.
  cp --preserve=timestamps -f "${source_archive}" "${BACKUP_EXTERNAL_DIR}/${name}"
  # Recreate the checksum in the destination directory so the path stays portable
  # and contains no Raspberry Pi local paths.
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
    # The external disk receives every age archive, including preinstall snapshots.
    mirror_external_archive "${source_archive}"
  fi
  # The HTTP directory receives all age-encrypted archives, including preinstall
  # snapshots. Plaintext legacy files never enter it.
  publish_public_archive "${source_archive}"
done
shopt -u nullglob

if [[ -n "${BACKUP_EXTERNAL_DIR}" ]]; then
  # The external disk also receives the secret-free inventory. If the mountpoint is
  # unavailable, the script exits above and never silently writes to the SD card.
  cp --preserve=timestamps -f "${DEST}/inventory.txt" \
    "${BACKUP_EXTERNAL_DIR}/inventory-${STAMP}.txt"
  find "${BACKUP_EXTERNAL_DIR}" -maxdepth 1 -type f \
    \( -name 'ladder-dragon-*.tgz.age*' -o -name 'preinstall-*.tgz.age*' -o -name 'inventory-*.txt' \) \
    -mtime +"${BACKUP_EXTERNAL_RETENTION_DAYS}" -delete
fi

# The web directory contains only encrypted archives, checksums, and a safe
# inventory without env/keys. Old files are removed before the index is rebuilt.
install -o root -g www-data -m 0640 \
  "${DEST}/inventory.txt" \
  "${PUBLIC_BACKUP_DIR}/inventory-${STAMP}.txt"
find "${PUBLIC_BACKUP_DIR}" -maxdepth 1 -type f \
  \( -name '*.tgz.age*' -o -name 'inventory-*.txt' \) \
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
