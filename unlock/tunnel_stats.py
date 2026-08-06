"""Live tunnel statistics, read straight from the running engine.

Two sources, because the two engines expose different things:

* AmneziaWG's tunnel service answers a UAPI ``get=1`` request on a named pipe
  with the peer's ``rx_bytes``/``tx_bytes`` and last handshake — the real
  counters the tunnel keeps.
* wireproxy has no such interface, so callers get ``None`` and show placeholders.

Byte totals are cumulative since the tunnel came up; rates are derived here by
differencing consecutive reads, so a caller polling once a second gets bps
without keeping any state of its own.

Reading the pipe needs Administrator rights — it is under ProtectedPrefix
precisely so an unprivileged process cannot ask a tunnel about its traffic.
Unlock is elevated anyway, since installing the tunnel service requires it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .constants import AMNEZIAWG_TUNNEL_NAME
from .logger import get_logger

log = get_logger("stats")

_PIPE = rf"\\.\pipe\ProtectedPrefix\Administrators\AmneziaWG\{AMNEZIAWG_TUNNEL_NAME}"


@dataclass(frozen=True)
class Snapshot:
    rx_bytes: int = 0
    tx_bytes: int = 0
    rx_rate: float = 0.0          # bits per second
    tx_rate: float = 0.0
    handshake_age: float | None = None   # seconds since the last handshake
    connected_for: float = 0.0    # seconds since these stats began


def _read_uapi() -> dict[str, int] | None:
    """One ``get=1`` round trip. None when the tunnel is not up.

    Opened through the raw Windows API rather than ``open()``: the pipe lives
    under ProtectedPrefix, and CreateFileW lets an absent pipe be told apart from
    a refused one without exception handling around every read.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
    OPEN_EXISTING = 3
    INVALID_HANDLE = ctypes.c_void_p(-1).value

    handle = kernel32.CreateFileW(
        _PIPE, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None
    )
    if handle == INVALID_HANDLE:
        return None
    try:
        written = wintypes.DWORD()
        request = b"get=1\n\n"
        if not kernel32.WriteFile(
            handle, request, len(request), ctypes.byref(written), None
        ):
            return None

        buffer = ctypes.create_string_buffer(8192)
        read = wintypes.DWORD()
        chunks = []
        while True:
            if not kernel32.ReadFile(
                handle, buffer, len(buffer), ctypes.byref(read), None
            ):
                break
            if read.value == 0:
                break
            chunks.append(buffer.raw[: read.value])
            if chunks[-1].endswith(b"\n\n"):
                break
        return _parse(b"".join(chunks)) if chunks else None
    finally:
        kernel32.CloseHandle(handle)


def _parse(payload: bytes) -> dict[str, int]:
    """Sum the peer counters out of a UAPI response.

    Totals rather than per-peer: a profile has one peer in practice, and summing
    keeps the shape right for the rare multi-peer config.
    """
    totals = {"rx_bytes": 0, "tx_bytes": 0, "last_handshake_time_sec": 0}
    for line in payload.decode("utf-8", "replace").splitlines():
        key, _, value = line.partition("=")
        if key in totals and value.isdigit():
            if key == "last_handshake_time_sec":
                totals[key] = max(totals[key], int(value))
            else:
                totals[key] += int(value)
    return totals


class TunnelStats:
    """Polls the engine and turns cumulative counters into rates."""

    def __init__(self) -> None:
        self._prev: tuple[float, int, int] | None = None
        self._started: float | None = None

    def reset(self) -> None:
        """Called when a tunnel comes up, so the timer and rates start at zero."""
        self._prev = None
        self._started = None

    def read(self) -> Snapshot | None:
        raw = _read_uapi()
        if raw is None:
            self.reset()
            return None

        now = time.monotonic()
        if self._started is None:
            self._started = now

        rx, tx = raw["rx_bytes"], raw["tx_bytes"]
        rx_rate = tx_rate = 0.0
        if self._prev is not None:
            elapsed = now - self._prev[0]
            if elapsed > 0.05:
                # max(0, …) because a reconnect resets the peer's counters, and a
                # negative delta would read as a nonsensical spike.
                rx_rate = max(0, rx - self._prev[1]) * 8 / elapsed
                tx_rate = max(0, tx - self._prev[2]) * 8 / elapsed
        self._prev = (now, rx, tx)

        handshake = raw["last_handshake_time_sec"]
        return Snapshot(
            rx_bytes=rx,
            tx_bytes=tx,
            rx_rate=rx_rate,
            tx_rate=tx_rate,
            handshake_age=(time.time() - handshake) if handshake else None,
            connected_for=now - self._started,
        )


def format_bytes(value: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            precision = 0 if unit == "B" else 2
            return f"{value:.{precision}f} {unit}"
        value /= 1024
    return f"{value:.2f} TB"


def format_rate(bits_per_second: float) -> str:
    for unit in ("bps", "Kbps", "Mbps", "Gbps"):
        if bits_per_second < 1000 or unit == "Gbps":
            precision = 0 if unit == "bps" else 1
            return f"{bits_per_second:.{precision}f} {unit}"
        bits_per_second /= 1000
    return f"{bits_per_second:.1f} Gbps"


def format_duration(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"
