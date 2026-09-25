# Local Groq Shorts + Instagram Reels Automation

This project runs entirely on your laptop from VS Code. There is no separate web-server or Docker installation requirement.

Add authorized YouTube links to `links.txt` — or list your channels in `channels.txt` and the bot discovers their latest uploads itself. The program downloads each video, removes its link after a successful download, divides the usable timeline into consecutive 20–30 second clips based on the video's duration, generates detailed AI metadata and thumbnails, renders vertical Shorts with word-by-word burned-in captions, and publishes each one to YouTube, Instagram, and Facebook — immediately, or on your own per-platform schedule.

> **Only process videos you own or have explicit permission/license to download, edit, and republish.** A publicly viewable video is not automatically licensed for reuse. The program requires `RIGHTS_ACKNOWLEDGED=true`.

## What the local workflow does

1. Watches the local `links.txt` file and, on a configurable interval, scans the channels listed in `channels.txt` for brand-new uploads.
2. Downloads one authorized YouTube video at a time using the Python API equivalent of `yt-dlp -f "bestvideo+bestaudio" URL`, then remuxes those streams without source re-encoding.
3. Removes every matching URL line immediately after the video downloads successfully (channel-discovered videos are remembered in SQLite instead).
4. Records the URL and job ID in `work/downloaded-links.log`.
5. Extracts speech audio locally with FFmpeg.
6. Uses Groq `whisper-large-v3-turbo` for timestamped **word-level** transcription.
7. In `full_coverage` mode, calculates the clip count from source duration and covers the timeline with consecutive 20–30 second sections.
8. Generates a detailed YouTube title/description and a separate Instagram caption for every clip.
9. Renders every section as an H.264/AAC MP4 at the configured native-resolution policy.
10. When enabled, temporarily hosts selected clips and runs API.market Real-ESRGAN before upload.
11. Burns **word-synced karaoke captions** into the final clip (all caps, cyan/yellow active-word highlight, Anton or bundled bold font).
12. Generates a JPEG thumbnail from the final (enhanced, captioned, or original) clip.
13. Uploads every result as a public YouTube Short, Instagram Reel, and Facebook Page Reel — right away for platforms without a schedule, or from a FIFO queue at each platform's configured times.

A downloaded URL is removed before AI/render/upload starts. If a later stage fails, the URL remains in `work/downloaded-links.log`; copy it back into `links.txt` when you want to retry.

## Local files

- `main.py` — easiest way to start the watcher from VS Code
- `links.txt` — paste one YouTube URL per line
- `channels.txt` — one channel per line whose new uploads are auto-queued
- `channels.toml` — non-secret YouTube and Instagram account IDs
- `fonts/` — caption fonts (drop `Anton-Regular.ttf` here for the signature look)
- `.env` — local API keys and tokens; never committed
- `client_secret.json` — Google OAuth desktop client; never committed
- `youtube_token.json` — generated Google OAuth token; never committed
- `work/jobs.db` — local job history, channel memory, and per-platform upload queue
- `work/jobs/<job-id>/short-001.mp4`, `short-002.mp4`, … — rendered Shorts/Reels
- `work/jobs/<job-id>/short-001-subtitled.mp4`, … — captioned final clips
- `work/jobs/<job-id>/thumbnail-001.jpg`, `thumbnail-002.jpg`, … — generated covers
- `work/jobs/<job-id>/transcript-words.json` — cached caption timings (saves re-transcription)
- `work/downloaded-links.log` — downloaded URL audit history

## Do not save account passwords

The program intentionally does not accept YouTube, Google, Facebook, or Instagram passwords.

- YouTube upload uses Google's official OAuth browser authorization.
- Instagram upload uses a Meta access token for a Professional account.
- `channels.toml` contains only non-secret IDs.
- Secret values stay in the gitignored `.env` and OAuth files on your laptop.

## 1. Install local requirements

Install:

- Python 3.11, 3.12, or 3.13 (Python 3.14 is not supported by the Chrome PO-token provider)
- VS Code
- VS Code Python extension
- FFmpeg and ffprobe

The Python installation command also installs the Deno JavaScript runtime and `yt-dlp-ejs` inside
`.venv`. Current YouTube player challenges require these components for normal format availability;
no separate global Deno installation is needed.

### Windows FFmpeg

Using Winget:

```powershell
winget install Gyan.FFmpeg
```

Restart VS Code after installation and verify:

```powershell
ffmpeg -version
ffprobe -version
```

### macOS

```bash
brew install ffmpeg
```

### Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install ffmpeg
```

## 2. Open and install in VS Code

Open the repository folder in VS Code.

### Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

If PowerShell blocks activation, either select `.venv` through **Python: Select Interpreter**, or temporarily allow the current process:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.venv\Scripts\Activate.ps1
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

In VS Code, select the `.venv` interpreter using **Python: Select Interpreter**.

A VS Code task named **Install project dependencies** is also included.

## 3. Configure Groq locally

Edit `.env`:

```dotenv
GROQ_API_KEY=gsk_your_key
GROQ_MODEL=qwen/qwen3.6-27b
GROQ_FALLBACK_MODEL=qwen/qwen3.6-27b
GROQ_TRANSCRIPTION_MODEL=whisper-large-v3-turbo
GROQ_MAX_TRANSCRIPT_CHARS=8000
GROQ_METADATA_DELAY_SECONDS=30
YOUTUBE_DESCRIPTION_TARGET_CHARS=4200
INSTAGRAM_CAPTION_TARGET_CHARS=2000
INSTAGRAM_HASHTAGS_FILE=instagram_hashtags.txt
INSTAGRAM_CAPTION_ROTATION_FILE=instagram_captions.txt
INSTAGRAM_CAPTION_MENTIONS=@wzz.unfiltered @precious.tulip1
CLIP_DURATION_SECONDS=30
SHORTS_SELECTION_MODE=full_coverage
MAX_SHORTS_PER_VIDEO=0
VIDEO_LAYOUT=fit_black
VIDEO_ALLOW_UPSCALE=false
VIDEO_CRF=18
VIDEO_PRESET=slow
RIGHTS_ACKNOWLEDGED=true
```

`MAX_SHORTS_PER_VIDEO=0` means automatic duration-based counting. A 10-minute source produces 20
30-second clips. The workflow distributes unusually short remainders where possible; the unavoidable
platform ceiling is 100 clips per source because both YouTube and Instagram limit automated daily
publishing. Set a positive value only when you intentionally want a lower cap.

The source is downloaded and transcribed once. After that, clips stream through the workflow one at
a time: generate metadata for clip 1 → render clip 1 → upload clip 1 to both platforms → continue to
clip 2. It never waits for metadata or rendering of the entire batch before the first upload.

No OpenAI API key or OpenAI service is used. The automatic workflow keeps Groq as its hosted AI
backend so no model is downloaded to the laptop. Kaggle notebooks are useful for interactive or
batch GPU experiments, but their sessions are temporary and do not provide a dependable always-on
API for this unattended local queue; using a tunneled notebook would stop whenever the Kaggle
session ends.

Detailed metadata is generated in a separate paced Groq request for every selected clip. The
configured 4,200-character YouTube and 2,000-character Instagram values are maximum targets, not
forced filler lengths. Metadata expands when the transcript contains enough factual information and
stays shorter when a 30-second clip cannot support more detail. One automatic repair request runs for
very short responses, but the clip is never blocked merely for being concise. Instagram accepts at
most 30
hashtags per caption, so the entire supplied hashtag list cannot appear on every Reel. The full
editable pool is stored in `instagram_hashtags.txt`; groups of 30 unique tags rotate across the Reel
batch while every caption remains within the platform limit. Instagram captions alternate globally
between the non-empty lines in `instagram_captions.txt`. Every new or pending Instagram Reel caption
starts with the handles in `INSTAGRAM_CAPTION_MENTIONS` (by default,
`@wzz.unfiltered @precious.tulip1`) without duplicating them during retries.

## 4. Configure local account IDs

Edit `channels.toml`:

```toml
[youtube]
channel_id = "UC_YOUR_CHANNEL_ID"

