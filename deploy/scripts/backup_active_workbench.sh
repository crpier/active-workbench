#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${ACTIVE_WORKBENCH_DATA_DIR:-/var/lib/active-workbench/data}"
BACKUP_DIR="${ACTIVE_WORKBENCH_BACKUP_DIR:-/var/lib/active-workbench/backups}"
RETENTION_DAYS="${ACTIVE_WORKBENCH_BACKUP_RETENTION_DAYS:-14}"

STATE_DB="${DATA_DIR}/state.db"
LOG_DIR="${DATA_DIR}/logs"
TIMESTAMP_UTC="$(date -u +"%Y%m%dT%H%M%SZ")"
WORK_DIR="${BACKUP_DIR}/.tmp-${TIMESTAMP_UTC}"
TARGET_DIR="${BACKUP_DIR}/${TIMESTAMP_UTC}"

mkdir -p "${WORK_DIR}" "${TARGET_DIR}"

if [[ -f "${STATE_DB}" ]]; then
  sqlite3 "${STATE_DB}" ".timeout 5000" ".backup '${WORK_DIR}/state.db'"
  gzip -9 "${WORK_DIR}/state.db"
fi

if [[ -d "${LOG_DIR}" ]]; then
  tar -C "${DATA_DIR}" -czf "${WORK_DIR}/logs.tar.gz" logs
fi

mv "${WORK_DIR}"/* "${TARGET_DIR}/"
rmdir "${WORK_DIR}" || true

find "${BACKUP_DIR}" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETENTION_DAYS}" -exec rm -rf {} +

echo "Backup complete: ${TARGET_DIR}"

