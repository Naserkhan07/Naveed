#!/usr/bin/env bash
# Cloud Run entrypoint for the Shorts Autopilot.
#
# Runs three things in one container so "everything runs on its own":
#   1. bootstrap.sh (sourced)  -> seeds persistent config, writes secret files,
#                                 derives paths, auto-disables platforms with no creds
#   2. clip_loop.sh            -> feeds hotclip-watch/* through HotClip's headless
#                                 CLI into hotclip-exports/ (the clipper)
#   3. backup_loop.sh          -> periodically snapshots the SQLite queue to /data
#   4. main.py (the bot)       -> discovery + queue + scheduled publishing, and it
#                                 serves the live dashboard on 0.0.0.0:$PORT (with
#                                 /healthz) that Cloud Run health-checks.
set -euo pipefail

export STATUS_PANEL_HOST="${STATUS_PANEL_HOST:-0.0.0.0}"
export STATUS_PANEL_PORT="${STATUS_PANEL_PORT:-${PORT:-8080}}"
export STATUS_PANEL_ENABLED="${STATUS_PANEL_ENABLED:-true}"

echo "[entrypoint] bootstrapping persistent state + secrets…"
set -a
# shellcheck disable=SC1091
source /app/cloudrun/bootstrap.sh
set +a

echo "[entrypoint] starting HotClip clipper loop…"
bash /app/cloudrun/clip_loop.sh &
CLIP_PID=$!

echo "[entrypoint] starting SQLite backup loop…"
bash /app/cloudrun/backup_loop.sh &
BACKUP_PID=$!

echo "[entrypoint] starting autopilot watcher (dashboard on :${STATUS_PANEL_PORT})…"
python main.py &
BOT_PID=$!

shutdown() {
  echo "[entrypoint] shutdown signal received; stopping…"
  kill "$BOT_PID" "$CLIP_PID" "$BACKUP_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap shutdown TERM INT

# Stay alive as long as the bot runs. If the bot ever exits (crash / config
# error), tear everything down so Cloud Run starts a fresh instance.
wait "$BOT_PID" || true
echo "[entrypoint] watcher exited; shutting down container for restart."
shutdown
