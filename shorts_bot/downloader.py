from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp

from .errors import DownloadError
from .models import SourceVideo

_URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}


def is_youtube_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and (parsed.hostname or "").lower() in _ALLOWED_HOSTS


def extract_youtube_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in _URL_PATTERN.findall(text):
        candidate = match.rstrip(".,;:!?)]}'\"")
        if is_youtube_url(candidate) and candidate not in urls:
            urls.append(candidate)
    return urls


class VideoDownloader:
    def __init__(
        self,
        cookies_from_browser: str = "",
        browser_profile: str = "",
        cookie_file: Path | None = None,
    ) -> None:
        self.cookies_from_browser = cookies_from_browser
        self.browser_profile = browser_profile
        self.cookie_file = cookie_file

    async def download(self, url: str, destination: Path) -> SourceVideo:
        if not is_youtube_url(url):
            raise DownloadError("Only individual youtube.com or youtu.be URLs are accepted.")
        return await asyncio.to_thread(self._download_sync, url, destination)

    @staticmethod
    def _retry_delay(
        attempt: int = 1,
        *,
        n: int | None = None,
        **_: object,
    ) -> int:
        """Use bounded backoff across old and current yt-dlp callback signatures."""
        retry_number = n if n is not None else attempt
        return min(2 ** max(0, retry_number - 1), 20)

    @classmethod
    def _download_options(
        cls,
        output_template: str,
        cookies_from_browser: str = "",
        browser_profile: str = "",
        cookie_file: Path | None = None,
    ) -> dict[str, object]:
        options: dict[str, object] = {
            # Exact Python API equivalent of: yt-dlp -f "bestvideo+bestaudio" URL
            # The streams are remuxed into MKV without re-encoding the downloaded source.
            "format": "bestvideo+bestaudio",
            "outtmpl": output_template,
            "merge_output_format": "mkv",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "overwrites": True,
            "writeinfojson": True,
            # Windows networks and some ISPs intermittently reset YouTube CDN streams.
            # Resume partial files, force IPv4, use small HTTP chunks, and back off.
            "continuedl": True,
            "source_address": "0.0.0.0",
            "socket_timeout": 30,
            "http_chunk_size": 10 * 1024 * 1024,
            "concurrent_fragment_downloads": 1,
            # Current YouTube extraction requires a full JS runtime for player challenges.
            # The project's yt-dlp[deno] dependency installs this runtime in the venv.
            "js_runtimes": {"deno": {}},
            "retries": 10,
            "fragment_retries": 10,
            "extractor_retries": 5,
            "file_access_retries": 5,
            "retry_sleep_functions": {
                "http": cls._retry_delay,
                "fragment": cls._retry_delay,
                "extractor": cls._retry_delay,
            },
        }
        if cookie_file:
            # A Netscape-format export avoids Windows Chromium DPAPI/app-bound encryption.
            # Never combine it with browser extraction, which would still trigger decryption.
            options["cookiefile"] = str(cookie_file)
        elif cookies_from_browser:
            options["cookiesfrombrowser"] = (
                cookies_from_browser,
                browser_profile or None,
                None,
                None,
            )
        return options

    @staticmethod
    def _extract_info(url: str, options: dict[str, object]) -> dict[str, object]:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
        if not isinstance(info, dict):
            raise DownloadError("YouTube returned no video metadata.")
        return info

    def _extract_with_rotated_clients(
        self,
        url: str,
        options: dict[str, object],
    ) -> dict[str, object]:
        """Retry extraction via alternate YouTube player clients, keeping cookies.

        Datacenter-IP bot walls are player-client specific: the default web client
        gets "Sign in to confirm you're not a bot" while the TV client and the
        EJS-backed mobile-web/Safari clients often still extract successfully.
        """
        client_ladders: tuple[tuple[str, ...], ...] = (
            ("android_vr",),
            ("ios",),
            ("tv_embedded",),
            ("tv",),
            ("mweb", "web_safari"),
        )
        last_detail = "no extractor detail available"
        for clients in client_ladders:
            retry_options = dict(options)
            retry_options["extractor_args"] = {
                "youtube": {"player_client": list(clients)}
            }
            # App/TV clients often expose only a single progressive stream
            # (e.g. android_vr serving format 18), so allow the "best" fallback.
            retry_options["format"] = "bestvideo+bestaudio/best"
            # Web-only challenge machinery (EJS/deno) hurts the app/TV clients'
            # similarity to real devices.
            retry_options.pop("js_runtimes", None)
            try:
                print(f"[botwall] trying player client(s): {','.join(clients)}", flush=True)
                return self._extract_info(url, retry_options)
            except yt_dlp.utils.DownloadError as retry_exc:
                last_detail = str(retry_exc)
                print(
                    f"[botwall] {','.join(clients)} failed: {last_detail[:120]}",
                    flush=True,
                )
        # Last resort: the account session itself can be the flagged variable
        # (home-IP cookies surfacing on a datacenter IP). Try the phone client
        # anonymously before giving up.
        anon_options = dict(options)
        anon_options.pop("cookiefile", None)
        anon_options.pop("cookiesfrombrowser", None)
        anon_options["extractor_args"] = {"youtube": {"player_client": ["android_vr"]}}
        anon_options["format"] = "bestvideo+bestaudio/best"
        anon_options.pop("js_runtimes", None)
        try:
            print("[botwall] trying anonymous android_vr", flush=True)
            return self._extract_info(url, anon_options)
        except yt_dlp.utils.DownloadError as anon_exc:
            last_detail = str(anon_exc)
            print(
                f"[botwall] anonymous android_vr failed: {last_detail[:120]}",
                flush=True,
            )
        raise DownloadError(
            "YouTube download failed: "
            f"{self._download_error_detail(last_detail)}"
        )

    def _download_error_detail(self, detail: str) -> str:
        normalized = detail.casefold()
        if "failed to decrypt with dpapi" in normalized:
            return (
                "Chrome cookies use Windows app-bound encryption and cannot be read directly. "
                "Export YouTube cookies in Netscape format, set "
                "YTDLP_COOKIE_FILE=youtube-cookies.txt, and clear "
                "YTDLP_COOKIES_FROM_BROWSER."
            )
        if "sign in to confirm" in normalized:
            if self.cookies_from_browser:
                return (
                    f"YouTube rejected cookies from {self.cookies_from_browser}. "
                    "Confirm that you are signed in to YouTube in that browser, "
                    "close the browser, and retry."
                )
            return (
                "YouTube requires signed-in cookies. Refresh the Netscape-format "
                "youtube-cookies.txt export and retry."
            )
        if "requested format is not available" in normalized:
            return (
                "YouTube did not expose separate best-video and best-audio streams. "
                "Update yt-dlp and yt-dlp-ejs, then refresh youtube-cookies.txt."
            )
        return detail

    def _download_sync(self, url: str, destination: Path) -> SourceVideo:
        destination.mkdir(parents=True, exist_ok=True)
        output_template = str(destination / "source.%(ext)s")
        options = self._download_options(
            output_template,
            self.cookies_from_browser,
            self.browser_profile,
            self.cookie_file,
        )
        try:
            info = self._extract_info(url, options)
        except yt_dlp.utils.DownloadError as exc:
            detail = str(exc)
            authenticated = "cookiefile" in options or "cookiesfrombrowser" in options
            if "sign in to confirm" in detail.casefold() and authenticated:
                # The bot wall is player-client specific on datacenter IPs. Rotate
                # clients (cookies kept) before reporting a stale-cookie error.
                info = self._extract_with_rotated_clients(url, options)
            elif "requested format is not available" in detail.casefold() and authenticated:
                # Account cookies can occasionally be assigned a YouTube client experiment that
                # exposes only SABR/image formats. Retry the exact same bestvideo+bestaudio
                # selector without authentication; this often restores normal public streams.
                public_options = dict(options)
                public_options.pop("cookiefile", None)
                public_options.pop("cookiesfrombrowser", None)
                try:
                    info = self._extract_info(url, public_options)
                except yt_dlp.utils.DownloadError as public_exc:
                    # A public default client can expose a format URL that later returns 403
                    # when YouTube requires a GVS Proof-of-Origin token. Force mweb/web_safari
                    # so the installed WebPoClient provider is asked to mint that token.
                    token_options = dict(public_options)
                    token_options["extractor_args"] = {
                        "youtube": {"player_client": ["mweb", "web_safari"]}
                    }
                    try:
                        info = self._extract_info(url, token_options)
                    except yt_dlp.utils.DownloadError as token_exc:
                        public_detail = self._download_error_detail(str(public_exc))
                        token_detail = self._download_error_detail(str(token_exc))
                        raise DownloadError(
                            "YouTube exposed no separate bestvideo+bestaudio streams with the "
                            "configured cookies, and both public retries failed. Confirm the WPC "
                            "PO Token Provider is active and keep its temporary Chrome window "
                            f"open. Default public retry: {public_detail}. "
                            f"PO-token client retry: {token_detail}"
                        ) from token_exc
            else:
                raise DownloadError(
                    f"YouTube download failed: {self._download_error_detail(detail)}"
                ) from exc
        except Exception as exc:
            raise DownloadError(f"Unexpected downloader error: {exc}") from exc

        candidates = [
            path
            for path in destination.glob("source.*")
            if path.is_file() and path.suffix not in {".json", ".part", ".ytdl"}
        ]
        if not candidates:
            raise DownloadError("The downloader finished but no video file was created.")
        source_path = max(candidates, key=lambda path: path.stat().st_size)
        duration = float(info.get("duration") or 0)
        if duration <= 0:
            raise DownloadError("Could not determine the source video's duration.")
        if duration < 20:
            raise DownloadError("The source video is shorter than the minimum 20-second Short.")

        return SourceVideo(
            path=source_path,
            source_url=str(info.get("webpage_url") or url),
            video_id=str(info.get("id") or "unknown"),
            title=str(info.get("title") or "Untitled video"),
            uploader=str(info.get("uploader") or info.get("channel") or "Unknown creator"),
            duration_seconds=duration,
        )
