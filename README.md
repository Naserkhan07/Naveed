# Shorts Autopilot — HotClip ↔ Scheduler

A fully automated Shorts/Reels pipeline with two halves:

1. **[HotClip](https://github.com/xixihhhh/hotclip)** (external, free, local) is the content
   factory: it transcribes, finds highlights, reframes to 9:16, removes silences/fillers,
   normalizes loudness, and burns **word-synced dynamic captions** with exact timing — plus
   cover JPGs and per-clip post copy.
2. **This bot** is the discovery + distribution brain: it watches YouTube channels for new
   uploads, feeds them to HotClip, harvests the finished clips into a SQLite queue, and
   publishes them to **YouTube, Instagram, and Facebook at your own per-day times** with
   configurable uploads per slot (e.g. 7 per YouTube slot, 10 per Instagram/Facebook slot).

```
channels.txt ──► download new uploads ──► hotclip-watch/  (HotClip 24/7 watch folder)
                                                     │  (transcribe → cut → 9:16 + captions
                                                     │   + cover + post copy, all local)
hotclip-exports/ ──► intake scan ──► SQLite publication queue ──► scheduler
                                                     │        YT 3 slots × 7 uploads
                                                     │        IG 2 slots × 10 uploads
                                                     │        FB 2 slots × 10 uploads
                                                     └──── catch-up for missed slots
```

> **Rights first:** only queue videos you own or have explicit permission/license to
> download, edit, and republish. Clipping/reposting other creators' videos without
> permission violates their rights and platform policies. The bot requires
> `RIGHTS_ACKNOWLEDGED=true`.

## What runs automatically

- Every `CHANNEL_SCAN_INTERVAL_MINUTES` (default 60), the newest uploads of every channel in
  `channels.txt` are discovered via yt-dlp metadata (no YouTube API key).
- Each new video is downloaded at best quality and dropped straight into HotClip's watch
  folder; a (channel, video) pair is never delivered twice (SQLite memory).
- HotClip (desktop app, or its headless `pnpm cli clip`) processes the watch folder 24/7
  and writes finished clips into its export directory: `mp4` + cover JPG + `.post.txt`
  + `clips.json` receipt.
- The watcher picks finished clips from the export directory (never half-written files),
  reads their copy, and queues them for publishing.
- At each platform's configured slot times, the scheduler publishes the oldest queued
  clips — `YOUTUBE_UPLOADS_PER_SLOT` per slot, etc. — with per-clip upload timestamps.
- A slot that had nothing ready (or failed) keeps its credit: the scheduler **catches up**
  automatically as soon as clips exist, then returns to the normal cadence.

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

> **Quota reality check (important):** the default YouTube Data API quota is
> 10,000 units/day and one upload costs 1,600 units → **~6 uploads per day**. The reference
> chart volume (21/day) needs a [quota increase request]
> (https://support.google.com/youtube/contact/yt_api_form). Until approved, extra uploads
> fail with quota errors and simply catch up on following days; the bot prints this warning
> at startup.

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
python -m shorts_bot.youtube_auth                  # (re)connect YouTube
python -m shorts_bot.instagram_token --facebook    # (re)create Meta long-lived token
python -m pytest -q                                # tests
python -m ruff check .                             # lint
```

For exact-to-the-minute publishing on a desktop, keep the watcher running — its 30-second
tick publishes within ~30s of each slot. Windows Task Scheduler/macOS cron can instead call
`--publish <platform>` at each slot.

## 6. Scheduling model

```dotenv
SCHEDULE_TIMEZONE=Asia/Kolkata
YOUTUBE_SCHEDULE_TIMES=mon=07:30,13:00,20:30;tue=07:30,13:00,20:30;wed=07:30,13:00,20:30;thu=07:30,13:00,20:30;fri=07:30,13:00,21:30;sat=08:30,13:30,21:30;sun=08:30,13:30,21:30
YOUTUBE_UPLOADS_PER_SLOT=7
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
- Shipped defaults mirror your reference charts (slot time = middle of each suggested
  window): YouTube 3 slots/day × 7, Instagram 2 slots/day × 10, Facebook 2 slots/day × 10.
- If the queue runs dry, nothing is posted until HotClip produces more clips.

A platform with **no** `*_SCHEDULE_TIMES` is published immediately during intake instead.

## Configuration reference

| Variable | Default | Purpose |
|---|---:|---|
| `HOTCLIP_WATCH_DIR` | `hotclip-watch` | Folder HotClip watches for new source videos |
| `HOTCLIP_EXPORT_DIR` | `hotclip-exports` | Folder HotClip writes finished clips to |
| `HOTCLIP_MIN_CLIP_AGE_SECONDS` | `90` | Min file age before a clip counts as finished |
| `CHANNELS_FILE` | `channels.txt` | Channel list for automatic discovery |
| `CHANNEL_SCAN_MAX_VIDEOS` | `5` | Newest uploads inspected per channel per scan (1–50) |
| `CHANNEL_SCAN_INTERVAL_MINUTES` | `60` | How often channels are re-scanned (5–1440) |
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
| `RIGHTS_ACKNOWLEDGED` | `false` | Required rights confirmation |

## Project layout

- `main.py` — one-command launcher (watcher)
- `shorts_bot/file_queue.py` — discovery, HotClip delivery, intake, the watcher loop
- `shorts_bot/hotclip.py` — export-dir scanner (mp4 + cover + `.post.txt` + `clips.json`)
- `shorts_bot/publisher.py` — FIFO publishing with per-slot credits and Meta cooldowns
- `shorts_bot/scheduler.py` — per-weekday schedule grammar and credit math
- `shorts_bot/channels.py` — channel list parsing + yt-dlp latest-uploads discovery
- `shorts_bot/downloader.py` — yt-dlp source downloads (best quality, retries, cookies)
- `shorts_bot/youtube.py` / `instagram.py` / `facebook.py` — official-API uploaders
- `shorts_bot/db.py` — SQLite: channel memory + publication queue

## Troubleshooting

- **"Sign in to confirm you're not a bot" (YouTube download):** export Netscape cookies to
  `youtube-cookies.txt` and set `YTDLP_COOKIE_FILE=youtube-cookies.txt`, or use
  `YTDLP_COOKIES_FROM_BROWSER=firefox`.
- **YouTube `quotaExceeded`:** expected beyond ~6 uploads/day on the default quota; clips
  stay queued and publish on later days. Request a quota increase for 21/day.
- **Instagram/Facebook token expired:** re-run `python -m shorts_bot.instagram_token
  --facebook`; Meta long-lived tokens last ~60 days.
- **Clips are discovered but never publish:** check pending counts in the watcher log,
  confirm `UPLOAD_*` flags, schedule grammar, and that `SCHEDULE_TIMEZONE` matches intent.
- **A clip was skipped as "file missing":** its MP4 was moved/deleted outside the bot; the
  queue entry keeps retrying whenever the file returns, or delete the row in `work/jobs.db`.