[instagram]
user_id = "YOUR_NUMERIC_INSTAGRAM_PROFESSIONAL_ACCOUNT_ID"
```

Do not put passwords or access tokens in this file.

## 5. Authorize YouTube from your laptop

1. Open Google Cloud Console.
2. Create/select a project and enable **YouTube Data API v3**.
3. Configure the OAuth consent screen.
4. Create an OAuth client with application type **Desktop app**.
5. Download the file and save it in this project as `client_secret.json`.
6. Run in the VS Code terminal:

```bash
python -m shorts_bot.youtube_auth
```

Alternatively, select **Authorize YouTube** in VS Code's Run and Debug menu.

Your browser opens Google's official consent screen. The result is saved locally as `youtube_token.json`. The program verifies that the authorized channel matches `channels.toml` before uploading.

Configure `.env`:

```dotenv
UPLOAD_YOUTUBE=true
YOUTUBE_PRIVACY_STATUS=public
YOUTUBE_CLIENT_SECRETS_FILE=client_secret.json
YOUTUBE_TOKEN_FILE=youtube_token.json
```

YouTube may lock uploads from an unaudited Google API project to private even when `public` is requested. The program cannot bypass that platform restriction.

## 6. Configure Instagram locally

Instagram publishing requires a Business or Creator account and a Meta app configured for Instagram content publishing/Facebook Login for Business.

Place the numeric Instagram Professional Account ID in `channels.toml`, and put the access token only in `.env`:

```dotenv
UPLOAD_INSTAGRAM=true
INSTAGRAM_ACCESS_TOKEN=your_long_lived_meta_access_token
INSTAGRAM_GRAPH_API_VERSION=v26.0
```

The local program:

1. Creates a resumable `REELS` media container.
2. Uploads the local MP4 to Meta's returned upload URL.
3. Waits for processing to finish.
4. Publishes the container.
5. Retrieves the Reel permalink.
6. Uses `share_to_feed=true`.

Meta controls final visibility and can reject expired tokens, missing permissions, unsupported accounts, or policy-violating media.

Graph API Explorer initially issues a short-lived User token. To avoid daily expiry failures, generate
a fresh **User Token** there, then exchange it locally for a long-lived User token and the connected
Page token. Find the App ID and App Secret under Meta App Dashboard → App settings → Basic, then run:

```powershell
python -m shorts_bot.instagram_token
```

The command prompts privately for the App ID, App Secret, and temporary User token, finds the Page
connected to `splitzz.isodope`, and writes only its long-lived Page token to `.env`. It never stores
the App Secret or temporary User token.

### Facebook Reels publishing

The bot publishes every rendered clip directly to your Facebook Page as a public Reel. Facebook
publishing is enabled by default (`UPLOAD_FACEBOOK=true`), so the bot uploads to Facebook
automatically every time it runs. It needs your numeric `FACEBOOK_PAGE_ID` (in `.env` or
`channels.toml`) and a long-lived Page token with `pages_manage_posts`; leave
`FACEBOOK_ACCESS_TOKEN` blank to reuse `INSTAGRAM_ACCESS_TOKEN`. To set everything up in one step,
run:

```powershell
python -m shorts_bot.instagram_token --facebook
```

The helper validates those permissions and confirms that Meta returns a `CREATE_CONTENT`/Content
Page task before automatically saving `FACEBOOK_PAGE_ID`, `FACEBOOK_ACCESS_TOKEN`,
`FACEBOOK_GRAPH_API_VERSION`, and `UPLOAD_FACEBOOK=true` in `.env`.
Facebook publishing initializes a Reel session, uploads the local MP4 to `rupload.facebook.com`,
publishes it publicly, waits for processing, and stores the Reel ID and URL. Meta limits API-published
Page Reels to 30 in a rolling 24-hour period; excess clips remain pending for automatic retry.

## 7. Optional API.market Real-ESRGAN enhancement

API.market requires `video_path` to be a direct public HTTPS URL; it cannot read a Windows file path.
The workflow therefore uploads each selected local clip temporarily to Cloudinary, submits that URL
to API.market, polls the asynchronous prediction, downloads the enhanced MP4, deletes the temporary
Cloudinary input, generates the thumbnail from the enhanced result, and only then uploads to YouTube,
Instagram, and Facebook.

Any key visible in a screenshot or chat is compromised. Revoke it and put only the replacement in
the gitignored `.env` file. Create a Cloudinary account and configure:

```dotenv
VIDEO_ENHANCER=api_market
APIMARKET_API_KEY=YOUR_NEW_ROTATED_KEY
APIMARKET_MODEL=RealESRGAN_x4plus
APIMARKET_RESOLUTION=FHD
APIMARKET_MAX_CLIPS=5
APIMARKET_TIMEOUT_SECONDS=1200

CLOUDINARY_CLOUD_NAME=YOUR_CLOUD_NAME
CLOUDINARY_API_KEY=YOUR_CLOUDINARY_API_KEY
CLOUDINARY_API_SECRET=YOUR_CLOUDINARY_API_SECRET
```

`APIMARKET_MAX_CLIPS=5` enhances only clips 1–5 as selected for the initial trial. Set it to `0` only
when the account has enough paid units to enhance every clip. Each enhanced clip consumes a separate
prediction. The temporary hosting object is deleted in cleanup even when enhancement fails.

## 8. Add YouTube links

Open `links.txt` in VS Code and add one URL per line:

```text
https://www.youtube.com/watch?v=VIDEO_ONE
https://youtu.be/VIDEO_TWO
https://youtube.com/shorts/VIDEO_THREE
```

Save the file. Blank lines and comments beginning with `#` are preserved.

## 8a. Word-by-word captions

Every clip gets burned-in, viral-style subtitles automatically, synced to the actual speech
(word-level Whisper timestamps):

- All caps, very bold type (Anton when present, bundled DejaVu Sans Bold otherwise)
- Currently spoken word highlighted in **cyan or yellow** (alternating per line), rest white
- Thick black outline, dark drop shadow, and a soft glow for readability
- 4 words per caption line (configurable), centered at ~44% of the frame height
- A subtle pop when each caption line appears, plus a slight size emphasis on the active word

The caption timings are cached in `work/jobs/<job-id>/transcript-words.json`, so resuming a job
never re-pays the transcription cost. The captions are burned **after** the optional AI
enhancement, so text always stays crisp. Thumbnails are taken from the captioned clip.

For the exact reference look, download **Anton** (`Anton-Regular.ttf`, SIL OFL) from
<https://fonts.google.com/specimen/Anton> and place it in `fonts/` — see `fonts/README.md`.
If it is missing, the bundled DejaVu Sans Bold is used so captions always render.

