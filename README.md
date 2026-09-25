# Local Groq Shorts + Instagram Reels Automation

This project runs entirely on your laptop from VS Code. There is no separate web-server or Docker installation requirement.

Add authorized YouTube links to `links.txt`. The local program downloads each video, removes its link after a successful download, divides the usable timeline into consecutive 20–30 second clips based on the video's duration, generates detailed AI metadata and thumbnails, renders vertical Shorts, and publishes each one to YouTube, Instagram, and Facebook.

> **Only process videos you own or have explicit permission/license to download, edit, and republish.** A publicly viewable video is not automatically licensed for reuse. The program requires `RIGHTS_ACKNOWLEDGED=true`.

## What the local workflow does

1. Watches the local `links.txt` file.
2. Downloads one authorized YouTube video at a time using the Python API equivalent of `yt-dlp -f "bestvideo+bestaudio" URL`, then remuxes those streams without source re-encoding.
3. Removes every matching URL line immediately after the video downloads successfully.
4. Records the URL and job ID in `work/downloaded-links.log`.
5. Extracts speech audio locally with FFmpeg.
6. Uses Groq `whisper-large-v3-turbo` for timestamped transcription.
7. In `full_coverage` mode, calculates the clip count from source duration and covers the timeline with consecutive 20–30 second sections.
8. Generates a detailed YouTube title/description and a separate Instagram caption for every clip.
9. Renders every section as an H.264/AAC MP4 at the configured native-resolution policy.
10. When enabled, temporarily hosts selected clips and runs API.market Real-ESRGAN before upload.
11. Generates a JPEG thumbnail from the final (enhanced or original) clip.
12. Uploads every result as a public YouTube Short, Instagram Reel, and Facebook Page Reel, using a custom YouTube thumbnail when eligible and a midpoint cover frame on Instagram.

A downloaded URL is removed before AI/render/upload starts. If a later stage fails, the URL remains in `work/downloaded-links.log`; copy it back into `links.txt` when you want to retry.

## Local files

- `main.py` — easiest way to start the watcher from VS Code
- `links.txt` — paste one YouTube URL per line
- `channels.toml` — non-secret YouTube and Instagram account IDs
- `.env` — local API keys and tokens; never committed
- `client_secret.json` — Google OAuth desktop client; never committed
- `youtube_token.json` — generated Google OAuth token; never committed
- `work/jobs.db` — local job history
- `work/jobs/<job-id>/short-001.mp4`, `short-002.mp4`, … — rendered Shorts/Reels
- `work/jobs/<job-id>/thumbnail-001.jpg`, `thumbnail-002.jpg`, … — generated covers
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
