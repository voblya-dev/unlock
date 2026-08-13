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
_AMPLITUDE = 0.050
_ATTACK = 0.070        # the note breathes in like a wave arriving, not a pluck
_RELEASE = 3.4         # exponential decay constant; higher = shorter tail
_FADE_OUT = 0.20       # final ramp to true silence

# (frequency Hz, start s, duration s, gain) tuples. These are dark, rounded
# tones for the night-sea scene: fundamentals only, low octave, slow swell and
# a long settling tail — closer to a fog horn's distant cousin than to a chime.
# Everything sits at A3 and below; nothing up in the register that can turn
# harsh on small speakers. Connect swells to a warm fifth; disconnect sighs
# back down; error is a muted double-thud well below both.
_CONNECT = (
    (196.00, 0.00, 1.05, 1.00),   # G3 — the swell
    (293.66, 0.16, 1.20, 0.70),   # D4 — rises out of it, kept quiet
)
_DISCONNECT = (
    (293.66, 0.00, 1.10, 0.80),   # D4 — the sigh on the way down, quiet
    (196.00, 0.18, 1.25, 0.90),   # G3 — settling into the dark
)
_ERROR = (
    (130.81, 0.00, 0.55, 0.90),   # C3 thud
    (123.47, 0.22, 0.80, 0.70),   # B2 answer
)

_enabled = True


def set_enabled(enabled: bool) -> None:
    global _enabled
    _enabled = bool(enabled)


def _wav(sequence) -> bytes:
    """Mix the notes onto one buffer so overlapping tails blend."""
    total = int(_RATE * max(start + duration for _, start, duration, _ in sequence))
    samples = [0.0] * total
    attack = max(1, int(_RATE * _ATTACK))

    for frequency, start, duration, gain in sequence:
        offset = int(_RATE * start)
        length = int(_RATE * duration)
        for index in range(length):
            position = offset + index
            if position >= total:
                break
            # A bare sine is the softest waveform there is; the envelope does
            # the rest. Exponential decay is how a struck bell falls away, so
            # the note ends without an audible cut. A squared attack curve
            # removes the corner at the onset, so the note swells out of
            # silence the way these ambient voices intend.
            angle = 2.0 * math.pi * frequency * index / _RATE
            attack_t = min(1.0, index / attack)
            envelope = (attack_t ** 2) * math.exp(-_RELEASE * index / _RATE)
            samples[position] += math.sin(angle) * envelope * _AMPLITUDE * gain

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
