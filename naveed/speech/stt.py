"""Offline speech-to-text: press the mascot, talk, it listens until you stop.

Two engines, both offline:

* **faster-whisper** — the default when installed; accurate on real accents and
  background noise, and fast enough on CPU with the ``base.en`` model.
* **vosk** — much smaller download, streaming, useful on low-end machines.

Microphone capture prefers ``sounddevice`` and falls back to the ``arecord``
(Linux) / ``sox`` (macOS/Windows-with-sox) command line, so a machine with no
Python audio library can still be heard.  Silence detection is a simple,
tunable RMS threshold: the listener keeps recording until you stop talking or the
maximum command duration is reached, and *returns the empty string* rather than
raising when nothing was said — a companion that screams at you for a cough is
worse than one that stays quiet.
"""

from __future__ import annotations

import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

from .. import lazy
from ..config import VoiceSettings
from .audio import SAMPLE_RATE, Recording, is_silence

__all__ = ["Listener", "Microphone", "Transcriber", "available_transcribers", "mic_available"]

logger = logging.getLogger("naveed.stt")

#: RMS below this counts as silence.  Tuned for a normal laptop microphone; a
#: noisy room raises it, a quiet headset lowers it.
DEFAULT_SILENCE_THRESHOLD = 300.0


def mic_available() -> bool:
    """True when *something* can record audio on this machine."""
    if lazy.find_spec_safe("sounddevice") is not None:
        return True
    if sys.platform.startswith("linux"):
        return bool(shutil.which("arecord"))
    return bool(shutil.which("sox") or shutil.which("rec"))


def available_transcribers() -> List[str]:
    """Installed STT engines, in preference order."""
    engines: List[str] = []
    if lazy.find_spec_safe("faster_whisper") is not None:
        engines.append("faster_whisper")
    if lazy.find_spec_safe("vosk") is not None:
        engines.append("vosk")
    return engines


