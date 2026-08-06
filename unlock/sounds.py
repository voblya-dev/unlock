"""Connect / disconnect chimes.

The tones are synthesised into an in-memory WAV and handed to ``winsound``
rather than shipped as assets: two short chimes are a few lines of arithmetic,
and bundling audio files would mean another PyInstaller datas entry plus a
format the user's machine has to have a codec for.
"""

from __future__ import annotations

import io
import math
import struct
import sys
import threading
import wave

from .logger import get_logger

log = get_logger("sounds")

_RATE = 44100
_AMPLITUDE = 0.05
_ATTACK = 0.09         # slow enough that the note swells in rather than clicks
_RELEASE = 4.6         # exponential decay constant; higher = shorter tail
_FADE_OUT = 0.16       # final ramp to true silence

# (frequency Hz, start s, duration s) triples. Notes overlap, so the pair reads
# as one soft chord rather than two beeps. Rising = "on", falling = "off".
# Kept in the lower octaves: the same envelope an octave up reads as piercing.
_CONNECT = ((261.63, 0.00, 0.55), (392.00, 0.10, 0.62))
_DISCONNECT = ((293.66, 0.00, 0.55), (196.00, 0.10, 0.66))
_ERROR = ((196.00, 0.00, 0.55), (164.81, 0.10, 0.66))

_enabled = True


def set_enabled(enabled: bool) -> None:
    global _enabled
    _enabled = bool(enabled)


def _wav(sequence) -> bytes:
    """Mix the notes onto one buffer so overlapping tails blend."""
    total = int(_RATE * max(start + duration for _, start, duration in sequence))
    samples = [0.0] * total
    attack = max(1, int(_RATE * _ATTACK))

    for frequency, start, duration in sequence:
        offset = int(_RATE * start)
        length = int(_RATE * duration)
        for index in range(length):
            position = offset + index
            if position >= total:
                break
            # A bare sine is the softest waveform there is; the envelope does
            # the rest. Exponential decay is how a struck bell falls away, so
            # the note ends without an audible cut.
            angle = 2.0 * math.pi * frequency * index / _RATE
            envelope = min(1.0, index / attack) * math.exp(-_RELEASE * index / _RATE)
            samples[position] += math.sin(angle) * envelope * _AMPLITUDE

    # The exponential never reaches zero, so the buffer would otherwise end on a
    # non-zero sample — an audible click at the point the tail is cut off.
    fade = min(total, int(_RATE * _FADE_OUT))
    for index in range(fade):
        # Cosine rather than linear: the slope is flat at both ends, so the ramp
        # joins the decay without a corner in it.
        ramp = 0.5 * (1.0 + math.cos(math.pi * index / fade))
        samples[total - fade + index] *= ramp

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_RATE)
        handle.writeframes(
            b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples)
        )
    return buffer.getvalue()


_CACHE: dict[str, bytes] = {}


def _render(name: str, sequence) -> bytes:
    if name not in _CACHE:
        _CACHE[name] = _wav(sequence)
    return _CACHE[name]


def _play(name: str, sequence) -> None:
    if not _enabled or sys.platform != "win32":
        return

    def worker() -> None:
        try:
            import winsound

            # SND_ASYNC is rejected outright when the source is memory
            # ("Cannot play asynchronously from memory"), so the call blocks —
            # which is fine here, the whole point of this thread.
            winsound.PlaySound(
                _render(name, sequence),
                winsound.SND_MEMORY | winsound.SND_NODEFAULT,
            )
        except Exception as exc:                    # noqa: BLE001 - audio is optional
            log.debug("Could not play %s: %s", name, exc)

    # Synthesis is ~0.3 s of samples in pure Python; on the UI thread that is a
    # visible hitch on the first play of each sound.
    threading.Thread(target=worker, daemon=True).start()


def connected() -> None:
    _play("connect", _CONNECT)


def disconnected() -> None:
    _play("disconnect", _DISCONNECT)


def failed() -> None:
    _play("error", _ERROR)
