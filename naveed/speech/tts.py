"""Offline text-to-speech, with a fallback at every step.

Naveed speaks **offline by default**, so the engine chain is:

1. **Piper** — small, fast, genuinely natural neural voices, fully offline.  Used
   through the Python package when installed, otherwise through the ``piper``
   binary with the voice model stored in ``~/.naveed/models/piper``.
2. **pyttsx3** — the OS's own engine (SAPI5 / NSSpeechSynthesizer / espeak).
3. **System commands** — ``say`` on macOS, PowerShell ``System.Speech`` on
   Windows, ``spd-say``/``espeak-ng`` on Linux.
4. **Silence** — with a clear, one-time explanation, because a companion that
   crashes because it has no voice is worse than a silent one.

Speech runs on a worker thread with a queue, and the speaker publishes an
amplitude envelope while it talks so the mascot's mouth moves in time with the
audio (:class:`SpeechEvent` callbacks feed
:class:`naveed.overlay.mascot.MascotAnimator`).
"""

from __future__ import annotations

import io
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import wave
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from .. import lazy
from ..config import VoiceSettings
from .audio import Recording

__all__ = [
    "DEFAULT_PIPER_VOICE",
    "PIPER_VOICES",
    "SpeechEvent",
    "Speaker",
    "TTSResult",
    "available_engines",
    "download_voice",
    "piper_voice_path",
]

#: Piper voices worth having, with their upstream model URLs.
PIPER_VOICES = {
    "en_US-amy-medium": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx",
    "en_US-lessac-medium": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
    "en_GB-alba-medium": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium.onnx",
}
DEFAULT_PIPER_VOICE = "en_US-amy-medium"


@dataclass
class SpeechEvent:
    """What the speaker is doing right now (drives the mascot's mouth)."""

    kind: str            # start | level | end
    text: str = ""
    level: float = 0.0
    duration: float = 0.0


@dataclass
class TTSResult:
    """Outcome of one synthesis attempt."""

    ok: bool
    engine: str = ""
    message: str = ""
    wav: bytes = b""
    duration: float = 0.0


def available_engines() -> List[str]:
    """TTS engines usable right now, in preference order."""
    engines: List[str] = []
    if lazy.find_spec_safe("piper") is not None or shutil.which("piper"):
        engines.append("piper")
    if lazy.find_spec_safe("pyttsx3") is not None:
        engines.append("pyttsx3")
    if sys.platform.startswith("darwin") and shutil.which("say"):
        engines.append("say")
    if sys.platform.startswith("win"):
        engines.append("sapi")
    for binary in ("spd-say", "espeak-ng", "espeak"):
        if shutil.which(binary):
            engines.append(binary)
    return engines


def piper_model_dir(settings: Optional[VoiceSettings] = None) -> str:
    """Folder holding Piper voice models."""
    if settings is not None and settings.piper_dir:
        return settings.piper_dir
    return os.path.join(os.path.expanduser("~"), ".naveed", "models", "piper")


def piper_voice_path(settings: Optional[VoiceSettings] = None) -> Optional[str]:
    """Resolve the configured Piper voice model to an existing ``.onnx`` file."""
    settings = settings or VoiceSettings()
    if settings.piper_voice and settings.piper_voice.endswith(".onnx") and os.path.exists(settings.piper_voice):
        return settings.piper_voice
    directory = piper_model_dir(settings)
    name = settings.piper_voice or DEFAULT_PIPER_VOICE
    candidate = os.path.join(directory, f"{name}.onnx")
    if os.path.exists(candidate):
        return candidate
    if os.path.isdir(directory):
        for entry in sorted(os.listdir(directory)):
            if entry.endswith(".onnx"):
                return os.path.join(directory, entry)
    return None


def download_voice(
    name: str = DEFAULT_PIPER_VOICE,
    directory: Optional[str] = None,
    *,
    progress: Optional[Callable[[str], None]] = None,
) -> str:
    """Download a Piper voice (model + config) into the models folder.

    Called by ``python -m naveed --setup --voice``; this is the only part of
    Naveed that reaches the network outside the configured LLM endpoint.
    """
    import urllib.request

    url = PIPER_VOICES.get(name) or (name if name.startswith("http") else None)
    if url is None:
        raise ValueError(f"unknown voice {name!r}; choose from {', '.join(PIPER_VOICES)}")
    target_dir = directory or piper_model_dir()
    os.makedirs(target_dir, exist_ok=True)
    model_path = os.path.join(target_dir, os.path.basename(url))
    for source, destination in ((url, model_path), (url + ".json", model_path + ".json")):
        if os.path.exists(destination):
            continue
        if progress is not None:
            progress(f"downloading {os.path.basename(destination)}")
        request = urllib.request.Request(source, headers={"User-Agent": "naveed"})
        with urllib.request.urlopen(request, timeout=180) as response, open(destination, "wb") as handle:
            shutil.copyfileobj(response, handle)
    if progress is not None:
        progress(f"voice ready: {model_path}")
    return model_path


