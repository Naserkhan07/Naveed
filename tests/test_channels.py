from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from shorts_bot.channels import (
    ChannelSpec,
    ChannelVideo,
    _normalize_channel,
    _published_at,
    discover_new_videos,
    latest_channel_videos,
    read_channels,
)


class FakeRepository:
    def __init__(self, seen: set[str]) -> None:
        self.seen = seen

    def filter_unseen_channel_videos(self, channel_key: str, video_ids: list[str]) -> set[str]:
        return {video_id for video_id in video_ids if video_id not in self.seen}


def test_published_at_parses_relative_labels_conservatively() -> None:
    recent = _published_at({"published_time_text": "3 days ago"})
    stale = _published_at({"publishedTimeText": "4 days ago"})
    now = datetime.now(UTC)

    assert recent is not None and 3.9 <= (now - recent).total_seconds() / 86_400 <= 4.1
    assert stale is not None and 4.9 <= (now - stale).total_seconds() / 86_400 <= 5.1


def test_normalize_handle() -> None:
    spec = _normalize_channel("@MyChannel")
    assert spec is not None
    assert spec.videos_url == "https://www.youtube.com/@MyChannel/videos"


def test_normalize_bare_handle() -> None:
    spec = _normalize_channel("MyChannel")
    assert spec is not None
    assert spec.videos_url == "https://www.youtube.com/@MyChannel/videos"


def test_normalize_channel_id() -> None:
    channel_id = "UC" + "a1" * 11
    spec = _normalize_channel(channel_id)
    assert spec is not None
    assert spec.videos_url == f"https://www.youtube.com/channel/{channel_id}/videos"


def test_normalize_url_appends_videos() -> None:
    spec = _normalize_channel("https://www.youtube.com/@creator/")
    assert spec is not None
    assert spec.videos_url == "https://www.youtube.com/@creator/videos"


def test_normalize_url_keeps_videos_tab() -> None:
    spec = _normalize_channel("https://www.youtube.com/@creator/shorts")
    assert spec is not None
    assert spec.videos_url == "https://www.youtube.com/@creator/videos"


def test_normalize_rejects_junk() -> None:
    assert _normalize_channel("not a channel at all!") is None
    assert _normalize_channel("") is None
    assert _normalize_channel("# comment") is None


def test_read_channels_parses_and_dedupes(tmp_path: Path) -> None:
    channels_file = tmp_path / "channels.txt"
    channels_file.write_text(
        "# my channels\n@one\n\n@two\n@one\nnot a channel !!\n",
        encoding="utf-8",
    )
    specs = read_channels(channels_file)
    assert [spec.key for spec in specs] == [
        "https://www.youtube.com/@one/videos",
        "https://www.youtube.com/@two/videos",
    ]


def test_read_channels_missing_file(tmp_path: Path) -> None:
    assert read_channels(tmp_path / "nope.txt") == []


def _fake_ydl(entries, captured_options=None):
    class FakeYoutubeDL:
        def __init__(self, options):  # noqa: ANN001
            self.options = options
            if captured_options is not None:
                captured_options.update(options)

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *args):  # noqa: ANN002, ANN204
            return False

        def extract_info(self, url, download):  # noqa: ANN001, ANN201
            return {"entries": entries}

    return FakeYoutubeDL


def test_latest_channel_videos(monkeypatch) -> None:  # noqa: ANN001
    import yt_dlp

    monkeypatch.setattr(
        yt_dlp,
        "YoutubeDL",
        _fake_ydl(
            [
                {"id": "abc123", "title": "Newest", "upload_date": "20260925"},
                {"id": "def456", "title": "Older", "upload_date": "20260924"},
                None,
                {"id": "", "title": "broken"},
            ]
        ),
    )
    spec = ChannelSpec(key="k", videos_url="https://www.youtube.com/@x/videos")
    videos = latest_channel_videos(spec, max_videos=3)
    assert [(v.video_id, v.title) for v in videos] == [("abc123", "Newest"), ("def456", "Older")]
    assert videos[0].url == "https://www.youtube.com/watch?v=abc123"
    assert all(v.channel_key == "k" for v in videos)


def test_latest_channel_videos_requests_relative_upload_timestamps(monkeypatch) -> None:  # noqa: ANN001
    import yt_dlp

    captured_options: dict[str, object] = {}
    monkeypatch.setattr(
        yt_dlp,
        "YoutubeDL",
        _fake_ydl(
            [{"id": "abc123", "title": "Recent", "timestamp": 1_750_000_000}],
            captured_options,
        ),
    )
    spec = ChannelSpec(key="k", videos_url="https://www.youtube.com/@x/videos")

    (video,) = latest_channel_videos(spec)

    assert video.published_at is not None
    assert video.published_at_approximate is True
    assert captured_options["extractor_args"] == {"youtubetab": {"approximate_date": ["true"]}}


