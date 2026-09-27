#!/usr/bin/env bash
# Sourced by entrypoint.sh. Prepares the persistent /data volume:
#   * seeds editable config files (channels, hashtags, links) once
#   * materializes secret files from Cloud Run secret env vars
#   * derives the *_FILE paths the bot reads
#   * auto-disables any publishing platform whose credentials are missing so a
#     partial setup still boots (mirrors the GitHub Actions "pick platforms" step)
#
# Because this is sourced, the `export`s below affect the bot's environment.

: "${DATA_DIR:=/data}"
: "${WORK_DIR:=/data/work}"

mkdir -p "$DATA_DIR/work" "$DATA_DIR/hotclip-watch" "$DATA_DIR/hotclip-exports"

# --- Seed editable config onto the volume (only the first time) ---------------
seed_if_absent() { # dest src
  if [ ! -e "$1" ] && [ -e "$2" ]; then
    cp "$2" "$1"
    echo "[bootstrap] seeded $(basename "$1")"
  fi
}
seed_if_absent "$DATA_DIR/channels.toml" /app/channels.toml
seed_if_absent "$DATA_DIR/channels.txt"  /app/channels.txt
seed_if_absent "$DATA_DIR/hashtags.txt"  /app/hashtags.txt
seed_if_absent "$DATA_DIR/links.txt"     /app/links.txt

# Point the bot at the persistent, live-editable copies (edit them in the bucket
# without rebuilding the image).
export CHANNELS_FILE="$DATA_DIR/channels.txt"
export CHANNEL_CONFIG_FILE="$DATA_DIR/channels.toml"
export HASHTAGS_FILE="$DATA_DIR/hashtags.txt"
export LINKS_FILE="$DATA_DIR/links.txt"
export DOWNLOADED_LINKS_LOG="$DATA_DIR/work/downloaded-links.log"

# --- YouTube OAuth token: secret -> file --------------------------------------
if [ -n "${YOUTUBE_TOKEN_JSON:-}" ]; then
  printf '%s' "$YOUTUBE_TOKEN_JSON" > "$DATA_DIR/work/youtube-token.json"
  export YOUTUBE_TOKEN_FILE="$DATA_DIR/work/youtube-token.json"
  echo "[bootstrap] YouTube token written"
elif [ "${UPLOAD_YOUTUBE:-false}" = "true" ]; then
  echo "[bootstrap] YOUTUBE_TOKEN_JSON secret missing -> disabling YouTube uploads" >&2
  export UPLOAD_YOUTUBE=false
fi

# --- yt-dlp cookies (datacenter IPs often need these): secret -> file ---------
if [ -n "${YTDLP_COOKIES_TXT:-}" ]; then
  printf '%s' "$YTDLP_COOKIES_TXT" > "$DATA_DIR/work/ytdlp-cookies.txt"
  export YTDLP_COOKIE_FILE="$DATA_DIR/work/ytdlp-cookies.txt"
  echo "[bootstrap] yt-dlp cookies written"
fi

# --- Instagram / Facebook gating ----------------------------------------------
if [ "${UPLOAD_INSTAGRAM:-false}" = "true" ] && [ -z "${INSTAGRAM_ACCESS_TOKEN:-}" ]; then
  echo "[bootstrap] INSTAGRAM_ACCESS_TOKEN missing -> disabling Instagram uploads" >&2
  export UPLOAD_INSTAGRAM=false
fi
if [ "${UPLOAD_FACEBOOK:-false}" = "true" ] \
   && [ -z "${FACEBOOK_ACCESS_TOKEN:-}" ] && [ -z "${INSTAGRAM_ACCESS_TOKEN:-}" ]; then
  echo "[bootstrap] no Facebook/Instagram token -> disabling Facebook uploads" >&2
  export UPLOAD_FACEBOOK=false
fi

echo "[bootstrap] platforms -> youtube=${UPLOAD_YOUTUBE:-false} instagram=${UPLOAD_INSTAGRAM:-false} facebook=${UPLOAD_FACEBOOK:-false}"
