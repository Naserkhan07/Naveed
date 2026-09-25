from __future__ import annotations

from pathlib import Path

from shorts_bot.db import JobRepository
from shorts_bot.models import ChannelPlatform


def _repo(tmp_path: Path) -> JobRepository:
    return JobRepository(tmp_path / "work" / "jobs.db")


def test_channel_video_memory(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    unseen = repo.filter_unseen_channel_videos("@one/videos", ["a", "b", "c"])
    assert unseen == {"a", "b", "c"}
    repo.mark_channel_video_queued("@one/videos", "b", "https://youtu.be/b", "Title B")
    assert repo.filter_unseen_channel_videos("@one/videos", ["a", "b", "c"]) == {"a", "c"}
    # Other channels are independent.
    assert "b" in repo.filter_unseen_channel_videos("@two/videos", ["b"])


def test_publication_lifecycle(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    clip_path = tmp_path / "exports" / "clip-01.mp4"
    clip_path.parent.mkdir(parents=True)
    clip_path.write_bytes(b"clip")

    assert not repo.publication_exists(clip_path)
    publication = repo.add_publication(
        clip_path,
        title="Great clip",
        description="Long body",
        instagram_caption="Caption",
        source_label="Source video",
    )
    assert repo.publication_exists(clip_path)
    assert publication.title == "Great clip"
    assert publication.youtube_video_id is None

    # FIFO: this one is the oldest pending for every platform.
    pending = repo.next_pending_publication(ChannelPlatform.YOUTUBE)
    assert pending is not None and pending.id == publication.id

    later = repo.add_publication(tmp_path / "exports" / "clip-02.mp4", title="Second")
    assert repo.next_pending_publication(ChannelPlatform.YOUTUBE).id == publication.id  # type: ignore[union-attr]

    updated = repo.update_publication(
        publication.id,
        youtube_video_id="yt-1",
        youtube_uploaded_at="2026-09-25T02:00:00+00:00",
    )
    assert updated.youtube_video_id == "yt-1"
    assert repo.next_pending_publication(ChannelPlatform.YOUTUBE).id == later.id  # type: ignore[union-attr]
    # Other platforms still see the first clip as pending.
    next_pending = repo.next_pending_publication(ChannelPlatform.INSTAGRAM)
    assert next_pending is not None
    assert next_pending.id == publication.id

    uploads = repo.count_platform_uploads_since(
        ChannelPlatform.YOUTUBE, "2026-09-25T00:00:00+00:00"
    )
    assert uploads == 1
    uploads_old = repo.count_platform_uploads_since(
        ChannelPlatform.YOUTUBE, "2026-09-26T00:00:00+00:00"
    )
    assert uploads_old == 0


def test_pending_counts(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.add_publication(tmp_path / "a.mp4", title="A")
    second = repo.add_publication(tmp_path / "b.mp4", title="B")
    counts = repo.pending_publication_counts()
    assert counts == {"YouTube": 2, "Instagram": 2, "Facebook": 2}
    repo.update_publication(second.id, instagram_media_id="ig-1")
    counts = repo.pending_publication_counts()
    assert counts["Instagram"] == 1
    assert counts["YouTube"] == 2


def test_update_publication_rejects_unknown_field(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    pub = repo.add_publication(tmp_path / "a.mp4", title="A")
    try:
        repo.update_publication(pub.id, nope="x")
    except ValueError as exc:
        assert "Unknown publication fields" in str(exc)
    else:
        raise AssertionError("expected ValueError")
