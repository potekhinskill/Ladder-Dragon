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
BACKUP_STAGING_RETENTION_MINUTES=60
BACKUP_LOCAL_MIN_FREE_BYTES=8589934592
STAMP="$(date -u +%Y-%m-%d-%H%M%S)"
DEST="${BACKUP_DIR}/${STAMP}"
STATUS_ARCHIVE_NAME=""
STATUS_ARCHIVE_SIZE=""
STATUS_ARCHIVE_SHA256=""
ACTIVE_TEMP_FILES=()
EXTERNAL_STORE=""
STAGING_CREATED=0

# DEST temporarily contains decrypted env/SQLite data. Remove staging even when
# the external mirror fails, so an emergency backup never leaves secrets on the SD card.
write_status() {
  local status="$1"
  local reason="${2:-}"
  local tmp runtime_tmp
  tmp="${PUBLIC_BACKUP_DIR}/.backup_status.$$"
  mkdir -p "${PUBLIC_BACKUP_DIR}" 2>/dev/null || return 0
  if [[ "${status}" == "success" && -n "${STATUS_ARCHIVE_NAME}" ]]; then
    printf '{"schema_version":2,"status":"success","reason":"","updated_at":"%s UTC","archive_name":"%s","archive_size_bytes":%s,"archive_sha256":"%s","archive_verified":true,"storage":"external","external_mount":"%s","external_directory":"%s"}\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%S)" "${STATUS_ARCHIVE_NAME}" \
      "${STATUS_ARCHIVE_SIZE}" "${STATUS_ARCHIVE_SHA256}" \
      "${BACKUP_EXTERNAL_MOUNT}" "${BACKUP_EXTERNAL_DIR}" >"${tmp}" 2>/dev/null || return 0
  else
    printf '{"schema_version":2,"status":"failed","reason":"%s","updated_at":"%s UTC"}\n' \
      "${reason}" "$(date -u +%Y-%m-%dT%H:%M:%S)" >"${tmp}" 2>/dev/null || return 0
  fi
  chown root:www-data "${tmp}" 2>/dev/null || true
  chmod 0640 "${tmp}" 2>/dev/null || true
  sync -f "${tmp}" 2>/dev/null || true
  mv -f "${tmp}" "${BACKUP_STATUS_FILE}" 2>/dev/null || true
  install -d -m 0755 "$(dirname "${RUNTIME_STATUS_FILE}")" 2>/dev/null || true
  runtime_tmp="${RUNTIME_STATUS_FILE}.tmp.$$"
  cp "${BACKUP_STATUS_FILE}" "${runtime_tmp}" 2>/dev/null || return 0
  chmod 0644 "${runtime_tmp}" 2>/dev/null || true
  sync -f "${runtime_tmp}" 2>/dev/null || true
  mv -f "${runtime_tmp}" "${RUNTIME_STATUS_FILE}" 2>/dev/null || true
}

