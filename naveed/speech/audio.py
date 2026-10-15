"""Small audio helpers: recording buffers, WAV files, levels.

Kept dependency-free (stdlib ``wave``/``array``) apart from an optional NumPy
fast-path, because the speech stack must load lazily and degrade gracefully on a
machine with no microphone at all.
"""

from __future__ import annotations

import array
import io
import math
import os
import wave
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from .. import lazy

__all__ = [
    "SAMPLE_RATE",
    "Recording",
    "dbfs",
    "is_silence",
    "pcm_to_array",
    "read_wav",
    "resample",
    "wav_bytes",
    "write_wav",
]

#: 16 kHz mono is what both Whisper and Vosk want, and it keeps buffers small.
SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2  # 16-bit


@dataclass
class Recording:
    """A block of mono 16-bit PCM."""

    frames: bytes = b""
    sample_rate: int = SAMPLE_RATE
    channels: int = 1

    def __len__(self) -> int:
        return len(self.frames) // max(1, self.sample_width * self.channels)

    @property
    def sample_width(self) -> int:
        return SAMPLE_WIDTH

    @property
    def seconds(self) -> float:
        return len(self) / float(self.sample_rate or 1)

    @property
    def empty(self) -> bool:
        return not self.frames

    def extend(self, more: bytes) -> "Recording":
        self.frames += more
        return self

    # --- levels -------------------------------------------------------
    def samples(self) -> List[int]:
        return pcm_to_array(self.frames)

    def rms(self, *, window: Optional[int] = None) -> float:
        """Root-mean-square level of the whole recording, or its last window."""
        values = self.samples()
        if window:
            values = values[-window:]
        if not values:
            return 0.0
        total = 0
        for value in values:
            total += value * value
        return math.sqrt(total / len(values))

    def level(self) -> float:
        """Level in 0.0-1.0 (useful for a mic meter on the panel)."""
        return min(1.0, self.rms() / 8000.0)

    # --- output -------------------------------------------------------
    def wav_bytes(self) -> bytes:
        return wav_bytes(self.frames, sample_rate=self.sample_rate, channels=self.channels)

    def write(self, path: str) -> str:
        return write_wav(path, self.frames, sample_rate=self.sample_rate, channels=self.channels)


def pcm_to_array(frames: bytes) -> List[int]:
    """Decode little-endian 16-bit PCM into a list of ints."""
    if not frames:
        return []
    values = array.array("h")
    values.frombytes(frames[: len(frames) - (len(frames) % 2)])
    if os.sys.byteorder != "little":
        values.byteswap()
    return values.tolist()


def array_to_pcm(values: Iterable[float], *, clip: float = 32767.0) -> bytes:
    """Encode floats (-1..1) or ints into little-endian 16-bit PCM."""
    decoded = array.array("h")
    for value in values:
        scaled = int(round(value * clip)) if isinstance(value, float) and -1.5 <= value <= 1.5 else int(value)
        decoded.append(max(-32768, min(32767, scaled)))
    if os.sys.byteorder != "little":
        decoded.byteswap()
    return decoded.tobytes()


def dbfs(rms: float) -> float:
    """Convert an RMS amplitude to dBFS (0 = full scale)."""
    if rms <= 0:
        return -120.0
    return max(-120.0, 20.0 * math.log10(rms / 32768.0))


def is_silence(frames: bytes, *, threshold: float = 320.0) -> bool:
    """True when a block is quieter than *threshold* RMS."""
    values = pcm_to_array(frames)
    if not values:
        return True
    total = 0
    for value in values:
        total += value * value
    return math.sqrt(total / len(values)) < threshold


def wav_bytes(frames: bytes, *, sample_rate: int = SAMPLE_RATE, channels: int = 1) -> bytes:
    """Wrap raw PCM in a WAV container."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(SAMPLE_WIDTH)
        handle.setframerate(sample_rate)
        handle.writeframes(frames)
    return buffer.getvalue()


def write_wav(path: str, frames: bytes, *, sample_rate: int = SAMPLE_RATE, channels: int = 1) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(SAMPLE_WIDTH)
        handle.setframerate(sample_rate)
        handle.writeframes(frames)
    return path


def read_wav(path: str) -> Recording:
    """Read a WAV file into a :class:`Recording` (16-bit mono assumed)."""
    with wave.open(path, "rb") as handle:
        frames = handle.readframes(handle.getnframes())
        return Recording(frames=frames, sample_rate=handle.getframerate(), channels=handle.getnchannels())


def resample(values: Sequence[float], source_rate: int, target_rate: int) -> List[float]:
    """Linear resample; NumPy is used when available, else pure Python."""
    if source_rate == target_rate or not values:
        return list(values)
    numpy = lazy.optional("numpy")
    if numpy is not None:
        array_like = numpy.asarray(values, dtype=numpy.float32)
        count = int(round(len(array_like) * target_rate / float(source_rate)))
        positions = numpy.linspace(0, len(array_like) - 1, count)
        return numpy.interp(positions, numpy.arange(len(array_like)), array_like).tolist()
    count = max(1, int(round(len(values) * target_rate / float(source_rate))))
    step = (len(values) - 1) / float(max(1, count - 1))
    result: List[float] = []
    for index in range(count):
        position = index * step
        low = int(math.floor(position))
        high = min(low + 1, len(values) - 1)
        fraction = position - low
        result.append(values[low] * (1 - fraction) + values[high] * fraction)
    return result