```dotenv
SUBTITLES_ENABLED=true
SUBTITLES_WORDS_PER_SCREEN=4
SUBTITLES_FONT_SIZE=62
SUBTITLES_POSITION_Y=850
SUBTITLES_FONT_NAME=Anton
SUBTITLES_FONT_DIR=fonts
```

Set `SUBTITLES_ENABLED=false` for clean clips without captions.

## 8b. Automatic channel discovery

Instead of pasting links manually, list source channels in `channels.txt` — one per line:

```text
@YourChannel
https://www.youtube.com/@AnotherChannel
UCxxxxxxxxxxxxxxxxxxxxxx
```

While watching (and on every `--once` / `--scan-channels` run), the bot reads each channel's
newest uploads via yt-dlp metadata (no download, no YouTube API key) and queues the ones it has
never seen. Every (channel, video) pair is remembered in `work/jobs.db`, so each video is
processed exactly once, oldest-new first. Channel failures (network, renamed handle) are logged
and never stop the rest of the scan.

```dotenv
CHANNELS_FILE=channels.txt
CHANNEL_SCAN_MAX_VIDEOS=5        # newest N uploads inspected per channel per scan
CHANNEL_SCAN_INTERVAL_MINUTES=60 # how often the watcher re-scans
```

`links.txt` entries are still processed as well, always before pending-upload retries.

> Only add channels you own or have explicit permission/license to repurpose.

## 8c. Scheduled uploads per platform

Give any platform its own upload times and the bot separates **production** from **publishing**:

```dotenv
SCHEDULE_TIMEZONE=Asia/Kolkata
YOUTUBE_SCHEDULE_TIMES=09:30,18:00
INSTAGRAM_SCHEDULE_TIMES=13:00,20:00
FACEBOOK_SCHEDULE_TIMES=11:00,17:00
```

- Platforms **without** times upload immediately after rendering (previous behavior).
- Platforms **with** times render clips into a first-in-first-out pending queue; each passed
  slot uploads the next pending clip to that platform only.
- **Catch-up**: a slot that had nothing ready (or was missed) keeps its credit. As soon as a
  clip is ready, one credit publishes one clip until the schedule is back on track — the
  per-clip upload timestamps in `work/jobs.db` make credits correct even across restarts and
  separate cron runs.
- The long-running watcher checks due slots every cycle; serverless schedulers only need
  `python -m shorts_bot.file_queue --publish youtube|instagram|facebook`.

Respect platform ceilings when choosing slot counts: YouTube's default API quota fits ~6
uploads/day, Instagram ~100/day, Facebook Page Reels ~30/day.

## 9. Start locally from VS Code

### Easiest method

Open **Run and Debug**, select **Run local Shorts automation**, and press **F5**.

### VS Code terminal

```powershell
.\.venv\Scripts\python.exe main.py
```

That single command starts the queue bot. The terminal prints:

```text
Local watcher started. Add YouTube URLs to links.txt. Press Ctrl+C to stop.
```

`Ctrl+C` stops the watcher cleanly. The watcher checks `links.txt` every 30 seconds and processes
jobs sequentially.

### Process the current file once

```bash
python -m shorts_bot.file_queue --once
```

Or select **Process links.txt once** in VS Code's Run and Debug menu.

If a downloaded job later fails during AI, rendering, or upload, retry it without downloading again:

```powershell
.\.venv\Scripts\python.exe main.py --resume JOB_ID
```

A job created before multi-clip support keeps its already-published single Short when resumed. To
reuse its downloaded source and create a new multi-clip batch, run:

```bash
python -m shorts_bot.file_queue --expand JOB_ID
```

## Automatic credential checks, retries, and pending folders

At startup and every `CREDENTIAL_CHECK_MINUTES`, the watcher reloads `.env`, verifies Groq models,
refreshes YouTube OAuth when needed, checks the authorized YouTube channel and Instagram Page token,
and validates Cloudinary when enhancement is enabled. Retired Groq models automatically migrate to
an active non-OpenAI Qwen model.

A startup authentication failure or an official publishing limit blocks only that destination while
other platforms, metadata, enhancement, rendering, and thumbnails continue. An individual YouTube
or Instagram clip upload failure no longer skips the rest of that platform's batch: the failed clip
remains pending and the bot immediately attempts the next generated clip. Instagram binary uploads
automatically retry temporary HTTP 408/5xx responses with exponential backoff before leaving that
clip pending. At the end, the workflow creates one ordinary folder under
`work/pending_uploads/` containing:

- `videos/` with every generated MP4
- `thumbnails/` with every cover image
- `metadata.json` with titles, descriptions, captions, IDs, URLs, and pending status
- `upload-manifest.csv` for manual upload tracking
- a short README

Configure:

