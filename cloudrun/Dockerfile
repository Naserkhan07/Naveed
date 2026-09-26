# syntax=docker/dockerfile:1
#
# Self-contained image for the Shorts Autopilot on Google Cloud Run.
#
# Everything the bot needs is downloaded/baked in at BUILD time so the running
# container never has to fetch the project or its dependencies:
#   * Python 3.12 + the project's pinned dependencies
#   * ffmpeg / ffprobe
#   * Node.js 22 + pnpm + HotClip (AGPL, cloned and installed here as a tool)
#
# Persistent state (SQLite queue, watch folder, exports, links) is NOT stored in
# the image — it lives on a Cloud Storage bucket mounted at /data (see deploy.sh).
#
# Build context is the REPO ROOT (see cloudbuild.yaml):  docker build -f cloudrun/Dockerfile .

ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# --- System packages ---------------------------------------------------------
# ffmpeg provides ffprobe; git/curl fetch HotClip; build-essential + python3 are
# needed to compile HotClip's native node modules (esbuild, ffmpeg-static,
# onnxruntime-node, @ffprobe-installer/*). libgl1/libglib2.0-0 cover common
# native runtime deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
        curl \
        ca-certificates \
        build-essential \
        python3 \
        make \
        g++ \
        pkg-config \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# --- Node.js 22 + pnpm (HotClip's headless CLI runtime) ----------------------
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && corepack enable \
    && corepack prepare pnpm@10 --activate

WORKDIR /app

# --- Python dependencies (own layer for caching) -----------------------------
COPY pyproject.toml README.md ./
COPY shorts_bot ./shorts_bot
RUN pip install -e .

# --- Non-secret config files seeded onto the persistent volume at boot --------
# (bootstrap.sh copies these to /data only if not already present there.)
COPY channels.toml channels.txt hashtags.txt links.txt /app/

# --- HotClip (the clipper): clone + install at build time ---------------------
# AGPL-licensed external tool, used as-is (never vendored into this repo).
ARG HOTCLIP_REPO=https://github.com/xixihhhh/hotclip
ARG HOTCLIP_REF=
ENV HOTCLIP_APP_DIR=/opt/hotclip-app \
    PNPM_CONFIG_ONLY_BUILT_DEPENDENCIES="esbuild,ffmpeg-static,onnxruntime-node,@ffprobe-installer/ffprobe,@ffprobe-installer/linux-x64,@ffprobe-installer/darwin-arm64,@ffprobe-installer/darwin-x64,@ffprobe-installer/win32-x64"
RUN set -eux; \
    if [ -n "$HOTCLIP_REF" ]; then \
        git clone --depth 1 -b "$HOTCLIP_REF" "$HOTCLIP_REPO" "$HOTCLIP_APP_DIR"; \
    else \
        git clone --depth 1 "$HOTCLIP_REPO" "$HOTCLIP_APP_DIR"; \
    fi; \
    cd "$HOTCLIP_APP_DIR"; \
    pnpm install --frozen-lockfile=false \
        --config.onlyBuiltDependencies=esbuild,ffmpeg-static,onnxruntime-node,@ffprobe-installer/ffprobe,@ffprobe-installer/linux-x64,@ffprobe-installer/darwin-arm64,@ffprobe-installer/darwin-x64,@ffprobe-installer/win32-x64

# --- Runtime defaults ---------------------------------------------------------
# Persistent state is on the /data Cloud Storage volume. The status dashboard
# binds 0.0.0.0:$PORT so Cloud Run can reach it (entrypoint.sh finalizes $PORT).
ENV WORK_DIR=/data/work \
    DATABASE_PATH=/data/work/jobs.db \
    HOTCLIP_WATCH_DIR=/data/hotclip-watch \
    HOTCLIP_EXPORT_DIR=/data/hotclip-exports \
    HOTCLIP_APP_DIR=/opt/hotclip-app \
    STATUS_PANEL_HOST=0.0.0.0 \
    STATUS_PANEL_PORT=8080 \
    STATUS_PANEL_ENABLED=true

# --- Cloud Run helper scripts -------------------------------------------------
COPY cloudrun/entrypoint.sh cloudrun/bootstrap.sh cloudrun/clip_loop.sh \
     cloudrun/backup_loop.sh cloudrun/backup_db.py /app/cloudrun/
RUN chmod +x /app/cloudrun/*.sh

# Cloud Run health: the status panel answers /healthz and / on STATUS_PANEL_PORT.
EXPOSE 8080

ENTRYPOINT ["/app/cloudrun/entrypoint.sh"]
