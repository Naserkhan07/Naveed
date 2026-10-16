"""Offline speech in and out (optional; Naveed runs silently without it)."""

from __future__ import annotations


from ..lazy import lazy_attrs

__all__ = [
    "DEFAULT_PIPER_VOICE",
    "Listener",
    "Microphone",
    "PIPER_VOICES",
    "Speaker",
    "Transcriber",
    "VoiceCallbacks",
    "VoiceLoop",
    "available_engines",
    "available_transcribers",
    "download_voice",
    "mic_available",
]

from .loop import VoiceCallbacks, VoiceLoop  # noqa: E402  (stdlib-only imports)
from .stt import (  # noqa: E402
    Listener,
    Microphone,
    Transcriber,
    available_transcribers,
    mic_available,
)
from .tts import (  # noqa: E402
    DEFAULT_PIPER_VOICE,
    PIPER_VOICES,
    Speaker,
    available_engines,
    download_voice,
)

__getattr__ = lazy_attrs(globals(), {"audio": "naveed.speech.audio"})


def summary() -> dict:
    """What the voice stack can do right now (used by ``--check``)."""
    return {
        "microphone": mic_available(),
        "transcribers": available_transcribers(),
        "tts_engines": available_engines(),
    }