```dotenv
ARCHIVE_ON_UPLOAD_LIMIT=true
ARCHIVE_DIR=work/pending_uploads
OPEN_UPLOAD_LIMIT_FOLDER=true
CREDENTIAL_CHECK_MINUTES=60
PENDING_RETRY_JOBS_PER_CYCLE=3
```

On Windows, Explorer opens the completed folder automatically. No ZIP extraction is needed. The
watcher always processes new URLs from `links.txt` before old pending uploads. When the URL queue is
idle, it reloads changed credentials and retries a bounded number of pending jobs each cycle; clips
already uploaded to a destination are skipped. A pending-count report explains exactly how many
YouTube and Instagram uploads remain.

### Personal messaging accounts are not used for storage

The workflow intentionally does not automate personal Instagram DMs or personal WhatsApp Web. A
phone number alone cannot authorize official WhatsApp automation; official sending requires a
WhatsApp Business Cloud API account, Phone Number ID, access token, and recipient opt-in. Pending
videos therefore remain in the ordinary local folder above. If the project is inside a OneDrive
Documents directory, that folder can also sync to the OneDrive mobile app.

## One-off URL command

To process URLs without editing `links.txt`:

```bash
shorts-cli --platform both "https://youtu.be/VIDEO_ID"
```

Platform overrides:

```bash
shorts-cli --platform youtube "https://youtu.be/VIDEO_ID"
shorts-cli --platform instagram "https://youtu.be/VIDEO_ID"
shorts-cli --platform none "https://youtu.be/VIDEO_ID"
```

`--platform none` creates the MP4 locally without uploading it.

## Hands-free deployment on GitHub Actions

The repository ships a complete serverless deployment under `.github/workflows/`. Everything
runs on GitHub's free runner minutes (public repos); no laptop or VPS required.

| Workflow | Trigger | What it does |
|---|---|---|
| **produce** | every 3 hours + manual | Scans channels, processes `links.txt`, renders captioned clips, retries pending uploads, runs any schedule-due uploads |
| **publish-youtube** | 04:00 & 12:30 UTC (09:30 & 18:00 IST) + manual | Publishes the next queued Short to YouTube |
| **publish-instagram** | 07:30 & 14:30 UTC (13:00 & 20:00 IST) + manual | Publishes the next queued Reel to Instagram |
| **publish-facebook** | 05:30 & 11:30 UTC (11:00 & 17:00 IST) + manual | Publishes the next queued Reel to Facebook |
| **intake-link** | issue opened with the link form | Appends your URL to `links.txt` and closes the issue |

Queue state (`bot-state/jobs.db`, `links.txt`, `channels.txt`) is committed back to `main` by
each run; rendered-but-unpublished clips travel between runs as a short-lived `pending-clips`
workflow artifact. All four bot workflows share one concurrency group, so runs queue instead of
racing the state file. YouTube Google OAuth, Meta tokens, and any cookie file live only in
Secrets — they are written to temp files at runtime and never committed.

### Set your upload times

Times exist in **two** places that must agree (cron is static YAML, credit math uses the
variable):

1. **Repository variable** — Settings → Secrets and variables → Actions → Variables, e.g.
   `YOUTUBE_SCHEDULE_TIMES = 09:30,18:00` (interpreted in `SCHEDULE_TIMEZONE`, default
   `Asia/Kolkata`).
2. **Workflow cron lines** (UTC!) in `.github/workflows/publish-*.yml`. The shipped crons match
   the default example: `30 12 * * *` = 18:00 IST.

GitHub's free-tier cron can fire a few minutes (occasionally ~30) late; uploads land within
that window of the configured time.

### Submit a link from your phone

Open **Issues → New issue → 📥 Queue a video link**, paste the YouTube URL, submit. The
intake workflow (owner-only, URL-validated) appends it to `links.txt` and it is processed on
the next producer run. `channels.txt` edits work the same way through the normal GitHub editor.

### Required secrets (Settings → Secrets and variables → Actions)

| Secret | Content |
|---|---|
| `GROQ_API_KEY` | Groq API key |
| `YOUTUBE_CLIENT_SECRET_JSON` | Full contents of `client_secret.json` |
| `YOUTUBE_TOKEN_JSON` | Full contents of `youtube_token.json` |
| `INSTAGRAM_ACCESS_TOKEN` | Long-lived Meta token (also reused for Facebook when `FACEBOOK_ACCESS_TOKEN` is unset) |
| `FACEBOOK_PAGE_ID` | Numeric Facebook Page ID |
| `FACEBOOK_ACCESS_TOKEN` | Long-lived Page token with `pages_manage_posts` (can be identical to the Instagram token) |
| `YTDLP_COOKIES` | *(optional but recommended)* Netscape cookie export for YouTube downloads from datacenter IPs |

Useful Variables: `YOUTUBE_SCHEDULE_TIMES`, `INSTAGRAM_SCHEDULE_TIMES`, `FACEBOOK_SCHEDULE_TIMES`
(comma-separated local times), `SCHEDULE_TIMEZONE` (default `Asia/Kolkata`), `SUBTITLES_ENABLED`
(default `true`), `YOUTUBE_PRIVACY_STATUS` (default `public`), `CHANNEL_SCAN_MAX_VIDEOS`
(default `5`).

