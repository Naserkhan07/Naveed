#!/usr/bin/env bash
# First-deploy helper: restore the project's credential material into
# cloudrun/secrets/ so the first Cloud Run deploy boots with publishing enabled.
#
#   bash cloudrun/seed_secrets_from_repo.sh
#
# What it does (never prints any secret value, only filenames):
#   1. runs setup_secrets.py  -> .env, client_secret.json, youtube_token.json
#   2. copies youtube_token.json into cloudrun/secrets/
#   3. extracts the Instagram/Facebook token values from .env into the
#      cloudrun/secrets/*.txt files the deploy script expects
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

mkdir -p cloudrun/secrets

echo "[seed] decoding committed secrets (setup_secrets.py)…"
python3 setup_secrets.py 2>/dev/null || python setup_secrets.py

if [ -f youtube_token.json ]; then
  cp youtube_token.json cloudrun/secrets/youtube_token.json
  echo "[seed] cloudrun/secrets/youtube_token.json ready"
else
  echo "[seed] WARNING: youtube_token.json was not produced; YouTube will stay off" >&2
fi

python3 - <<'PY'
import pathlib

env = {}
p = pathlib.Path(".env")
if p.exists():
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")

targets = [
    ("INSTAGRAM_ACCESS_TOKEN", "instagram_access_token.txt"),
    ("IG_ACCESS_TOKEN",        "instagram_access_token.txt"),
    ("INSTAGRAM_TOKEN",        "instagram_access_token.txt"),
    ("FACEBOOK_ACCESS_TOKEN",  "facebook_access_token.txt"),
    ("FB_ACCESS_TOKEN",        "facebook_access_token.txt"),
    ("FACEBOOK_TOKEN",         "facebook_access_token.txt"),
]
out = pathlib.Path("cloudrun/secrets")
seen = set()
for key, fname in targets:
    if key in env and env[key] and fname not in seen:
        (out / fname).write_text(env[key], encoding="utf-8")
        seen.add(fname)
        print(f"[seed] cloudrun/secrets/{fname} ready (from .env:{key})")

for fname in ("instagram_access_token.txt", "facebook_access_token.txt"):
    if fname not in seen:
        print(f"[seed] no matching key in .env for {fname} -> that platform stays off")
PY

echo "[seed] done. cloudrun/secrets contains:"
ls -1 cloudrun/secrets