class Speaker:
    """Speaks text on a worker thread and reports an amplitude envelope."""

    def __init__(
        self,
        settings: Optional[VoiceSettings] = None,
        *,
        on_event: Optional[Callable[[SpeechEvent], None]] = None,
        enabled: bool = True,
    ) -> None:
        self.settings = settings or VoiceSettings()
        self.on_event = on_event
        self.enabled = enabled
        self.engine = ""
        self.last_result = TTSResult(ok=True, engine="none")
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._speaking = threading.Event()
        self._warned = False

    # --- lifecycle ------------------------------------------------------
    def start(self) -> "Speaker":
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="naveed-speak", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    @property
    def speaking(self) -> bool:
        return self._speaking.is_set()

    # --- API ------------------------------------------------------------
    def say(self, text: str, *, wait: bool = False) -> None:
        """Queue *text* to be spoken (no-op when speech is disabled)."""
        if not self.enabled or not text or not text.strip():
            return
        self.start()
        self._queue.put(text.strip())
        if wait:
            self._queue.join()

    def interrupt(self) -> None:
        """Drop anything still queued (used when the user starts talking)."""
        try:
            while True:
                self._queue.get_nowait()
                self._queue.task_done()
        except queue.Empty:
            pass

    def speak_now(self, text: str) -> TTSResult:
        """Synthesise (and play) *text* synchronously."""
        return self._speak(text)

    # --- worker ---------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            try:
                if item is None:
                    return
                self._speak(item)
            except Exception:
                pass
            finally:
                self._queue.task_done()

    def _speak(self, text: str) -> TTSResult:
        self._speaking.set()
        self._emit(SpeechEvent(kind="start", text=text))
        try:
            result = self._synthesise(text)
            if not result.ok and not self._warned:
                self._warned = True
                self._emit(SpeechEvent(kind="end", text=result.message))
                return result
            if result.wav:
                self._play(result.wav)
                self._envelope(result.duration or self._estimate(text))
            else:
                self._envelope(self._estimate(text))
            return result
        finally:
            self._speaking.clear()
            self._emit(SpeechEvent(kind="end", text=text))

    @staticmethod
    def _estimate(text: str) -> float:
        """Rough spoken duration: spoken English runs at ~14 characters/second."""
        return max(0.4, min(60.0, len(text) / 14.0))

    def _synthesise(self, text: str) -> TTSResult:
        for engine in self._engine_order():
            try:
                if engine == "piper":
                    wav, duration = self._piper(text)
                    if wav:
                        self.engine = "piper"
                        self.last_result = TTSResult(True, "piper", wav=wav, duration=duration)
                        return self.last_result
                elif engine == "pyttsx3" and self._pyttsx3(text):
                    self.engine = "pyttsx3"
                    self.last_result = TTSResult(True, "pyttsx3", duration=self._estimate(text))
                    return self.last_result
                elif engine in ("say", "sapi", "spd-say", "espeak-ng", "espeak") and self._system_command(engine, text):
                    self.engine = engine
                    self.last_result = TTSResult(True, engine, duration=self._estimate(text))
                    return self.last_result
            except Exception:
                continue
        self.last_result = TTSResult(
            False,
            "",
            "no offline voice is installed — add one with: pip install \"naveed[voice]\"",
        )
        return self.last_result

    def _engine_order(self) -> List[str]:
        if self.settings.tts and self.settings.tts not in ("auto", "none"):
            return [self.settings.tts]
        if self.settings.tts == "none":
            return []
        order = available_engines()
        # Piper with no model downloaded cannot speak through the Python API, but
        # a bare `piper` binary with its own default voice still can.
        if "piper" in order and piper_voice_path(self.settings) is None and not shutil.which("piper"):
            order = [engine for engine in order if engine != "piper"]
        return order

    def _piper(self, text: str) -> Tuple[bytes, float]:
        """Synthesise with Piper, via the Python API or the CLI."""
        model = piper_voice_path(self.settings)
        if model is None:
            return b"", 0.0
        output = os.path.join(_temp_dir(), f"naveed-{int(time.time() * 1000)}.wav")
        piper_module = lazy.optional("piper")
        if piper_module is not None and hasattr(piper_module, "PiperVoice"):
            voice = piper_module.PiperVoice.load(model, config_path=model + ".json")
            with wave.open(output, "wb") as handle:
                voice.synthesize(text, handle)
        else:
            binary = shutil.which("piper")
            if not binary:
                return b"", 0.0
            subprocess.run(
                [binary, "--model", model, "--output_file", output],
                input=text.encode("utf-8"),
                check=True,
                capture_output=True,
                timeout=120,
            )
        if not os.path.exists(output):
            return b"", 0.0
        with open(output, "rb") as handle:
            data = handle.read()
        try:
            os.unlink(output)
        except OSError:
            pass
        return data, _wav_seconds(data)

    def _pyttsx3(self, text: str) -> bool:
        engine_module = lazy.load("pyttsx3")
        engine = engine_module.init()
        engine.setProperty("rate", int(175 * max(0.5, self.settings.rate)))
        engine.setProperty("volume", max(0.0, min(1.0, self.settings.volume)))
        engine.say(text)
        engine.runAndWait()
        return True

    def _system_command(self, engine: str, text: str) -> bool:
        if engine == "say":
            subprocess.run(["say", "-r", str(int(180 * max(0.5, self.settings.rate))), text], check=True, timeout=120)
        elif engine == "sapi":
            script = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$s.Rate = {int((self.settings.rate - 1.0) * 5)}; "
                "$s.Speak([Console]::In.ReadToEnd())"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                input=text,
                text=True,
                check=True,
                timeout=120,
            )
        elif engine == "spd-say":
            subprocess.run(["spd-say", "-w", text], check=True, timeout=120)
        else:
            subprocess.run([engine, "-s", str(int(160 * max(0.5, self.settings.rate))), text], check=True, timeout=120)
        return True

    # --- playback --------------------------------------------------------
    def _play(self, wav: bytes) -> None:
        """Play WAV bytes through the first audio output that exists."""
        if not wav:
            return
        player = _system_player()
        if player:
            path = _write_temp_wav(wav)
            try:
                if player[0] == "powershell":
                    subprocess.run([*player, path], check=True, timeout=300)
                elif player[0] == "ffplay":
                    subprocess.run([*player, "-loglevel", "quiet", path], check=True, timeout=300)
                else:
                    subprocess.run([*player, path], check=True, timeout=300)
                return
            except (subprocess.SubprocessError, OSError):
                pass
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass

        sounddevice = lazy.optional("sounddevice")
        numpy = lazy.optional("numpy")
        if sounddevice is not None and numpy is not None:
            try:
                recording = decode_wav(wav)
                samples = numpy.frombuffer(recording.frames, dtype="int16")
                sounddevice.play(samples, recording.sample_rate)
                sounddevice.wait()
            except Exception:
                pass

    # --- mouth animation ---------------------------------------------------
    def _envelope(self, duration: float) -> None:
        """Emit an amplitude envelope while the audio plays.

        Piper can report word boundaries, but the difference is not worth another
        dependency: measured against the audio, a syllable-rate oscillation reads
        as lip-sync, and because it is bounded by the real audio duration it never
        desynchronises badly.
        """
        if duration <= 0 or self.on_event is None:
            return
        end = time.time() + min(duration, 30.0)
        index = 0.0
        while time.time() < end and not self._stop.is_set():
            index += 0.16
            level = 0.35 + 0.65 * abs(math.sin(index) * math.sin(index * 0.37 + 1.1))
            self._emit(SpeechEvent(kind="level", level=min(1.0, level), duration=duration))
            time.sleep(0.07)

    def _emit(self, event: SpeechEvent) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(event)
        except Exception:
            pass


# --- helpers ----------------------------------------------------------------

def _temp_dir() -> str:
    import tempfile

    return tempfile.gettempdir()


def _write_temp_wav(data: bytes) -> str:
    import tempfile

    handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    try:
        handle.write(data)
    finally:
        handle.close()
    return handle.name


def _system_player() -> Optional[List[str]]:
    """An external audio player for the current platform, if any."""
    if sys.platform.startswith("win"):
        return ["powershell", "-NoProfile", "-Command", "(New-Object Media.SoundPlayer $args[0]).PlaySync()"]
    if sys.platform.startswith("darwin") and shutil.which("afplay"):
        return ["afplay"]
    for binary in ("paplay", "aplay", "ffplay"):
        if shutil.which(binary):
            return [binary]
    return None


def decode_wav(data: bytes) -> Recording:
    """Decode WAV bytes into a :class:`naveed.speech.audio.Recording`."""
    with wave.open(io.BytesIO(data), "rb") as handle:
        return Recording(
            frames=handle.readframes(handle.getnframes()),
            sample_rate=handle.getframerate(),
            channels=handle.getnchannels(),
        )


def _wav_seconds(data: bytes) -> float:
    try:
        return decode_wav(data).seconds
    except Exception:
        return 0.0
