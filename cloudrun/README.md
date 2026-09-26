# Run the Shorts Autopilot on Google Cloud (Cloud Run)

This folder deploys the whole pipeline — discovery → HotClip clipping → publish
queue → scheduled uploads → live dashboard — to **Google Cloud Run** as a single,
always-on container. No PC to leave on, no VM to patch: Cloud Run keeps one
instance warm 24/7 and restarts it automatically if it ever crashes, and all
state lives in a Cloud Storage bucket so nothing is lost across restarts or
redeploys.

```
channels.txt ─► discover uploads ─► download ─► /data/hotclip-watch/
                                                      │ HotClip (headless CLI, in-container)
   /data/hotclip-exports/ ◄── finished clips ◄────────┘
        │  harvest into SQLite queue (/data/work/jobs.db)
        ▼
   scheduled publishing ─► YouTube / Instagram / Facebook
        │
        └─► live dashboard served on the Cloud Run URL (same page as localhost)
```

> **You can't click "deploy" from here — and neither can I.** This sandbox has no
> access to your Google Cloud account (no `gcloud` auth, billing, or project).
> Everything below is prepared for you; you run the commands with your own
> credentials. It's ~5 minutes of setup the first time.

---

## ⚠️ Read this first — rotate your leaked credentials

Your repository's committed **`.envexample`** contains `SAFE_ENV`,
`SAFE_CLIENT_SECRET`, and `SAFE_YOUTUBE_TOKEN` — base64-obfuscated (trivially
reversible by anyone who clones the repo) copies of your real `.env`, OAuth
`client_secret.json`, and `youtube_token.json`. `setup_secrets.py` decodes them.

Because they are in git history, treat them as **compromised**:

1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials),
   **delete and recreate the OAuth 2.0 Client ID**, then re-run
   `python -m shorts_bot.youtube_auth` to mint a fresh `youtube_token.json`.
2. Remove `.envexample` (and `setup_secrets.py` if you no longer need it) from
   the repo, and purge them from history if the repo is public.
3. Never commit real tokens again. For this deployment, secrets go into
   **Secret Manager** (below), never into the image or git.

This deploy path deliberately does **not** read `.envexample` or bake any secret
into the container — you supply secrets separately.

---

## What it costs (rough, `us-central1`)

Cloud Run with an always-on single instance bills for the whole instance
lifecycle. Ballpark, always-on:

| CPU | Memory | ~/month |
| --- | --- | --- |
| 1 vCPU | 2 GiB  | ~$70  |
| 2 vCPU | 4 GiB  | ~$150 |