### Known cloud limitations

- **Timing precision**: GitHub cron is approximate. If to-the-minute timing ever becomes
  critical, the same `--publish` commands run exactly on time under a VPS/Pi cron or systemd
  timer instead.
- **YouTube download bot-checks**: datacenter IPs are more often challenged; add the
  `YTDLP_COOKIES` secret and YouTube may still occasionally refuse a run — the scheduler's
  catch-up credits recover automatically on the next run.
- **Token hygiene**: Meta tokens still need rotation (~60 days) and the YouTube OAuth refresh
  token is long-lived but must remain valid; if a run reports `invalid_grant`, re-run
  `python -m shorts_bot.youtube_auth` locally and refresh the `YOUTUBE_TOKEN_JSON` secret.
  Any locally-refreshed YouTube token should be copied back into the same secret.

## Configuration reference

| Variable | Default | Purpose |
|---|---:|---|
| `GROQ_API_KEY` | empty | Required Groq API key |
| `GROQ_MODEL` | `qwen/qwen3.6-27b` | Active non-OpenAI Groq highlight/metadata model |
| `GROQ_FALLBACK_MODEL` | `qwen/qwen3.6-27b` | Non-OpenAI Groq fallback model |
| `GROQ_TRANSCRIPTION_MODEL` | `whisper-large-v3-turbo` | Timestamped transcription |
| `GROQ_MAX_TRANSCRIPT_CHARS` | `8000` | Sampled planning transcript budget |
| `GROQ_METADATA_DELAY_SECONDS` | `30` | Pacing between detailed per-clip metadata calls |
| `YOUTUBE_DESCRIPTION_TARGET_CHARS` | `4200` | Target detailed description length, max 4500 |
| `INSTAGRAM_CAPTION_TARGET_CHARS` | `2000` | Caption limit including mentions and hashtags, max 2000 |
| `INSTAGRAM_HASHTAGS_FILE` | `instagram_hashtags.txt` | Editable pool rotated in groups of 30 |
| `INSTAGRAM_CAPTION_ROTATION_FILE` | `instagram_captions.txt` | Exact Instagram caption bodies alternated globally Reel by Reel |
| `INSTAGRAM_CAPTION_MENTIONS` | `@wzz.unfiltered @precious.tulip1` | Handles placed at the start of every pending/new Reel caption |
| `YTDLP_COOKIES_FROM_BROWSER` | empty | Direct browser extraction (Firefox recommended on Windows) |
| `YTDLP_BROWSER_PROFILE` | empty | Optional browser profile name/path |
| `YTDLP_COOKIE_FILE` | empty | Netscape cookie export for Chrome DPAPI workaround |
| `CHANNEL_CONFIG_FILE` | `channels.toml` | Local non-secret account IDs |
| `UPLOAD_YOUTUBE` | `false` | Enable YouTube publishing |
| `YOUTUBE_PRIVACY_STATUS` | `public` | Requested YouTube visibility |
| `YOUTUBE_TOKEN_FILE` | `youtube_token.json` | Local OAuth token |
| `UPLOAD_INSTAGRAM` | `false` | Enable Instagram publishing |
| `INSTAGRAM_ACCESS_TOKEN` | empty | Secret local Meta Page token |
| `INSTAGRAM_GRAPH_API_VERSION` | `v26.0` | Meta Graph API version |
| `UPLOAD_FACEBOOK` | `true` | Publish public Facebook Page Reels automatically |
| `FACEBOOK_PAGE_ID` | empty | Numeric Facebook Page ID; can be stored in `channels.toml` |
| `FACEBOOK_ACCESS_TOKEN` | Instagram token | Long-lived Page token with `pages_manage_posts` |
| `FACEBOOK_GRAPH_API_VERSION` | `v26.0` | Facebook Reels API version |
| `LINKS_FILE` | `links.txt` | Local URL queue |
| `DOWNLOADED_LINKS_LOG` | `work/downloaded-links.log` | Download audit log |
| `LINKS_POLL_SECONDS` | `30` | Queue interval, 5–3600 seconds |
| `CREDENTIAL_CHECK_MINUTES` | `60` | Reload `.env`, check services, and retry pending jobs |
| `PENDING_RETRY_JOBS_PER_CYCLE` | `3` | Maximum old pending jobs retried per check |
| `CLIP_DURATION_SECONDS` | `30` | Preferred duration, 20–30 |
| `SHORTS_SELECTION_MODE` | `full_coverage` | `full_coverage` or `ai_highlights` |
| `MAX_SHORTS_PER_VIDEO` | `0` | `0` = duration-based automatic count; 1–100 = optional cap |
| `VIDEO_LAYOUT` | `fit_black` | Full source with black space; optional `center_crop` or `blurred_background` |
| `VIDEO_ALLOW_UPSCALE` | `false` | Do not enlarge the source inside the vertical canvas |
| `VIDEO_CRF` | `18` | x264 quality; lower is higher quality/larger |
| `VIDEO_PRESET` | `slow` | x264 compression preset |
| `VIDEO_ENHANCER` | `none` | Set `api_market` to enable remote Real-ESRGAN |
| `APIMARKET_API_KEY` | empty | Rotated private API.market key |
| `APIMARKET_MODEL` | `RealESRGAN_x4plus` | Remote enhancement model |
| `APIMARKET_RESOLUTION` | `FHD` | Requested output resolution |
| `APIMARKET_MAX_CLIPS` | `5` | First N clips enhanced; `0` means all |
| `CLOUDINARY_CLOUD_NAME` | empty | Temporary input hosting account |
| `CLOUDINARY_API_KEY` | empty | Temporary input hosting key |
| `CLOUDINARY_API_SECRET` | empty | Temporary input hosting secret |
| `ARCHIVE_ON_UPLOAD_LIMIT` | `true` | Build a normal folder whenever platform uploads remain pending |
| `ARCHIVE_DIR` | `work/pending_uploads` | Local pending-video folder destination |
| `OPEN_UPLOAD_LIMIT_FOLDER` | `true` | Open the completed folder in Windows Explorer |
| `WORK_DIR` | `work` | Local media directory |
| `DATABASE_PATH` | `work/jobs.db` | Local SQLite history |
| `KEEP_WORK_FILES` | `true` | Keep the job folder (source video) after publishing |
| `DELETE_UPLOADED_CLIPS` | `true` | Delete each clip MP4/thumbnail once it is published on every platform |
| `SUBTITLES_ENABLED` | `true` | Burn word-synced karaoke captions into every clip |
| `SUBTITLES_WORDS_PER_SCREEN` | `4` | Words per caption line (1–8) |
| `SUBTITLES_FONT_SIZE` | `62` | Caption size on the 1080×1920 canvas (24–140) |
| `SUBTITLES_POSITION_Y` | `850` | Caption center height on the 1080×1920 canvas |
| `SUBTITLES_FONT_NAME` | `Anton` | Caption family; falls back to bundled DejaVu Sans Bold |
| `SUBTITLES_FONT_DIR` | `fonts` | Extra font files for caption rendering |
| `CHANNELS_FILE` | `channels.txt` | Channel list for automatic latest-video discovery |
| `CHANNEL_SCAN_MAX_VIDEOS` | `5` | Newest uploads inspected per channel per scan (1–50) |
| `CHANNEL_SCAN_INTERVAL_MINUTES` | `60` | How often the watcher re-scans channels (5–1440) |
| `SCHEDULE_TIMEZONE` | system local | IANA timezone for upload schedules (e.g. `Asia/Kolkata`) |
| `YOUTUBE_SCHEDULE_TIMES` | empty | Comma-separated local times; empty = upload immediately |
| `INSTAGRAM_SCHEDULE_TIMES` | empty | Same, for Instagram Reels |
| `FACEBOOK_SCHEDULE_TIMES` | empty | Same, for Facebook Page Reels |
| `RIGHTS_ACKNOWLEDGED` | `false` | Required rights confirmation |