def test_discover_new_videos_filters_seen_and_out_of_window(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    import yt_dlp

    now = datetime.now(UTC)
    monkeypatch.setattr(
        yt_dlp,
        "YoutubeDL",
        _fake_ydl(
            [
                {
                    "id": "newest",
                    "title": "Newest",
                    "timestamp": (now - timedelta(hours=1)).timestamp(),
                },
                {
                    "id": "seen",
                    "title": "Seen",
                    "timestamp": (now - timedelta(hours=2)).timestamp(),
                },
                {
                    "id": "outside",
                    "title": "Too old",
                    "timestamp": (now - timedelta(days=5)).timestamp(),
                },
                {
                    "id": "oldest-new",
                    "title": "Oldest new",
                    "timestamp": (now - timedelta(hours=3)).timestamp(),
                },
                {"id": "undated", "title": "Unknown date"},
            ]
        ),
    )
    channels_file = tmp_path / "channels.txt"
    channels_file.write_text("@MyChannel\n", encoding="utf-8")
    new_videos, errors = discover_new_videos(
        channels_file,
        FakeRepository(seen={"seen"}),
        max_videos=5,
        lookback_days=4,
    )
    assert errors == []
    # Oldest unseen within the 4-day window first; seen, stale, and undated are skipped.
    assert [v.video_id for v in new_videos] == ["oldest-new", "newest"]


def test_discover_new_videos_excludes_approximate_four_day_boundary(
    monkeypatch, tmp_path: Path
) -> None:  # noqa: ANN001
    from shorts_bot import channels

    channels_file = tmp_path / "channels.txt"
    channels_file.write_text("@one\n", encoding="utf-8")
    now = datetime.now(UTC)

    def fake_latest(spec: ChannelSpec, max_videos: int) -> list[ChannelVideo]:
        del max_videos
        return [
            ChannelVideo(
                spec.key,
                "approx-boundary",
                "https://youtu.be/approx-boundary",
                "Approximate boundary",
                now - timedelta(days=4) + timedelta(minutes=2),
                True,
            ),
            ChannelVideo(
                spec.key,
                "recent-approx",
                "https://youtu.be/recent-approx",
                "Recent approximate",
                now - timedelta(days=3),
                True,
            ),
            ChannelVideo(
                spec.key,
                "recent-exact",
                "https://youtu.be/recent-exact",
                "Recent exact",
                now - timedelta(days=4) + timedelta(minutes=2),
            ),
        ]

    monkeypatch.setattr(channels, "latest_channel_videos", fake_latest)
    new_videos, errors = discover_new_videos(channels_file, FakeRepository(set()))

    assert errors == []
    assert [video.video_id for video in new_videos] == ["recent-exact", "recent-approx"]


def test_discover_new_videos_round_robins_channels(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    from shorts_bot import channels

    channels_file = tmp_path / "channels.txt"
    channels_file.write_text("@one\n@two\n", encoding="utf-8")
    now = datetime.now(UTC)
    dates = {
        "one-old": now - timedelta(hours=3),
        "one-new": now - timedelta(hours=1),
        "two-old": now - timedelta(hours=2),
        "two-new": now - timedelta(minutes=30),
    }

    def fake_latest(spec: ChannelSpec, max_videos: int) -> list[ChannelVideo]:
        del max_videos
        ids = ("one-old", "one-new") if "@one" in spec.key else ("two-old", "two-new")
        return [
            ChannelVideo(
                spec.key,
                video_id,
                f"https://youtu.be/{video_id}",
                video_id,
                dates[video_id],
            )
            for video_id in ids
        ]

    monkeypatch.setattr(channels, "latest_channel_videos", fake_latest)
    new_videos, errors = discover_new_videos(channels_file, FakeRepository(set()))

    assert errors == []
    assert [video.video_id for video in new_videos] == [
        "one-old",
        "two-old",
        "one-new",
        "two-new",
    ]


def test_discover_new_videos_collects_errors(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    import yt_dlp

    class BrokenFake:
        def __init__(self, options):  # noqa: ANN001
            pass

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *args):  # noqa: ANN002, ANN204
            return False

        def extract_info(self, url, download):  # noqa: ANN001, ANN201
            raise RuntimeError("network down")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", BrokenFake)
    channels_file = tmp_path / "channels.txt"
    channels_file.write_text("@MyChannel\n", encoding="utf-8")
    new_videos, errors = discover_new_videos(channels_file, FakeRepository(set()))
    assert new_videos == []
    assert errors and "network down" in errors[0]


def test_channel_video_structure() -> None:
    video = ChannelVideo("key", "vid", "https://youtu.be/vid", "Title")
    assert video.video_id == "vid"