Plus Cloud Storage (a few GB of clips/state ≈ pennies) and egress. **Clipping
(HotClip) is the expensive part** — it's CPU/RAM heavy. The defaults are
`--cpu 2 --memory 4Gi`; lower to `--cpu 1 --memory 2Gi` if clipping load is
light, or raise memory if clips fail. (If cost matters a lot and you also want
HotClip, a small always-on **Compute Engine VM** is usually cheaper per unit of
compute — say the word and I'll add that path too.)

---

## Prerequisites

- A Google Cloud project with **billing enabled**.
- [`gcloud` CLI](https://cloud.google.com/sdk/docs/install) installed and
  authenticated: `gcloud auth login`.
- Your account IDs are already in `channels.toml` (YouTube channel, Instagram
  user, Facebook page). Keep that file's IDs correct.

---

## One-time setup

### 1. Point gcloud at your project

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud auth login
```

### 2. Put your secrets in `cloudrun/secrets/` (gitignored)

Create the folder and drop in whichever credentials you have. Missing files are
fine — the matching platform just stays off until you add it.

```bash
mkdir -p cloudrun/secrets

# YouTube: the OAuth token you generated locally (the whole file's contents)
cp /path/to/youtube_token.json cloudrun/secrets/youtube_token.json

# Instagram long-lived Meta token (just the token string)
printf '%s' 'EAAG...your-instagram-token' > cloudrun/secrets/instagram_access_token.txt

# Facebook Page token (optional — leave out to reuse the Instagram token)
printf '%s' 'EAAG...your-page-token'      > cloudrun/secrets/facebook_access_token.txt

# YouTube cookies so downloads work from a datacenter IP (see note below)
cp /path/to/youtube-cookies.txt cloudrun/secrets/ytdlp-cookies.txt
```

> **YouTube cookies (important):** Cloud Run's outbound IP is a datacenter
> address, and YouTube frequently answers "Sign in to confirm you're not a bot."
> Export cookies from a signed-in browser in **Netscape** format
> (e.g. a "Get cookies.txt" browser extension on youtube.com) into
> `cloudrun/secrets/ytdlp-cookies.txt`. Without it, downloads may fail and the
> queue will simply stay empty.

### 3. Deploy

```bash
bash cloudrun/deploy.sh
```

The first run is slow — Cloud Build clones HotClip and installs its native
dependencies (onnxruntime, ffmpeg-static, …). When it finishes you'll see the
**dashboard URL**. Open it: you should see the RUNNING badge and the per-platform
cards.

To use a different project/region/service or resources:

```bash
bash cloudrun/deploy.sh --project my-proj --region us-central1 --cpu 2 --memory 4Gi
```

### 4. Verify it's alive

```bash
# Tail logs (watch for [bootstrap], [clip], [panel], [scheduler] lines)
gcloud run services logs read shorts-autopilot --region us-central1 --follow

# Hit the health endpoint
curl -s "$(gcloud run services describe shorts-autopilot --region us-central1 --format='value(status.url)')/healthz"
# -> ok
```

---

## How it "runs on its own forever"

- **Always-on:** `--min-instances 1 --max-instances 1 --no-cpu-throttling` keeps
  exactly one instance running with CPU allocated at all times. The bot's watcher
  loop never exits; the dashboard serves on the same port Cloud Run health-checks.
- **Self-healing:** if the container exits (unexpected crash), Cloud Run starts a
  fresh instance to satisfy the minimum. State is in the bucket, so it resumes
  where it left off.
- **Durable state:** the SQLite queue, HotClip watch/export folders, and
  `links.txt` live on a Cloud Storage bucket mounted at `/data`. Editing
  `channels.txt` / `hashtags.txt` / `links.txt` in the bucket takes effect on the
  next tick — no redeploy needed.
- **Catch-up scheduling:** each platform publishes what its schedule owes; missed
  slots roll their credits forward, so delays never lose uploads.

---

## Day-to-day

**Update the code** (after changing `shorts_bot/`, schedules, or the Dockerfile):

```bash
git pull                 # or make your edits
bash cloudrun/deploy.sh  # rebuilds the image and rolls out the new revision
```

**Change schedules / volume / flags:** edit `cloudrun/autopilot.env.yaml`, then
`bash cloudrun/deploy.sh`. (Secrets are separate — update the files in
`cloudrun/secrets/` and re-run; the script pushes new secret versions.)

**Change channels / hashtags / add a manual link:** edit the file directly in the
bucket, e.g.:

```bash
gcloud storage cp channels.txt gs://YOUR_BUCKET/channels.txt
# or download, edit, upload:
gcloud storage cp gs://YOUR_BUCKET/links.txt ./links.txt
echo "https://youtu.be/XXXX" >> links.txt
gcloud storage cp links.txt gs://YOUR_BUCKET/links.txt
```

**Refresh Meta tokens (~every 60 days):** regenerate the long-lived token
locally (`python -m shorts_bot.instagram_token --facebook`), overwrite the file
in `cloudrun/secrets/`, and re-run `bash cloudrun/deploy.sh`.

---

## ⚠️ Known caveats (honest notes)

- **SQLite on Cloud Storage (gcsfuse):** Google doesn't recommend databases on
  gcsfuse. This bot writes little and is pinned to **one** instance (single
  writer), which works in practice, but an unclean shutdown *can* corrupt the DB.
  Mitigations already in place: single-instance pinning and automatic
  `jobs.backup-*.db` snapshots in the bucket (`cloudrun/backup_loop.sh`). To
  recover: stop the service, `cp` the newest backup over `jobs.db`, redeploy. If
  you ever need bulletproof DB durability, the clean upgrade is a **Cloud
  Filestore (NFS) volume** instead of the GCS bucket, or the **VM** path — I can
  wire either.
- **HotClip model cache:** models download on the first clip into the container's
  local disk. Because the instance stays warm they're reused; a cold start
  (rare) re-downloads them. Set `HOTCLIP_CACHE_DIR` under `/data` if you'd rather
  persist models in the bucket (slower inference, no re-download).
- **Clipping speed:** HotClip runs on CPU here. It works but is not fast; expect
  minutes per source. GPU on Cloud Run is possible but needs extra setup.
- **YouTube API quota:** still 100 `videos.insert` calls/day by default; the
  schedule targets 99. The channel's own daily cap is separate and may be lower.
- **Dashboard is public** (`--allow-unauthenticated`) like your GitHub Pages one.
  It shows no secrets, but to lock it down, drop that flag and front it with IAP,
  or grant `roles/run.invoker` to specific users only.

---

## Tear it down / pause

```bash
# Stop billing (keeps all state in the bucket):
gcloud run services update shorts-autopilot --region us-central1 --min-instances 0
# (this also turns off always-on CPU; re-deploy to resume)

# Delete everything (service + image + bucket):
gcloud run services delete shorts-autopilot --region us-central1
gcloud storage rm -r gs://YOUR_BUCKET
```

---

## Files in this folder

| File | Purpose |
|---|---|
| `Dockerfile` | Self-contained image: Python deps + ffmpeg + Node/pnpm + HotClip |
| `cloudbuild.yaml` | Cloud Build recipe used by `deploy.sh` |
| `entrypoint.sh` | Boots bootstrap + clipper loop + backup loop + the bot |
| `bootstrap.sh` | Seeds config, writes secret files, gates platforms by creds |
| `clip_loop.sh` | Runs HotClip's headless CLI over the watch folder |
| `backup_loop.sh` + `backup_db.py` | Periodic SQLite snapshots to the bucket |
| `autopilot.env.yaml` | Non-secret env (schedules, flags, paths) |
| `deploy.sh` | One-command: APIs, bucket, SA, secrets, build, deploy |
| `secrets/` | **You put credentials here (gitignored)** |
