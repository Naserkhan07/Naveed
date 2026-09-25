from __future__ import annotations

from pathlib import Path

from shorts_bot.channels import (
    ChannelSpec,
    ChannelVideo,
    _normalize_channel,
    discover_new_videos,
    latest_channel_videos,
    read_channels,
)


class FakeRepository:
    def __init__(self, seen: set[str]) -> None:
        self.seen = seen

    def filter_unseen_channel_videos(self, channel_key: str, video_ids: list[str]) -> set[str]:
        return {video_id for video_id in video_ids if video_id not in self.seen}


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


def _fake_ydl(entries):
    class FakeYoutubeDL:
        def __init__(self, options):  # noqa: ANN001
            self.options = options

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
                {"id": "abc123", "title": "Newest"},
                {"id": "def456", "title": "Older"},
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


def test_discover_new_videos_filters_seen_and_reverses(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    import yt_dlp

    monkeypatch.setattr(
        yt_dlp,
        "YoutubeDL",
        _fake_ydl(
            [
                {"id": "newest", "title": "Newest"},
                {"id": "seen", "title": "Seen"},
                {"id": "newest-first", "title": "Oldest new"},
            ]
        ),
    )
    channels_file = tmp_path / "channels.txt"
    channels_file.write_text("@MyChannel\n", encoding="utf-8")
    new_videos, errors = discover_new_videos(
        channels_file,
        FakeRepository(seen={"seen"}),
        max_videos=3,
    )
    assert errors == []
    # Oldest unseen first so the queue processes uploads in order.
    assert [v.video_id for v in new_videos] == ["newest-first", "newest"]


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