cleanup_staging() {
  local temporary
  for temporary in "${ACTIVE_TEMP_FILES[@]}"; do
    rm -f -- "${temporary}"
  done
  if [[ "${STAGING_CREATED}" == 1 ]]; then
    rm -rf -- "${DEST}"
  fi
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
# Shared with updates; an exclusive watchdog recovery must wait for completion.
mkdir -p /var/lib/ladder-dragon
exec 18>>/var/lib/ladder-dragon/network-recovery.lock
flock -s -w 45 18 || { echo "[FAIL] network recovery is active" >&2; exit 1; }
exec 17>>/var/lib/ladder-dragon/backup.lock
flock -n 17 || { echo "[FAIL] another backup is active" >&2; exit 1; }
if [[ -r /var/lib/pi-watchdog/network-reboot.boot ]] && \
  cmp -s /var/lib/pi-watchdog/network-reboot.boot /proc/sys/kernel/random/boot_id; then
  echo "[FAIL] network reboot is pending" >&2
  exit 1
fi
command -v age >/dev/null || {
  echo "[FAIL] age is required for encrypted backups" >&2
  exit 1
}
[[ "${BACKUP_AGE_RECIPIENT}" == age1* ]] || {
  echo "[FAIL] BACKUP_AGE_RECIPIENT is missing or invalid" >&2
  exit 1
}
if [[ -z "${BACKUP_EXTERNAL_MOUNT}" || -z "${BACKUP_EXTERNAL_DIR}" ]]; then
  echo "[FAIL] external backup storage is required" >&2
  exit 1
fi
if [[ -n "${BACKUP_EXTERNAL_MOUNT}" && -n "${BACKUP_EXTERNAL_DIR}" ]]; then
  for path in "${BACKUP_EXTERNAL_MOUNT}" "${BACKUP_EXTERNAL_DIR}"; do
    [[ "${path}" =~ ^/[A-Za-z0-9._/@+-]+$ && "$(realpath -m "${path}")" == "${path}" ]] || {
      echo "[FAIL] external backup paths must be canonical absolute paths" >&2
      exit 1
    }
  done
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
  [[ "$(stat -c %d "${BACKUP_EXTERNAL_MOUNT}")" != "$(stat -c %d /)" ]] || {
    echo "[FAIL] external backup storage must not use the root filesystem" >&2
    exit 1
  }
  # Pin the mounted filesystem before any write. Unmount cannot redirect an
  # absolute pathname to the underlying SD-card mountpoint during this run.
  exec 19<"${BACKUP_EXTERNAL_MOUNT}"
  [[ "$(stat -Lc %d "/proc/$$/fd/19")" != "$(stat -c %d /)" ]] || {
    echo "[FAIL] external backup mount detached before directory open" >&2
    exit 1
  }
  external_relative="${BACKUP_EXTERNAL_DIR#"${BACKUP_EXTERNAL_MOUNT}/"}"
  # exFAT does not support chmod; mount options own ciphertext permissions.
  mkdir -p "/proc/$$/fd/19/${external_relative}"
  exec 20<"/proc/$$/fd/19/${external_relative}"
  EXTERNAL_STORE="/proc/$$/fd/20"
  [[ "$(stat -Lc %d "${EXTERNAL_STORE}")" == "$(stat -Lc %d "/proc/$$/fd/19")" ]] || {
    echo "[FAIL] backup directory is outside the pinned external filesystem" >&2
    exit 1
  }
fi
install -d -m 0700 "${BACKUP_DIR}"
install -d -o root -g www-data -m 0750 "${PUBLIC_BACKUP_DIR}"

prune_stale_local_staging() {
  local staging name
  while IFS= read -r -d '' staging; do
    name="${staging##*/}"
    # Remove only the timestamp format created by this script.
    [[ "${name}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{6}$ ]] || continue
    rm -rf -- "${staging}"
  done < <(
    find "${BACKUP_DIR}" -mindepth 1 -maxdepth 1 -type d \
      -mmin +"${BACKUP_STAGING_RETENTION_MINUTES}" -print0
  )
}

prune_stale_local_temporary_files() {
  local directory="$1"
  # Match only randomized temporary names created by this backup script.
  find "${directory}" -maxdepth 1 -type f \
    \( -name '.ladder-dragon-*.tgz.age.tmp.*' \
       -o -name '.preinstall-*.tgz.age.tmp.*' \
       -o -name '.ladder-dragon-*.tgz.age.sha256.tmp.*' \
       -o -name '.preinstall-*.tgz.age.sha256.tmp.*' \
       -o -name '.index.*' -o -name '.backup_status.*' -o -name '.backup-link.*' \) \
    -mmin +"${BACKUP_STAGING_RETENTION_MINUTES}" -delete
}

rebuild_public_index() {
  local manifest_tmp
  manifest_tmp="$(mktemp "${PUBLIC_BACKUP_DIR}/.index.XXXXXX")"
  {
    echo "Ladder Dragon encrypted backups"
    echo "Generated: ${STAMP} UTC"
    echo "Archives are age-encrypted; inventory files contain no secrets."
    find "${PUBLIC_BACKUP_DIR}" -maxdepth 1 \
      \( -type f -o -type l \) \
      \( -name '*.tgz.age' -o -name '*.tgz.age.sha256' -o -name 'inventory-*.txt' \) \
      -printf '%f\n' | sort
  } >"${manifest_tmp}"
  install -o root -g www-data -m 0640 "${manifest_tmp}" "${PUBLIC_BACKUP_DIR}/index.txt"
  rm -f "${manifest_tmp}"
}

prune_expired_external_backups() {
  local latest_archive="" expired archive_checksum retention_minutes
  [[ -n "${BACKUP_EXTERNAL_DIR}" ]] || return 0
  retention_minutes=$((BACKUP_EXTERNAL_RETENTION_DAYS * 24 * 60))

  # Reclaim expired external capacity before writing a new archive. Preserve the
  # newest encrypted archive until a replacement is verified and published.
  latest_archive="$({
    find "${EXTERNAL_STORE}/" -maxdepth 1 -type f \
      \( -name 'ladder-dragon-*.tgz.age' -o -name 'preinstall-*.tgz.age' \) \
      -printf '%T@ %p\n'
  } | sort -nr | sed -n '1{s/^[^ ]* //;p;}')"

  while IFS= read -r -d '' expired; do
    [[ "${expired}" == "${latest_archive}" ]] && continue
    archive_checksum="${expired}.sha256"
    rm -f -- "${expired}" "${archive_checksum}"
  done < <(
    find "${EXTERNAL_STORE}/" -maxdepth 1 -type f \
      \( -name 'ladder-dragon-*.tgz.age' -o -name 'preinstall-*.tgz.age' \) \
      -mmin +"${retention_minutes}" -print0
  )

  find "${EXTERNAL_STORE}/" -maxdepth 1 -type f \
    -name 'inventory-*.txt' \
    -mmin +"${retention_minutes}" -delete
}

# Only private transient source snapshots remain local. Completed ciphertext
# is written directly to the pinned external filesystem, never the SD card.
prune_stale_local_staging
prune_stale_local_temporary_files "${BACKUP_DIR}"
prune_stale_local_temporary_files "${PUBLIC_BACKUP_DIR}"
prune_stale_local_temporary_files "${EXTERNAL_STORE}/"
prune_expired_external_backups
[[ "$(df -PB1 "${BACKUP_DIR}" | awk 'NR==2 {print $4}')" -ge "${BACKUP_LOCAL_MIN_FREE_BYTES}" ]] || {
  echo "[FAIL] insufficient local capacity for private SQLite staging" >&2
  exit 1
}
rebuild_public_index
[[ ! -e "${DEST}" ]] || { echo "[FAIL] backup staging identity already exists" >&2; exit 1; }
install -d -m 0700 "${DEST}"
STAGING_CREATED=1

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
  /etc/systemd/system/ladder-dragon-soak-audit.service \
  /etc/systemd/system/ladder-dragon-soak-audit.timer \
	  /etc/systemd/system/ladder-dragon-market-scenario.service \
	  /etc/systemd/system/ladder-dragon-market-scenario.timer \
	  /etc/systemd/system/ladder-dragon-database-retention.service \
	  /etc/systemd/system/ladder-dragon-database-retention.timer \
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

# Watchdog state and the current Telegram configuration stay only inside the
# encrypted age archive. They never enter the HTTP directory.
for path in \
  /etc/watchdog.conf \
  /etc/ladder-dragon/telegram.env \
  /etc/ladder-dragon/soak-report-signing.pem \
  /etc/ladder-dragon/soak-report-signing.pub.pem \
  /etc/systemd/system/pi-watchdog-v3.service \
  /etc/systemd/system/pi-watchdog-v3.timer \
  /etc/systemd/system/pi-watchdog-v3.service.d \
  /etc/logrotate.d/pi-watchdog \
  /usr/local/bin/pi-watchdog_v3.sh \
  /usr/local/libexec/ladder-dragon/network_recovery.py \
  /var/lib/pi-watchdog/network-recovery.json \
  /var/lib/pi-watchdog/network-reboot.boot \
  /usr/local/bin/ladder-dragon-soak-audit \
  /var/lib/ladder-dragon/soak \
  /var/lib/ladder-dragon/database-archives \
  /var/lib/ladder-dragon/database-retention \
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
from contextlib import closing
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
            with closing(
                sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30)
            ) as src:
                src.execute("PRAGMA busy_timeout=30000")
                with closing(sqlite3.connect(temporary, timeout=30)) as out:
                    out.execute("PRAGMA busy_timeout=30000")
                    # Copy one pinned snapshot. A paginated backup can restart
                    # forever when the active WAL changes between page batches.
                    src.backup(out)
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

