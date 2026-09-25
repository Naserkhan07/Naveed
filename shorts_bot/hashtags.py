"""Mandatory hashtag block appended to every upload, honouring platform caps.

The ordered list lives in ``hashtags.txt`` (repo root by default, override
with ``HASHTAGS_FILE``). Only tokens starting with ``#`` are collected, so
plain sentences in the file act as comments. The block is appended to every
upload's description/caption **in file order, from the first tag down**, cut
off where the platform stops accepting hashtags:

* Instagram: 30 hashtags per caption (more breaks the publish call).
* YouTube: 60 hashtags per description (more makes YouTube ignore *all* of
  them). The uploader appends ``#Shorts`` itself, so the default budget is
  59 — 59 + 1 = the 60 maximum.
* Facebook: no platform cap — the full list is appended (cap ``0``).

Tags already present in the text are never duplicated, and each platform's
character limit trims only from the end of the block.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from .models import ChannelPlatform, ShortPlan

if TYPE_CHECKING:
    from .config import Settings

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"#[^\s#]+")
_VALID_TAG_RE = re.compile(r"^#[\w]+$", re.UNICODE)

#: Default per-platform hashtag budgets (0 = unlimited).
YOUTUBE_HASHTAG_MAX = 59  # uploader adds #Shorts itself -> 60 total, the API cap
INSTAGRAM_HASHTAG_MAX = 30
FACEBOOK_HASHTAG_MAX = 0

#: Per-platform description/caption character budgets for the final text.
_TEXT_BUDGETS = {
    # Room is left for the uploader's trailing "\n\n#Shorts".
    ChannelPlatform.YOUTUBE: 4_950,
    ChannelPlatform.INSTAGRAM: 2_200,
    ChannelPlatform.FACEBOOK: 60_000,
}

_logged_missing: set[str] = set()


def parse_hashtag_text(raw: str) -> list[str]:
    """Ordered, de-duplicated hashtag tokens collected from free text."""
    tags: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN_RE.findall(raw):
        tag = token.rstrip(".,;:!?)]}")
        if not _VALID_TAG_RE.match(tag) or len(tag) < 2:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)
    return tags


def load_hashtags(path: Path) -> list[str]:
    """Read the hashtag list file; missing file -> no block (logged once)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        key = str(path)
        if key not in _logged_missing:
            logger.info("Hashtag file %s not found; uploads get no hashtag block.", path)
            _logged_missing.add(key)
        return []
    tags = parse_hashtag_text(raw)
    if not tags:
        logger.warning("Hashtag file %s holds no valid hashtags.", path)
    return tags


def count_hashtags(text: str) -> int:
    """How many hashtag tokens a text already carries (counts toward caps)."""
    return sum(1 for token in _TOKEN_RE.findall(text) if _VALID_TAG_RE.match(token))


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] if " " in text[:limit] else text[:limit]
    return cut.rstrip(" \n-_|:,") or text[:limit]


def apply_hashtags(
    text: str,
    platform: ChannelPlatform,
    tags: Sequence[str],
    *,
    cap: int,
) -> str:
    """Append the mandatory block to ``text`` up to the platform's limits.

    ``cap`` limits how many hashtags the final text may carry overall
    (existing ones count, too); ``0`` means unlimited. Trailing tags are
    dropped until the result fits the platform's character budget.
    """
    if not tags:
        return text
    budget = _TEXT_BUDGETS[platform]
    base = _truncate(text.rstrip(), budget - 2)
    present = {tag.casefold() for tag in _TOKEN_RE.findall(base)}
    slots: int | None = None if cap == 0 else max(0, cap - count_hashtags(base))

    chosen: list[str] = []
    for tag in tags:
        key = tag.casefold()
        if key in present:
            continue
        if slots is not None and len(chosen) >= slots:
            break
        present.add(key)
        chosen.append(tag)
    if not chosen:
        return base
    first_choice = chosen[0]
    while chosen:
        candidate = f"{base}\n\n{' '.join(chosen)}"
        if len(candidate) <= budget:
            return candidate
        chosen.pop()
    # No tag fits next to the base text: trim the base harder so at least the
    # first required tag always ships with the upload.
    base = _truncate(base, max(0, budget - 2 - len(first_choice)))
    return f"{base}\n\n{first_choice}".lstrip("\n")


def hashtag_cap_for(settings: Settings, platform: ChannelPlatform) -> int:
    if platform is ChannelPlatform.YOUTUBE:
        return settings.hashtags_youtube_max
    if platform is ChannelPlatform.INSTAGRAM:
        return settings.hashtags_instagram_max
    return settings.hashtags_facebook_max


def plan_with_hashtags(
    plan: ShortPlan,
    platform: ChannelPlatform,
    settings: Settings,
) -> ShortPlan:
    """Return ``plan`` with the mandatory hashtag block merged in.

    YouTube/Facebook read the description; Instagram reads its caption —
    only the field the platform actually publishes is modified.
    """
    if not settings.hashtags_enabled:
        return plan
    tags = load_hashtags(settings.hashtags_file)
    if not tags:
        return plan
    cap = hashtag_cap_for(settings, platform)
    if platform is ChannelPlatform.INSTAGRAM:
        caption = plan.instagram_caption or plan.description or plan.title
        return replace(
            plan,
            instagram_caption=apply_hashtags(caption, platform, tags, cap=cap),
        )
    description = plan.description or plan.title
    return replace(
        plan,
        description=apply_hashtags(description, platform, tags, cap=cap),
    )