class Microphone:
    """Records mono 16-bit PCM until silence, a stop signal, or a time limit."""

    def __init__(
        self,
        *,
        sample_rate: int = SAMPLE_RATE,
        block_seconds: float = 0.1,
        silence_threshold: float = DEFAULT_SILENCE_THRESHOLD,
        silence_seconds: float = 1.0,
        max_seconds: float = 20.0,
        device: Optional[str] = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.block_seconds = block_seconds
        self.silence_threshold = silence_threshold
        self.silence_seconds = silence_seconds
        self.max_seconds = max_seconds
        self.device = device
        self.level = 0.0  # live 0-1 meter for the panel

    @property
    def backend(self) -> str:
        if lazy.find_spec_safe("sounddevice") is not None:
            return "sounddevice"
        if shutil.which("arecord"):
            return "arecord"
        if shutil.which("sox") or shutil.which("rec"):
            return "sox"
        return "none"

    # --- recording -----------------------------------------------------
    def record(self, *, stop: Optional[threading.Event] = None, on_level: Optional[Callable[[float], None]] = None) -> Recording:
        """Record one utterance.

        Returns as soon as *silence_seconds* of quiet follows speech.  If nothing
        is ever said it returns after ``max(2s, silence_seconds + 1.5s)`` so a
        stray click on the mascot does not hang the UI for the whole timeout.
        """
        backend = self.backend
        if backend == "sounddevice":
            return self._record_sounddevice(stop=stop, on_level=on_level)
        if backend == "arecord":
            return self._record_cli(["arecord", "-q", "-f", "S16_LE", "-r", str(self.sample_rate), "-c", "1", "-t", "raw"], stop=stop)
        if backend == "sox":
            binary = shutil.which("rec") or shutil.which("sox")
            return self._record_cli([binary, "-q", "-t", "raw", "-r", str(self.sample_rate), "-c", "1", "-e", "signed", "-b", "16", "-"], stop=stop)
        raise RuntimeError("no microphone backend is available (install the 'voice' extra: sounddevice)")

    def _record_sounddevice(self, *, stop: Optional[threading.Event], on_level: Optional[Callable[[float], None]]) -> Recording:
        sounddevice = lazy.load("sounddevice", extra="voice")
        numpy = lazy.optional("numpy")
        blocks: "queue.Queue[bytes]" = queue.Queue()
        block_frames = int(self.sample_rate * self.block_seconds)

        def callback(indata, frames, _time_info, status) -> None:  # pragma: no cover - audio thread
            blocks.put(bytes(indata))

        stream = sounddevice.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=block_frames,
            channels=1,
            dtype="int16",
            device=self.device,
            callback=callback,
        )
        recording = Recording(sample_rate=self.sample_rate)
        quiet_for = 0.0
        spoke = False
        started = time.time()
        stream.start()
        try:
            while True:
                if stop is not None and stop.is_set():
                    break
                try:
                    block = blocks.get(timeout=0.5)
                except queue.Empty:
                    continue
                recording.extend(block)
                level = 0.0 if is_silence(block, threshold=self.silence_threshold) else 1.0
                if numpy is not None and len(block) >= 2:
                    samples = numpy.frombuffer(block, dtype="int16")
                    level = float(min(1.0, abs(samples).mean() / 6000.0))
                self.level = level
                if on_level is not None:
                    on_level(level)
                if level > 0.05:
                    spoke = True
                    quiet_for = 0.0
                else:
                    quiet_for += self.block_seconds
                elapsed = time.time() - started
                if spoke and quiet_for >= self.silence_seconds:
                    break
                if not spoke and elapsed >= max(2.0, self.silence_seconds + 1.5):
                    break
                if elapsed >= self.max_seconds:
                    break
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        return recording

    def _record_cli(self, command: Sequence[str], *, stop: Optional[threading.Event]) -> Recording:
        """Record with an external tool, cutting the process off on silence."""
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        recording = Recording(sample_rate=self.sample_rate)
        quiet_for = 0.0
        spoke = False
        started = time.time()
        block_bytes = int(self.sample_rate * self.block_seconds) * 2
        try:
            assert process.stdout is not None
            while True:
                if stop is not None and stop.is_set():
                    break
                block = process.stdout.read(block_bytes)
                if not block:
                    break
                recording.extend(block)
                silent = is_silence(block, threshold=self.silence_threshold)
                self.level = 0.0 if silent else 1.0
                if not silent:
                    spoke = True
                    quiet_for = 0.0
                else:
                    quiet_for += self.block_seconds
                elapsed = time.time() - started
                if spoke and quiet_for >= self.silence_seconds:
                    break
                if not spoke and elapsed >= max(2.0, self.silence_seconds + 1.5):
                    break
                if elapsed >= self.max_seconds:
                    break
        finally:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        return recording


