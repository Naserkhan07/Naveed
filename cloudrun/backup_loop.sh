#!/usr/bin/env bash
# Periodically snapshot the SQLite queue to the /data bucket so the publish
# state is recoverable even if the gcsfuse-backed database is ever damaged.
set -uo pipefail

DB="${DATABASE_PATH:-/data/work/jobs.db}"
INTERVAL="${DB_BACKUP_INTERVAL_SECONDS:-1800}"
KEEP="${DB_BACKUP_KEEP:-3}"

echo "[backup] backup loop started (db=$DB every=${INTERVAL}s keep=${KEEP})"
while true; do
  if [ -f "$DB" ]; then
    python /app/cloudrun/backup_db.py "$DB" "$(dirname "$DB")" "$KEEP" || true
  fi
  sleep "$INTERVAL"
done