## Test locally

```bash
python -m pytest -q
python -m ruff check .
```

A VS Code **Run tests** task is included.

## Troubleshooting

### Groq daily token limit reached

Groq retired `llama-3.1-8b-instant` and `llama-3.3-70b-versatile` on August 16, 2026.
The project now uses Groq-hosted Qwen, which needs only the existing Groq API key and no OpenAI
account or API key. Old Llama values in `.env` are migrated automatically at startup. Long
transcripts are still compacted into contiguous candidate blocks before planning. Use:

```dotenv
GROQ_MODEL=qwen/qwen3.6-27b
GROQ_FALLBACK_MODEL=qwen/qwen3.6-27b
GROQ_MAX_TRANSCRIPT_CHARS=8000
```

A URL is removed after download by design. If AI planning then fails, reuse the local source without
redownloading it:

```powershell
python -m shorts_bot.file_queue --resume JOB_ID
```

Use the job ID printed in brackets in the failure output. If the 8B model's limit is also exhausted,
wait until Groq's reported reset time or upgrade the Groq service tier.

### YouTube says "Sign in to confirm you're not a bot"

Sign in to YouTube in a supported browser. Firefox cookies can usually be read directly. Modern
Chrome on Windows may return `Failed to decrypt with DPAPI` because application-bound encryption
prevents `yt-dlp` from decrypting the browser database, even under the same Windows account.

For Firefox direct extraction:

```dotenv
YTDLP_COOKIES_FROM_BROWSER=firefox
YTDLP_BROWSER_PROFILE=
YTDLP_COOKIE_FILE=
```

