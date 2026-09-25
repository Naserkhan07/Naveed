import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from groq import APIStatusError, RateLimitError

from shorts_bot.ai import (
    AIPlanner,
    apply_instagram_hashtags,
    compact_transcript,
    full_coverage_plans,
    normalize_plan,
    normalize_plans,
)
from shorts_bot.models import ShortPlan, SourceVideo, TranscriptResult


def source(duration: float = 120) -> SourceVideo:
    return SourceVideo(
        path=Path("source.mp4"),
        source_url="https://youtu.be/example",
        video_id="example",
        title="A useful source",
        uploader="Original Creator",
        duration_seconds=duration,
    )


async def test_automatically_selects_active_non_openai_groq_model() -> None:
    planner = AIPlanner(
        api_key="test-key",
        model="retired-model",
        fallback_model="also-retired",
        transcription_model="whisper-large-v3-turbo",
    )

    class FakeModels:
        async def list(self):  # noqa: ANN202
            return SimpleNamespace(
                data=[
                    SimpleNamespace(id="qwen/qwen3.6-27b"),
                    SimpleNamespace(id="openai/gpt-oss-20b"),
                    SimpleNamespace(id="whisper-large-v3-turbo"),
                ]
            )

    planner.client = SimpleNamespace(models=FakeModels())  # type: ignore[assignment]

    model, transcription = await planner.check_models()

    assert model == "qwen/qwen3.6-27b"
    assert transcription == "whisper-large-v3-turbo"
    assert planner.fallback_model == "qwen/qwen3.6-27b"


def test_normalizes_ai_plan_and_adds_attribution() -> None:
    plan = normalize_plan(
        {
            "start_seconds": 44.2,
            "duration_seconds": 26,
            "title": "  A   strong   moment  ",
            "description": "The key idea in a few seconds. #Learning",
            "instagram_caption": "A quick explanation worth saving. #Learning",
            "selection_reason": "Self-contained explanation",
        },
        source(),
        target_duration=25,
    )

    assert plan.start_seconds == 44.2
    assert plan.duration_seconds == 26
    assert plan.title == "A strong moment #Shorts"
    assert "Source: A useful source — Original Creator" in plan.description
    assert "https://youtu.be/example" in plan.description
    assert "#Shorts" in plan.description
    assert "A quick explanation worth saving" in plan.instagram_caption
    assert "Credit: Original Creator" in plan.instagram_caption
    assert "#Reels" in plan.instagram_caption


async def test_retries_with_smaller_transcript_when_prompt_is_too_large() -> None:
    prompt_sizes: list[int] = []

    class FakeCompletions:
        async def create(self, **kwargs):  # noqa: ANN003, ANN201
            prompt_sizes.append(len(kwargs["messages"][1]["content"]))
            if len(prompt_sizes) == 1:
                response = httpx.Response(
                    413,
                    request=httpx.Request("POST", "https://api.groq.com/test"),
                )
                raise APIStatusError("request too large", response=response, body={})
            if len(prompt_sizes) == 4:
                content = json.dumps(
                    {
                        "title": "Title",
                        "description": "D" * 4_000,
                        "instagram_caption": "C" * 1_800,
                    }
                )
            else:
                content = (
                    '{"start_seconds": 1, "duration_seconds": 25, "title": "Title", '
                    '"description": "Description", "instagram_caption": "Caption"}'
                )
            message = SimpleNamespace(content=content)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    planner = AIPlanner(
        api_key="test-key",
        model="small-model",
        fallback_model="small-model",
        transcription_model="whisper-large-v3-turbo",
        max_transcript_chars=16_000,
    )
    planner.client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=FakeCompletions())
    )

    async def fake_transcribe(_audio_path: Path) -> TranscriptResult:
        text = "\n".join(f"[{i}-{i + 1}] Segment {i}" for i in range(3000))
        return TranscriptResult(text=text, words=())

    planner._transcribe_full = fake_transcribe  # type: ignore[method-assign]
    plan = await planner.create_plan(Path("unused.mp3"), source())

    assert plan.start_seconds == 1
    assert len(prompt_sizes) == 4  # two selection attempts, metadata, then length repair
    assert prompt_sizes[1] < prompt_sizes[0]


async def test_accepts_concise_grounded_metadata_after_one_repair() -> None:
    calls = 0

    class FakeCompletions:
        async def create(self, **kwargs):  # noqa: ANN003, ANN201
            nonlocal calls
            calls += 1
            message = SimpleNamespace(
                content=(
                    '{"title": "Accurate title", "description": "Concise factual detail", '
                    '"instagram_caption": "Concise factual caption"}'
                )
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    planner = AIPlanner(
        api_key="test-key",
        model="small-model",
        fallback_model="small-model",
        transcription_model="whisper-large-v3-turbo",
    )
    planner.client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    base = ShortPlan(0, 25, "Base", "", "")

    enriched = await planner.enrich_plan(base, source(), "[0.00-25.00] A factual clip")

    assert calls == 2
    assert "Concise factual detail" in enriched.description
    assert "Concise factual caption" in enriched.instagram_caption


async def test_retries_json_generation_with_larger_completion_budget() -> None:
    token_budgets: list[int] = []

    class FakeCompletions:
        async def create(self, **kwargs):  # noqa: ANN003, ANN201
            token_budgets.append(kwargs["max_tokens"])
            if len(token_budgets) == 1:
                response = httpx.Response(
                    400,
                    request=httpx.Request("POST", "https://api.groq.com/test"),
                )
                raise APIStatusError(
                    "json_validate_failed: max completion tokens reached",
                    response=response,
                    body={},
                )
            message = SimpleNamespace(content='{"title": "Complete"}')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    planner = AIPlanner(
        api_key="test-key",
        model="small-model",
        fallback_model="small-model",
        transcription_model="whisper-large-v3-turbo",
    )
    planner.client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=FakeCompletions())
    )

    payload = await planner._request_plan("prompt", max_tokens=650)

    assert payload == {"title": "Complete"}
    assert token_budgets == [650, 2_050]


