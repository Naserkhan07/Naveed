#!/usr/bin/env bash
# HotClip clipper loop.
#
# The bot drops downloaded source videos into HOTCLIP_WATCH_DIR. This loop runs
# each pending source through HotClip's headless CLI, writing finished clips
# (mp4 + cover + .post.txt + clips.json) into HOTCLIP_EXPORT_DIR, which the bot
# then harvests into its publish queue. Mirrors the proven GitHub Actions step.
set -uo pipefail

WATCH="${HOTCLIP_WATCH_DIR:-/data/hotclip-watch}"
EXPORT="${HOTCLIP_EXPORT_DIR:-/data/hotclip-exports}"
APP="${HOTCLIP_APP_DIR:-/opt/hotclip-app}"
export PATH="/usr/local/bin:/usr/bin:${PATH:-}"

# Make sure the pnpm shim exists even if corepack state was not persisted.
command -v pnpm >/dev/null 2>&1 || corepack enable pnpm >/dev/null 2>&1 || true

mkdir -p "$WATCH" "$EXPORT"
echo "[clip] clipper loop started (watch=$WATCH export=$EXPORT app=$APP)"

shopt -s nullglob
while true; do
  for src in "$WATCH"/*.mp4 "$WATCH"/*.mov "$WATCH"/*.mkv "$WATCH"/*.webm "$WATCH"/*.m4v; do
    [ -e "$src" ] || continue
    [ -e "$src.clipped" ] && continue     # already processed
    [ -e "$src.clipping" ] && continue    # another pass is on it
    touch "$src.clipping"
    echo "[clip] clipping $(basename "$src") …"
    if ( cd "$APP" && pnpm cli clip "$src" --out "$EXPORT" --json ); then
      touch "$src.clipped"
      echo "[clip] finished $(basename "$src")"
    else
      echo "[clip] FAILED $(basename "$src"); will retry on a later pass"
    fi
    rm -f "$src.clipping"
  done
  sleep 15
done
