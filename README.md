# Shorts Autopilot — HotClip ↔ Scheduler

> **[Open the live status panel](https://naserkhan07.github.io/Naveed/)** — dashboard, schedules, activity, and publication queue.

A fully automated Shorts/Reels pipeline with two halves:

1. **[HotClip](https://github.com/xixihhhh/hotclip)** (external, free, local) is the content
   factory: it transcribes, finds highlights, reframes to 9:16, removes silences/fillers,
   normalizes loudness, and burns **word-synced dynamic captions** with exact timing — plus
   cover JPGs and per-clip post copy.
2. **This bot** is the discovery + distribution brain: it watches YouTube channels for new
   uploads, feeds them to HotClip, harvests the finished clips into a SQLite queue, and
   publishes them to **YouTube, Instagram, and Facebook at your own per-day times** with
   configurable uploads per slot (33 per YouTube slot, 10 per Instagram/Facebook slot)
   and a fixed hashtag block appended to every upload.

```
channels.txt ──► unseen uploads from the last 4 days ──► hotclip-watch/
                                                          │ HotClip clips
hotclip-exports/ ──► intake ──► SQLite ready queue ──► platform-specific schedules
                                  up to 99 finished clips   YT 3 slots × 33
                                                          IG/FB 2 slots × 10 each
```

> **Rights first:** only queue videos you own or have explicit permission/license to
> download, edit, and republish. Clipping/reposting other creators' videos without
> permission violates their rights and platform policies. The bot requires
> `RIGHTS_ACKNOWLEDGED=true`.

## What runs automatically

- Every `CHANNEL_SCAN_INTERVAL_MINUTES` (local default 60; cloud workflow 30), yt-dlp
  checks up to 50 recent entries per creator in `channels.txt` (no YouTube API key).
- Fallback candidates need a usable upload date/timestamp within the last 4 days and must
  not have been processed before. Only this supplied creator list is scanned; undated or
  older sources are skipped rather than risk reposting stale content.
- Downloads are capped at 5 sources per scan. The bot aims to keep up to 99 finished,
  unpublished clips ready, matching the configured 99/day YouTube target. This is a buffer
  target, not a guarantee if recent sources or processing capacity are insufficient.
- HotClip (desktop app, or its headless `pnpm cli clip`) processes the watch folder and
  writes finished clips into its export directory: `mp4` + cover JPG + `.post.txt`
  + `clips.json` receipt. Only finished exports are enrolled in the SQLite queue.
- In the cloud workflow, already-queued clips are published first; new sources are then
  harvested and clipped, and their finished exports are queued for the next scheduled run.
- Each platform publishes only when its **own** schedule is due; per-platform timestamps
  prevent duplicate uploads. Missed or failed slots retain catch-up credits until content
  is available.
- A **status panel** runs at http://localhost:8000 for as long as the watcher does — full
  live view of discoveries, deliveries, queue, credits, and publishes (see section 6).

## 1. Install HotClip (the clipper)

1. Download the desktop app from the
   [latest release](https://github.com/xixihhhh/hotclip/releases/latest)
   (Windows installer/portable, macOS, Linux).
2. On first run, let it fetch its local models (ASR tiers, TransNetV2, etc.).
3. Open **Settings → Watch folder** and point it at this project's `hotclip-watch/`
   folder (default name; change with `HOTCLIP_WATCH_DIR`).
4. Point HotClip's **export/output directory** at this project's `hotclip-exports/`
   folder (change with `HOTCLIP_EXPORT_DIR`). Enable the caption style you like
   (e.g. Hormozi / keyword highlight / word pop) in its export scheme.
5. Leave HotClip running with “clips while you sleep” watch mode on.

Headless alternative: clone the HotClip repo and drive
`pnpm cli clip <video> --out hotclip-exports` yourself; the intake works the same.

## 2. Install this bot

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate`.

Also install FFmpeg (only `ffprobe` is needed now) —
`winget install Gyan.FFmpeg` / `brew install ffmpeg` / `sudo apt install ffmpeg`.

## 3. Connect your accounts

### YouTube

1. Google Cloud Console → project → enable **YouTube Data API v3** → OAuth consent screen →
   create a **Desktop app** OAuth client → save as `client_secret.json`.
2. Add your channel id to `channels.toml`:
   ```toml
   [youtube]
   channel_id = "UC_YOUR_CHANNEL_ID"
   ```
3. Run `python -m shorts_bot.youtube_auth` (or VS Code's *Authorize YouTube* config) and
   approve in the browser. The token lands in `youtube_token.json`.
4. `.env`: `UPLOAD_YOUTUBE=true`, `YOUTUBE_PRIVACY_STATUS=public`.

> **Current YouTube upload limits:** the default Data API project has a separate
> `videos.insert` bucket of **100 upload calls/day**. The cloud schedule is set to
> 3 slots × 33 uploads = **99/day**, under that API bucket. This is not a promise that
> the channel can upload 99/day: YouTube does not publish a fixed channel limit; it can
> vary by region and channel history. Advanced features provide a higher daily limit,
> not a published number. See [videos.insert quota](https://developers.google.com/youtube/v3/docs/videos/insert)
> and [YouTube daily upload limits](https://support.google.com/youtube/answer/10383400?hl=en).
> If you hit a channel
> limit, wait 24 hours; the bot keeps pending clips queued.
>
> **Public-upload audit:** API projects created after July 28, 2020 that have not passed
> YouTube's API compliance audit can have API-uploaded videos restricted to private.
> This audit is separate from OAuth consent and YouTube Studio feature eligibility; see
> the [YouTube video resource documentation](https://developers.google.com/youtube/v3/docs/videos).

### Instagram + Facebook

1. Business/Creator Instagram account connected to a Facebook Page, Meta app with content
   publishing.
2. Put the numeric Instagram Professional Account ID in `channels.toml` and configure:
   ```dotenv
   UPLOAD_INSTAGRAM=true
   INSTAGRAM_ACCESS_TOKEN=your_long_lived_meta_access_token
   INSTAGRAM_GRAPH_API_VERSION=v26.0
   UPLOAD_FACEBOOK=true
   FACEBOOK_PAGE_ID=your_numeric_page_id
   FACEBOOK_ACCESS_TOKEN=          # blank = reuse the Instagram token
   FACEBOOK_GRAPH_API_VERSION=v26.0
   ```
3. Generate/refresh the long-lived Page token with:
   ```powershell
   python -m shorts_bot.instagram_token --facebook
   ```

Meta long-lived tokens last ~60 days — re-run the helper when uploads start failing with
auth errors. Platform ceilings: Instagram ≤100 API posts/day, Facebook Page Reels ≤30/day —
both fit the 20/day-per-platform chart volume.

## 4. Add your channels

Edit `channels.txt` (one per line: `@handle`, URL, or channel ID). New uploads are found
and handed to HotClip automatically. Manual one-offs go in `links.txt` (one URL per line)
or via `shorts-cli URL...`.

## 5. Run

Everything (discovery, delivery, intake, scheduled publishing):

```powershell
.\.venv\Scripts\python.exe main.py
```

The watcher checks for new links/clips every 30 seconds and re-scans channels hourly.

Single passes and utilities:

```powershell
python -m shorts_bot.file_queue --once             # one full cycle, then exit
python -m shorts_bot.file_queue --scan-channels    # only deliver new channel uploads
python -m shorts_bot.file_queue --publish youtube  # publish what YouTube is owed now
python -m shorts_bot.status_panel                  # dashboard only (read-only view)
python -m shorts_bot.youtube_auth                  # (re)connect YouTube
python -m shorts_bot.instagram_token --facebook    # (re)create Meta long-lived token
python -m pytest -q                                # tests
python -m ruff check .                             # lint
```

For exact-to-the-minute publishing on a desktop, keep the watcher running — its 30-second
tick publishes within ~30s of each slot. Windows Task Scheduler/macOS cron can instead call
`--publish <platform>` at each slot.

## 6. Status panel — http://localhost:8000

The watcher always serves a live localhost dashboard (no setup, no extra install). While
`main.py` runs, open **http://localhost:8000** in any browser and it auto-refreshes every
5 seconds. Running fully on GitHub instead? The same dashboard is published online — see
section 9.

- **RUNNING / STALE badge** — driven by the watcher's database heartbeat; if the bot ever
  stops ticking the badge turns red, plus "last tick … ago" and uptime.
- **Per-platform cards** — uploads done today vs. what the schedule owes right now, slot
  chips (done / partial / due / upcoming), credits due right now, queue depth, total
  published, last upload time, next slot, and the per-slot pace.
- **Activity feed** — every discovery, HotClip delivery, queued clip, publish (with the
  live post link), upload limit, and error: *what happened, when, and where*.
- **Ready-buffer meter** — finished clips available to all enabled platforms versus the
  target, plus clips and sources still in preparation.
- **Publication queue** — every clip with a ✓ (linked) or … pending cell per platform.
- **Footer** — HotClip folders, hashtag count, channels, links pending, scan interval.

The address is printed when the watcher starts (`[panel] live status dashboard: …`). If
port 8000 is busy the next free port is used automatically. Configure or disable via
`STATUS_PANEL_PORT`, `STATUS_PANEL_HOST`, `STATUS_PANEL_ENABLED=false`.
A standalone read-only view against the same database also works without the watcher:
`python -m shorts_bot.status_panel` (it then honestly shows STALE until the watcher runs).

> GitHub Actions runs are ephemeral, so the panel applies to local/always-on runs; in the
> cloud use the Actions run log and the persisted queue instead.

## 7. Scheduling model

```dotenv
SCHEDULE_TIMEZONE=Asia/Kolkata
YOUTUBE_SCHEDULE_TIMES=mon=07:30,13:00,20:30;tue=07:30,13:00,20:30;wed=07:30,13:00,20:30;thu=07:30,13:00,20:30;fri=07:30,13:00,21:30;sat=08:30,13:30,21:30;sun=08:30,13:30,21:30
YOUTUBE_UPLOADS_PER_SLOT=33
INSTAGRAM_SCHEDULE_TIMES=mon=08:00,20:30;tue=08:00,19:30;wed=12:00,20:30;thu=08:00,19:30;fri=12:00,20:30;sat=10:00,19:30;sun=10:30,19:30
INSTAGRAM_UPLOADS_PER_SLOT=10
FACEBOOK_SCHEDULE_TIMES=mon=09:00,20:00;tue=09:00,19:30;wed=12:00,20:00;thu=09:00,19:30;fri=12:00,20:30;sat=10:00,19:30;sun=10:30,19:00
FACEBOOK_UPLOADS_PER_SLOT=10
```

- Grammar: plain `08:00,20:30` = every day; `mon=08:00;fri=08:00,21:30` = per weekday
  (unlisted weekdays get nothing; don't mix both forms). 24-hour local times.
- Each **passed** slot owes `*_UPLOADS_PER_SLOT` uploads of the oldest queued clips.
- Upload timestamps in `work/jobs.db` track what each platform already got today — so after
  a restart or overnight catch-up, credits stay exact (a missed slot publishes double later,
  not zero).
- Cloud defaults spread uploads across the configured windows: YouTube 3 slots/day ×
  **33 uploads** (= 99/day, below the default 100-call `videos.insert` API bucket),
  Instagram 2 slots/day × 10, Facebook 2 slots/day × 10. YouTube’s channel-level daily
  limit is separate and may be lower; lower the YouTube setting if the channel returns
  `uploadLimitExceeded`.
- If the queue runs dry, nothing is posted until HotClip produces more clips.

A platform with **no** `*_SCHEDULE_TIMES` is published immediately during intake instead.

## 8. Hashtags on every video

Every upload gets the ordered block from [`hashtags.txt`](hashtags.txt) appended
automatically — from the first tag down, as many as the platform accepts:

| Platform | Where they land | How many |
|---|---|---|
| YouTube | end of the description | up to **59** (+ the `#Shorts` the uploader adds itself = YouTube's 60 cap — beyond 60 YouTube ignores *every* hashtag) |
| Instagram | end of the caption | up to **30** (Instagram rejects captions with more) |
| Facebook | end of the Reel description | **the whole list** (no platform cap) |

- 207 tags ship in the box: 14 global reach tags, then every country A–Z.
- Tags already present in a clip's HotClip copy are never duplicated, and the
  existing copy always stays above the block ("from top till bottom").
- Character limits trim only trailing tags; at least the first tag always ships.
- Edit the file freely: only `#tokens` are read, everything else is a comment
  (never write `#example` words in header lines — they'd become live tags).
- Controls: `HASHTAGS_ENABLED` (default true), `HASHTAGS_FILE`,
  `HASHTAGS_YOUTUBE_MAX`/`HASHTAGS_INSTAGRAM_MAX`/`HASHTAGS_FACEBOOK_MAX`
  (0 = unlimited; values above a platform's real cap are rejected on startup).

## 9. Run everything on GitHub — no local PC needed

The autopilot runs on GitHub and wakes every 15 minutes (plus on pushes to `main` and
manual runs). Each cycle first publishes clips already prepared for platforms whose own
schedules are due, then harvests and clips recent unseen sources and queues finished work
for the next cycle. State (queue DB, watch folder, exports, HotClip itself) persists between
runs via GitHub caches, and a tiny monthly keepalive commit on the `autopilot-keepalive`
branch stops GitHub from disabling scheduled runs after 60 days of repo inactivity.

> Honest mechanics: GitHub Actions cron is best-effort, not an exact-minute scheduler;
> starts can be delayed or skipped. When a run does start, per-platform catch-up credits
> publish what is owed for that platform. The ready buffer reduces waiting on clipping,
> but cannot guarantee an exact upload time or a full buffer when recent sources or
> processing capacity are insufficient.

### Your dashboard is always online — no localhost needed

Every run rebuilds the same status panel as a **public GitHub Pages site**:
open **https://Naserkhan07.github.io/Naveed/** from anywhere (phone included) and you
get the identical dashboard — RUNNING/STALE badge, per-platform progress, the "what,
when, where" activity feed with links, and the queue — refreshed automatically after
every run (the header shows "data from … ago"). The page is static and public like the
repo: it never contains tokens or secrets, only clip titles, progress, and post links.

### One-time setup (~3 minutes, all in the GitHub web UI)

1. **Merge the PR** so `main` has the code.
2. **Add the workflow file**: repo → **Add file → Upload files** → upload
   `.github/workflows/autopilot.yml` onto `main` (the Arena GitHub App token isn't
   allowed to push workflow files; GitHub schedules also only run from the default
   branch — both solved by this one upload).
3. **Settings → Pages** → "Build and deployment" → Source: **GitHub Actions**.
4. **Settings → Secrets and variables → Actions** → add:
   `YOUTUBE_TOKEN_JSON` (contents of your local `youtube_token.json`),
   `INSTAGRAM_USER_ID`, `INSTAGRAM_ACCESS_TOKEN`, `FACEBOOK_PAGE_ID`,
   `FACEBOOK_ACCESS_TOKEN` (optional `YTDLP_COOKIES_TXT` — runners are datacenter IPs
   and YouTube may ask "confirm you're not a bot" without cookies).
5. **Actions tab → Autopilot → Run workflow** once. The dashboard goes live at the
   Pages URL on that first run; every 15-minute tick keeps everything moving.

Schedules, timezone, and per-slot volumes live in the workflow's `env:` block (edit
them like `.env`); `HOTCLIP_CLOUD: "true"` enables experimental cloud clipping via
HotClip's headless CLI (AGPL source cloned at runtime, never vendored here — failures
never block publishing the backlog). Meta long-lived tokens still expire ~60 days:
refresh them like before.

The local watcher path (sections 5–7) stays fully supported for anyone who prefers
an always-on PC; the localhost panel and the Pages dashboard are the same page.

## Configuration reference

| Variable | Default | Purpose |
|---|---:|---|
| `HOTCLIP_WATCH_DIR` | `hotclip-watch` | Folder HotClip watches for new source videos |
| `HOTCLIP_EXPORT_DIR` | `hotclip-exports` | Folder HotClip writes finished clips to |
| `HOTCLIP_MIN_CLIP_AGE_SECONDS` | `90` | Min file age before a clip counts as finished |
| `CHANNELS_FILE` | `channels.txt` | Channel list for automatic discovery |
| `CHANNEL_SCAN_MAX_VIDEOS` | `50` | Newest uploads inspected per channel per scan (1–50) |
| `CHANNEL_SCAN_INTERVAL_MINUTES` | `60` | How often channels are re-scanned (5–1440; cloud: 30) |
| `CHANNEL_FALLBACK_LOOKBACK_DAYS` | `4` | Maximum source-video age for creator-list fallback (1–30) |
| `CHANNEL_MAX_SOURCES_PER_SCAN` | `5` | New source downloads allowed in one scan (1–50) |
| `READY_CLIP_BUFFER_TARGET` | `99` | Target number of finished clips ready for all enabled platforms |
| `LINKS_FILE` | `links.txt` | Manual URL queue (processed first) |
| `LINKS_POLL_SECONDS` | `30` | Watcher tick (5–3600) |
| `WORK_DIR` / `DATABASE_PATH` | `work` / `work/jobs.db` | Staging and the SQLite queue |
| `SCHEDULE_TIMEZONE` | system local | IANA timezone for all schedule times |
| `*_SCHEDULE_TIMES` | empty | Per-platform slot times (daily or `day=` grammar) |
| `*_UPLOADS_PER_SLOT` | `1` | Uploads per slot per platform (1–50) |
| `YTDLP_COOKIES_FROM_BROWSER` | empty | Browser to read YouTube cookies from |
| `YTDLP_COOKIE_FILE` | empty | Netscape cookie file (Chrome DPAPI workaround) |
| `UPLOAD_YOUTUBE` | `false` | Enable YouTube publishing |
| `YOUTUBE_PRIVACY_STATUS` | `public` | Requested YouTube visibility |
| `YOUTUBE_TOKEN_FILE` | `youtube_token.json` | Local OAuth token |
| `CHANNEL_CONFIG_FILE` | `channels.toml` | Non-secret account IDs |
| `UPLOAD_INSTAGRAM` | `false` | Enable Instagram publishing |
| `INSTAGRAM_ACCESS_TOKEN` | empty | Long-lived Meta Page token |
| `INSTAGRAM_GRAPH_API_VERSION` | `v26.0` | Meta Graph API version |
| `UPLOAD_FACEBOOK` | `true` | Enable Facebook Page Reels publishing |
| `FACEBOOK_PAGE_ID` | empty | Numeric Page ID (or in `channels.toml`) |
| `FACEBOOK_ACCESS_TOKEN` | Instagram token | Long-lived Page token with `pages_manage_posts` |
| `FACEBOOK_LIMIT_COOLDOWN_HOURS` | `24` | Pause after a Meta spam-protection block |
| `YOUTUBE_DESCRIPTION_TARGET_CHARS` | `4200` | Max YouTube description length |
| `INSTAGRAM_CAPTION_TARGET_CHARS` | `2000` | Max Instagram caption length |
| `DELETE_UPLOADED_CLIPS` | `false` | Delete clip MP4 once published everywhere |
| `HASHTAGS_ENABLED` | `true` | Append the required hashtag block to every upload |
| `HASHTAGS_FILE` | `hashtags.txt` | Ordered hashtag list (only `#tokens` are read) |
| `HASHTAGS_YOUTUBE_MAX` | `59` | YouTube hashtag budget (+1 uploader `#Shorts` = 60 cap) |
| `HASHTAGS_INSTAGRAM_MAX` | `30` | Instagram's hard caption hashtag cap |
| `HASHTAGS_FACEBOOK_MAX` | `0` | 0 = unlimited; Facebook gets the full list |
| `STATUS_PANEL_ENABLED` | `true` | Serve the live localhost dashboard with the watcher |
| `STATUS_PANEL_HOST` | `127.0.0.1` | Dashboard bind address |
| `STATUS_PANEL_PORT` | `8000` | Dashboard port (auto-increments if busy) |
| `STATUS_STALE_AFTER_SECONDS` | `120` | Heartbeat age before the badge shows STALE |
| `RIGHTS_ACKNOWLEDGED` | `false` | Required rights confirmation |

## Project layout

- `main.py` — one-command launcher (watcher)
- `shorts_bot/file_queue.py` — discovery, HotClip delivery, intake, the watcher loop
- `shorts_bot/hotclip.py` — export-dir scanner (mp4 + cover + `.post.txt` + `clips.json`)
- `shorts_bot/publisher.py` — FIFO publishing with per-slot credits and Meta cooldowns
- `shorts_bot/hashtags.py` — per-platform hashtag block (caps, dedupe, char budgets)
- `shorts_bot/status_panel.py` + `status_page.html` — the localhost dashboard
  (heartbeat badge, per-platform cards, activity feed, queue; `python -m shorts_bot.status_panel`)
- `shorts_bot/pages_export.py` — exports the same dashboard statically for GitHub Pages
- `shorts_bot/scheduler.py` — per-weekday schedule grammar and credit math
- `shorts_bot/channels.py` — channel list parsing + yt-dlp latest-uploads discovery
- `shorts_bot/downloader.py` — yt-dlp source downloads (best quality, retries, cookies)
- `shorts_bot/youtube.py` / `instagram.py` / `facebook.py` — official-API uploaders
- `shorts_bot/db.py` — SQLite: channel memory + publication queue

## Troubleshooting

- **"Sign in to confirm you're not a bot" (YouTube download):** export Netscape cookies to
  `youtube-cookies.txt` and set `YTDLP_COOKIE_FILE=youtube-cookies.txt`, or use
  `YTDLP_COOKIES_FROM_BROWSER=firefox`.
- **YouTube `quotaExceeded`:** the default `videos.insert` bucket is 100 upload calls/day
  per API project; the cloud schedule targets 99/day. Check the project’s Quotas page if
  the API bucket is exhausted. The channel’s own daily upload cap is separate and variable;
  when YouTube returns `uploadLimitExceeded`, wait 24 hours and lower the schedule if needed.
  Clips remain queued.
- **Instagram/Facebook token expired:** re-run `python -m shorts_bot.instagram_token
  --facebook`; Meta long-lived tokens last ~60 days.
- **Clips are discovered but never publish:** check pending counts in the watcher log,
  confirm `UPLOAD_*` flags, schedule grammar, and that `SCHEDULE_TIMEZONE` matches intent.
- **A clip was skipped as "file missing":** its MP4 was moved/deleted outside the bot; the
  queue entry keeps retrying whenever the file returns, or delete the row in `work/jobs.db`.