async def test_qwen_disables_reasoning_and_retries_json_validation_as_text() -> None:
    requests: list[dict[str, object]] = []

    class FakeCompletions:
        async def create(self, **kwargs):  # noqa: ANN003, ANN201
            requests.append(kwargs)
            if len(requests) == 1:
                response = httpx.Response(
                    400,
                    request=httpx.Request("POST", "https://api.groq.com/test"),
                )
                raise APIStatusError(
                    "json_validate_failed",
                    response=response,
                    body={"error": {"code": "json_validate_failed"}},
                )
            message = SimpleNamespace(content='```json\n{"title": "Recovered"}\n```')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    planner = AIPlanner(
        api_key="test-key",
        model="qwen/qwen3.6-27b",
        fallback_model="qwen/qwen3.6-27b",
        transcription_model="whisper-large-v3-turbo",
    )
    planner.client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=FakeCompletions())
    )

    payload = await planner._request_plan("Return JSON")

    assert payload == {"title": "Recovered"}
    assert len(requests) == 2
    assert requests[0]["reasoning_effort"] == "none"
    assert requests[0]["reasoning_format"] == "hidden"
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in requests[1]
    assert [message["role"] for message in requests[0]["messages"]] == ["user"]


async def test_uses_fallback_model_when_primary_is_rate_limited() -> None:
    requested_models: list[str] = []

    class FakeCompletions:
        async def create(self, **kwargs):  # noqa: ANN003, ANN201
            requested_models.append(kwargs["model"])
            if kwargs["model"] == "large-model":
                response = httpx.Response(
                    429,
                    request=httpx.Request("POST", "https://api.groq.com/test"),
                )
                raise RateLimitError("daily limit", response=response, body={})
            message = SimpleNamespace(content='{"start_seconds": 1}')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    planner = AIPlanner(
        api_key="test-key",
        model="large-model",
        fallback_model="small-model",
        transcription_model="whisper-large-v3-turbo",
    )
    planner.client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=FakeCompletions())
    )

    payload = await planner._request_plan("prompt")

    assert payload == {"start_seconds": 1}
    assert requested_models == ["large-model", "small-model"]


def test_compacts_long_transcript_across_full_timeline() -> None:
    transcript = "\n".join(
        f"[{index:.2f}-{index + 1:.2f}] Segment {index}" for index in range(2000)
    )

    compacted = compact_transcript(transcript, max_chars=8_000, candidate_blocks=8)

    assert len(compacted) <= 8_000
    assert "TIMELINE OMITTED" in compacted
    assert "Segment 0" in compacted
    assert "Segment 1999" in compacted


def test_instagram_caption_enforces_thirty_hashtag_and_character_limits() -> None:
    tags = [f"#tag{index}" for index in range(40)]
    caption = apply_instagram_hashtags("Detailed caption #oldtag", tags, max_chars=2_000)

    assert len(caption) <= 2_000
    assert "#oldtag" not in caption
    assert caption.count("#") == 30
    assert "#tag29" in caption
    assert "#tag30" not in caption


def test_instagram_caption_places_mentions_first_without_duplicates() -> None:
    caption = apply_instagram_hashtags(
        "@wzz.unfiltered Existing caption @precious.tulip1 #oldtag",
        ["#viral", "#reels"],
        max_chars=120,
        mentions=["@wzz.unfiltered", "@precious.tulip1", "@WZZ.UNFILTERED"],
    )

    assert caption.startswith("@wzz.unfiltered @precious.tulip1\n\n")
    assert caption.casefold().count("@wzz.unfiltered") == 1
    assert caption.casefold().count("@precious.tulip1") == 1
    assert caption.endswith("#viral #reels")
    assert len(caption) <= 120


def test_full_coverage_count_depends_on_video_duration() -> None:
    plans = full_coverage_plans(source(duration=600), target_duration=30, max_clips=0)

    assert len(plans) == 20
    assert plans[0].start_seconds == 0
    assert plans[-1].start_seconds == 570
    assert all(plan.duration_seconds == 30 for plan in plans)


def test_full_coverage_respects_platform_ceiling_for_long_video() -> None:
    plans = full_coverage_plans(source(duration=4_000), target_duration=30, max_clips=0)

    assert len(plans) == 100
    assert plans[0].start_seconds == 0
    assert plans[-1].start_seconds == 3_970


def test_normalizes_multiple_non_overlapping_plans() -> None:
    plans = normalize_plans(
        {
            "clips": [
                {"start_seconds": 0, "duration_seconds": 25, "title": "First"},
                {"start_seconds": 10, "duration_seconds": 25, "title": "Overlap"},
                {"start_seconds": 50, "duration_seconds": 25, "title": "Second"},
            ]
        },
        source(),
        target_duration=25,
        max_clips=10,
    )

    assert [plan.start_seconds for plan in plans] == [0, 50]


def test_clamps_invalid_timing_to_video() -> None:
    plan = normalize_plan(
        {"start_seconds": 999, "duration_seconds": 12, "title": "Moment"},
        source(duration=22),
        target_duration=25,
    )

    assert plan.duration_seconds == 22
    assert plan.start_seconds == 0