To keep using Chrome, export only your YouTube session to a Netscape-format cookie file using the
procedure in yt-dlp's official cookie-exporting guide, save it locally as `youtube-cookies.txt`, then
configure:

```dotenv
YTDLP_COOKIES_FROM_BROWSER=
YTDLP_BROWSER_PROFILE=
YTDLP_COOKIE_FILE=youtube-cookies.txt
```

The cookie file takes precedence and avoids Chrome DPAPI extraction. It is ignored by Git, but it is
still equivalent to account access: never share, upload, screenshot, or commit it. Delete it and sign
out of the exported browser session when it is no longer needed. Retry with:

```powershell
python -m shorts_bot.file_queue --once
```

### YouTube says "Requested format is not available"

Current YouTube downloads require an external JavaScript runtime, matching EJS challenge scripts,
and sometimes a YouTube Proof-of-Origin token. Pull the latest update and reinstall the project; it
requires a current `yt-dlp`, Deno, `yt-dlp-ejs>=0.8`, curl-cffi, and the WebPoClient token provider.
The provider opens an automated temporary Chrome window only when YouTube requests a PO token; do not
close that window while the download is starting. Its current browser dependency does not load under
Python 3.14, so create `.venv` with Python 3.11–3.13. The downloader always keeps the exact
`bestvideo+bestaudio` selector. If exported account cookies expose only SABR/image formats for a
public video, it retries that same selector without cookies. If the default public URL then returns
HTTP 403, it forces PO-token-capable mweb/web_safari clients while preserving the same quality.

```powershell
winget install --exact --id Python.Python.3.13
git pull origin arena/01a00af0-soul-exter
deactivate 2>$null
Remove-Item -Recurse -Force .venv
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m yt_dlp --version
deno --version
python -m shorts_bot.file_queue --once
```

### YouTube download connection reset on Windows

Update the downloader and retry the same URL:

```powershell
python -m pip install --upgrade yt-dlp
python -m shorts_bot.file_queue --once
```

The workflow resumes partial downloads, forces IPv4, downloads conservatively, and retries temporary
HTTP/CDN failures with exponential backoff. A failed download does not remove its URL from
`links.txt`. If all retries still fail, temporarily disable any VPN/proxy, allow Python through the
firewall or antivirus web shield, or try another network such as a mobile hotspot.

### Uploaded video looks blurry

First wait for YouTube and Instagram to finish HD processing; immediately after upload they may only
serve a low-resolution rendition. The default renderer now shows the complete source without zooming
or cropping. It centers the source inside a 1080×1920 canvas and fills unused space with solid black.
It preserves the source frame rate and encodes H.264 at CRF 18 with the slow preset. Confirm `.env`
contains:

```dotenv
VIDEO_LAYOUT=fit_black
VIDEO_ALLOW_UPSCALE=false
VIDEO_CRF=18
VIDEO_PRESET=slow
```

The downloader keeps yt-dlp's highest available source streams. FFmpeg still cuts and re-encodes each
Short, but `fit_black` preserves the full composition and `VIDEO_ALLOW_UPSCALE=false` prevents a
low-resolution source from being enlarged. This is the only non-distorted way to show an entire
landscape frame inside a vertical phone canvas without the zoomed-in center crop.
Existing rendered/uploaded files are not changed by a configuration update. To reuse the downloaded
source, re-render all tracked clips with current settings, and upload new copies, run:

```powershell
python -m shorts_bot.file_queue --rebuild JOB_ID
```

The old platform posts remain online and must be deleted manually after checking the replacements.
`--rebuild` now removes every stale `short-*.mp4` and thumbnail before starting, resets metadata so
long descriptions/captions are regenerated, and validates any existing MP4 before reuse. This avoids
`moov atom not found` failures caused by interrupted partial files.

### FFmpeg not found

Install FFmpeg, restart VS Code, and verify `ffmpeg -version` in the integrated terminal.

### YouTube token missing or wrong channel

Run:

```bash
python -m shorts_bot.youtube_auth
```

If the token was created for another channel, delete `youtube_token.json` and authorize again with the correct Google account.

### Instagram upload fails

Confirm that:

- The account is Business or Creator, not a personal account.
- The Meta app has content-publishing permission.
- The token has not expired.
- `channels.toml` contains the numeric `instagram_business_account.id`, not the username or
  Business Portfolio name. Retrieve it with:
  `/me/accounts?fields=id,name,instagram_business_account{id,username},access_token`.

### A URL disappeared but a later stage failed

That means the download succeeded. Fix the reported AI, rendering, token, or upload issue and resume
using the job ID printed in the terminal:

```powershell
python -m shorts_bot.file_queue --resume JOB_ID
```

Completed clips and platform uploads are recorded individually, so a resume skips successful clips
and does not repost them. Instagram's official Content Publishing API permits at most 100
API-published posts per rolling 24 hours. YouTube custom thumbnail eligibility varies by channel;
if `thumbnails.set` is refused, the video remains published and YouTube uses its generated frame.