# The archive is never written to disk unencrypted. A same-directory rename
# prevents the dashboard or mirror loop from observing partial ciphertext.
archive_name="ladder-dragon-${STAMP}.tgz.age"
[[ ! -e "${EXTERNAL_STORE}/${archive_name}" ]] || {
  echo "[FAIL] backup archive identity already exists" >&2
  exit 1
}
archive_tmp="$(mktemp "${EXTERNAL_STORE}/.${archive_name}.tmp.XXXXXX")"
ACTIVE_TEMP_FILES+=("${archive_tmp}")
# age must create its output path and refuses an existing replacement.
# The pinned filesystem owns the randomized ciphertext path.
rm -f "${archive_tmp}"
tar -C "${BACKUP_DIR}" -czf - "${STAMP}" \
  | age -r "${BACKUP_AGE_RECIPIENT}" \
      -o "${archive_tmp}"
[[ -s "${archive_tmp}" ]] || {
  echo "[FAIL] encrypted backup archive is empty" >&2
  exit 1
}
sync -f "${archive_tmp}"
mv -f "${archive_tmp}" "${EXTERNAL_STORE}/${archive_name}"

# Keep a portable checksum beside the external ciphertext.
checksum_tmp="$(mktemp "${EXTERNAL_STORE}/.${archive_name}.sha256.tmp.XXXXXX")"
ACTIVE_TEMP_FILES+=("${checksum_tmp}")
(cd "${EXTERNAL_STORE}" && sha256sum "${archive_name}" >"${checksum_tmp}")
sync -f "${checksum_tmp}"
mv -f "${checksum_tmp}" "${EXTERNAL_STORE}/${archive_name}.sha256"
(cd "${EXTERNAL_STORE}" && sha256sum -c "${archive_name}.sha256" >/dev/null)

