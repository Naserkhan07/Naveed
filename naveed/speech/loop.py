"""Voice flow: click the mascot, say the thing, watch it happen.

The user chose **click-to-talk**, so this module is deliberately simple and
predictable:

``begin()``   stop any speech that is playing, start recording, tell the mascot
              to show its listening state;
``finish()``  stop recording early (a second click, or the panel's stop button);
``cancel()``  drop the recording without transcribing.

Everything is reported through callbacks, so the same loop drives the Qt overlay
and the headless test suite.  No part of it touches Qt or the agent directly,
which is what keeps the speech stack lazy: a machine with no microphone and no
voice installed still runs the mascot, it just cannot hear or speak.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

from ..config import Config
from .stt import Listener
from .tts import Speaker, SpeechEvent

__all__ = ["VoiceLoop", "VoiceCallbacks"]


@dataclass
class VoiceCallbacks:
    """Everything the overlay needs to animate a conversation."""

    on_state: Optional[Callable[[str], None]] = None          # listening | idle | thinking
    on_level: Optional[Callable[[float], None]] = None        # live mic level 0-1
    on_text: Optional[Callable[[str], None]] = None           # final transcript
    on_error: Optional[Callable[[str], None]] = None
    on_speech: Optional[Callable[[SpeechEvent], None]] = None  # start/level/end


class VoiceLoop:
    """Wires the microphone, the transcriber and the speaker together."""

    def __init__(self, config: Config, callbacks: Optional[VoiceCallbacks] = None) -> None:
        self.config = config
        self.callbacks = callbacks or VoiceCallbacks()
        self._lock = threading.RLock()
        self._listening = False
        self.transcript = ""

        self.speaker = Speaker(config.voice, on_event=self._on_speech)
        self.listener = Listener(
            config.voice,
            on_level=self._on_level,
            on_text=self._on_transcript,
        )

    # --- properties ----------------------------------------------------
    @property
    def listening(self) -> bool:
        return self._listening

    @property
    def can_listen(self) -> bool:
        return self.listener.available

    @property
    def can_speak(self) -> bool:
        return self.speaker.enabled

    # --- speaking ------------------------------------------------------
    def say(self, text: str) -> None:
        """Speak *text* (the mascot's mouth follows through the callbacks)."""
        self.speaker.say(text)

    def stop_speaking(self) -> None:
        self.speaker.interrupt()

    @property
    def speaking(self) -> bool:
        return self.speaker.speaking

    # --- listening -----------------------------------------------------
    def begin(self) -> bool:
        """Start listening (click on the mascot).

        Returns ``False`` when there is no microphone or a session is running.
        """
        with self._lock:
            if self._listening:
                return False
            self.stop_speaking()
            started = self.listener.start()
            if not started:
                error = self.listener.last.error or "I could not open the microphone."
                self._emit_error(error)
                return False
            self._listening = True
            self._emit_state("listening")
            return True

    def finish(self) -> None:
        """Stop recording early; transcription still completes."""
        self.listener.stop()

    def cancel(self) -> None:
        self.listener.stop()
        with self._lock:
            self._listening = False
        self._emit_state("idle")

    def listen_blocking(self) -> str:
        """Record and transcribe on this thread (used by ``--listen``)."""
        with self._lock:
            self.stop_speaking()
            self._listening = True
            self._emit_state("listening")
        try:
            result = self.listener.listen()
        finally:
            with self._lock:
                self._listening = False
            self._emit_state("idle")
        return result.text

    # --- callbacks ------------------------------------------------------
    def _on_speech(self, event: SpeechEvent) -> None:
        if self.callbacks.on_speech is not None:
            self.callbacks.on_speech(event)
        if event.kind == "start":
            self._emit_state("speaking")
        elif event.kind == "end":
            self._emit_state("idle")

    def _on_level(self, level: float) -> None:
        if self.callbacks.on_level is not None:
            self.callbacks.on_level(level)

    def _on_transcript(self, text: str) -> None:
        self.transcript = text
        with self._lock:
            self._listening = False
        if not text:
            self._emit_error("I did not catch that — click me and try again.")
            self._emit_state("idle")
            return
        self._emit_state("thinking")
        if self.callbacks.on_text is not None:
            self.callbacks.on_text(text)

    def _emit_state(self, state: str) -> None:
        if self.callbacks.on_state is not None:
            self.callbacks.on_state(state)

    def _emit_error(self, message: str) -> None:
        if self.callbacks.on_error is not None:
            self.callbacks.on_error(message)

    def close(self) -> None:
        self.cancel()
        self.speaker.stop()