class Transcriber:
    """Turns a :class:`Recording` into text, offline."""

    def __init__(self, settings: Optional[VoiceSettings] = None) -> None:
        self.settings = settings or VoiceSettings()
        self._whisper_model = None
        self._vosk_model = None
        self.last_error = ""
        self.load_time = 0.0

    @property
    def engine(self) -> str:
        configured = self.settings.stt
        if configured and configured not in ("auto", "none"):
            return configured
        engines = available_transcribers()
        return engines[0] if engines else "none"

    # --- engines --------------------------------------------------------
    def _whisper(self):
        if self._whisper_model is None:
            faster_whisper = lazy.load("faster_whisper", extra="voice")
            started = time.time()
            self._whisper_model = faster_whisper.WhisperModel(
                self.settings.whisper_model,
                device=self.settings.whisper_device,
                compute_type=self.settings.whisper_compute,
            )
            self.load_time = time.time() - started
        return self._whisper_model

    def _vosk(self):
        if self._vosk_model is None:
            vosk = lazy.load("vosk", extra="voice")
            model_dir = os.path.join(os.path.expanduser("~"), ".naveed", "models", "vosk")
            if not os.path.isdir(model_dir):
                raise RuntimeError(
                    "the Vosk model folder is missing — download a model from "
                    "https://alphacephei.com/vosk/models and unpack it into " + model_dir
                )
            vosk.SetLogLevel(-1)
            self._vosk_model = vosk.Model(model_dir)
        return self._vosk_model

    def transcribe(self, recording: Recording) -> str:
        """Return the recognised text (empty string when nothing was said)."""
        if recording.empty or recording.seconds < 0.25:
            return ""
        engine = self.engine
        try:
            if engine == "faster_whisper":
                return self._transcribe_whisper(recording)
            if engine == "vosk":
                return self._transcribe_vosk(recording)
        except Exception as error:  # report, never crash the overlay
            self.last_error = f"{type(error).__name__}: {error}"
            logger.warning("transcription failed: %s", self.last_error)
            return ""
        self.last_error = (
            "no speech-to-text engine is installed — add one with: pip install \"naveed[voice]\""
        )
        return ""

    def _transcribe_whisper(self, recording: Recording) -> str:
        model = self._whisper()
        samples = recording.samples()
        if not samples:
            return ""
        numpy = lazy.optional("numpy")
        if numpy is not None:
            audio = numpy.asarray(samples, dtype=numpy.float32) / 32768.0
        else:  # pragma: no cover - NumPy is a faster-whisper dependency
            audio = [value / 32768.0 for value in samples]
        segments, _info = model.transcribe(
            audio,
            language=None if self.settings.language in ("", "auto") else self.settings.language,
            vad_filter=True,
            beam_size=1,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def _transcribe_vosk(self, recording: Recording) -> str:
        vosk = lazy.load("vosk", extra="voice")
        model = self._vosk()
        recognizer = vosk.KaldiRecognizer(model, recording.sample_rate)
        recognizer.SetWords(False)
        recognizer.AcceptWaveform(recording.frames)
        import json

        payload = json.loads(recognizer.FinalResult() or "{}")
        return str(payload.get("text") or "").strip()


@dataclass
class ListenResult:
    """What one listening session produced."""

    text: str = ""
    seconds: float = 0.0
    error: str = ""


class Listener:
    """One-shot listening: record, transcribe, hand back text.

    ``on_partial`` fires with a live microphone level so the mascot can pulse
    while it hears you; ``on_text`` fires once with the final transcript.
    """

    def __init__(
        self,
        settings: Optional[VoiceSettings] = None,
        *,
        on_level: Optional[Callable[[float], None]] = None,
        on_text: Optional[Callable[[str], None]] = None,
        transcriber: Optional[Transcriber] = None,
    ) -> None:
        self.settings = settings or VoiceSettings()
        self.microphone = Microphone(
            silence_seconds=self.settings.silence_seconds,
            max_seconds=self.settings.max_command_seconds,
            device=self.settings.input_device,
        )
        self.transcriber = transcriber or Transcriber(self.settings)
        self.on_level = on_level
        self.on_text = on_text
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last: ListenResult = ListenResult()
        self.busy = False

    @property
    def available(self) -> bool:
        return mic_available()

    def start(self) -> bool:
        """Begin listening in the background. Returns False when already busy."""
        if self.busy:
            return False
        if not self.available:
            self.last = ListenResult(error="no microphone is available")
            return False
        self._stop.clear()
        self.busy = True
        self._thread = threading.Thread(target=self._run, name="naveed-listen", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stop recording early (push-to-talk release)."""
        self._stop.set()

    def listen(self, *, timeout: Optional[float] = None) -> ListenResult:
        """Record and transcribe on the calling thread."""
        started = time.time()
        try:
            recording = self.microphone.record(stop=self._stop, on_level=self.on_level)
        except Exception as error:
            self.last = ListenResult(error=f"{type(error).__name__}: {error}")
            return self.last
        text = self.transcriber.transcribe(recording)
        self.last = ListenResult(
            text=text,
            seconds=time.time() - started,
            error=self.transcriber.last_error if not text else "",
        )
        return self.last

    def _run(self) -> None:
        try:
            result = self.listen()
            if result.text and self.on_text is not None:
                try:
                    self.on_text(result.text)
                except Exception:
                    pass
        finally:
            self.busy = False