publish_public_archive() {
  local name="$1" target link_tmp
  # Publish links to ciphertext only. No archive bytes enter the web directory.
  for target in "${name}" "${name}.sha256"; do
    link_tmp="$(mktemp "${PUBLIC_BACKUP_DIR}/.backup-link.XXXXXX")"
    ACTIVE_TEMP_FILES+=("${link_tmp}")
    rm -f "${link_tmp}"
    ln -s "${BACKUP_EXTERNAL_DIR}/${target}" "${link_tmp}"
    mv -Tf "${link_tmp}" "${PUBLIC_BACKUP_DIR}/${target}"
  done
}

retire_local_duplicates() {
  local directory archive name local_digest external_digest
  # Migration is non-destructive for unique or mismatched legacy archives.
  # Only exact ciphertext counterparts can replace old local recovery copies.
  for directory in "${BACKUP_DIR}" "${PUBLIC_BACKUP_DIR}"; do
    while IFS= read -r -d '' archive; do
      name="${archive##*/}"
      [[ "${name}" =~ ^ladder-dragon-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{6}\.tgz\.age$ ]] || continue
      [[ -f "${EXTERNAL_STORE}/${name}" && ! -L "${EXTERNAL_STORE}/${name}" \
         && -f "${EXTERNAL_STORE}/${name}.sha256" && ! -L "${EXTERNAL_STORE}/${name}.sha256" \
         && "$(stat -c %s "${EXTERNAL_STORE}/${name}.sha256")" -le 256 ]] || continue
      local_digest="$(sha256sum "${archive}" | awk '{print $1}')"
      external_digest="$(sha256sum "${EXTERNAL_STORE}/${name}" | awk '{print $1}')"
      [[ "${local_digest}" == "${external_digest}" ]] || continue
      [[ "$(cat "${EXTERNAL_STORE}/${name}.sha256")" == "${external_digest}  ${name}" ]] || continue
      rm -f -- "${archive}" "${archive}.sha256"
    done < <(find "${directory}" -maxdepth 1 -type f -name 'ladder-dragon-*.tgz.age' -print0)
  done
}

# Reject a disconnected or replaced mount before public success publication.
[[ "$(findmnt -T "${BACKUP_EXTERNAL_MOUNT}" -no TARGET)" == "${BACKUP_EXTERNAL_MOUNT}" \
   && "$(stat -c %d "${BACKUP_EXTERNAL_DIR}")" == "$(stat -Lc %d "${EXTERNAL_STORE}")" ]] || {
  echo "[FAIL] external backup mount changed during backup" >&2
  exit 1
}
publish_public_archive "${archive_name}"
retire_local_duplicates
cp --preserve=timestamps -f "${DEST}/inventory.txt" \
  "${EXTERNAL_STORE}/inventory-${STAMP}.txt"
prune_expired_external_backups
install -o root -g www-data -m 0640 \
  "${DEST}/inventory.txt" \
  "${PUBLIC_BACKUP_DIR}/inventory-${STAMP}.txt"
# Public records are disposable pointers and inventories, not recovery copies.
find "${PUBLIC_BACKUP_DIR}" -maxdepth 1 -type l \
  \( -name 'ladder-dragon-*.tgz.age' -o -name 'ladder-dragon-*.tgz.age.sha256' \) \
  ! -name "${archive_name}" ! -name "${archive_name}.sha256" -delete
find "${PUBLIC_BACKUP_DIR}" -maxdepth 1 -type f \
  -name 'inventory-*.txt' -mmin +60 -delete
rebuild_public_index
STATUS_ARCHIVE_NAME="${archive_name}"
STATUS_ARCHIVE_SIZE="$(stat -c %s "${EXTERNAL_STORE}/${archive_name}")"
STATUS_ARCHIVE_SHA256="$(sha256sum "${EXTERNAL_STORE}/${archive_name}" | awk '{print $1}')"
echo "${BACKUP_EXTERNAL_DIR}/${archive_name}"
