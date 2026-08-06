"""Drives Amnezia's own Windows client as a headless tunnel service.

``amneziawg.exe /installtunnelservice CONFIG`` registers a Windows service that
creates a real Wintun adapter and owns the default route — the same mechanism
WireGuard for Windows and WireSock use. That is the whole reason this exists
next to the wireproxy path: wireproxy exposes the tunnel as a SOCKS listener,
and SOCKS carries no UDP, so Discord voice, games and QUIC cannot cross it.

The service runs as LocalSystem, outlives our process, and is keyed by the
config file's stem. So the config lives under ProgramData (SYSTEM can read it)
and a stale service from a crashed session is torn down before a new one starts.
"""

from __future__ import annotations

import subprocess
import time

from .constants import (
    AMNEZIAWG_CONFIG_PATH,
    AMNEZIAWG_SEARCH_DIRS,
    AMNEZIAWG_TUNNEL_NAME,
)
from .logger import get_logger
from .vpn_links import Profile

log = get_logger("awg")

_CREATE_NO_WINDOW = 0x08000000
_SERVICE = f"AmneziaWGTunnel${AMNEZIAWG_TUNNEL_NAME}"
_START_TIMEOUT = 12.0
_STOP_TIMEOUT = 10.0
_POLL = 0.25


class AwgEngineError(RuntimeError):
    pass


def amneziawg_path():
    for directory in AMNEZIAWG_SEARCH_DIRS:
        candidate = directory / "amneziawg.exe"
        if candidate.exists():
            return candidate
    return None


def build_config(profile: Profile) -> str:
    """wg-quick INI for the tunnel service.

    Same shape as the wireproxy config minus the listener sections, plus a
    routing table entry: the service needs to know which addresses to claim,
    and 0.0.0.0/0 in AllowedIPs is what makes it take the default route.
    """
    settings = profile.outbound
    addresses = settings.get("address") or ["10.0.0.2/32"]
    lines = [
        "[Interface]",
        f"PrivateKey = {settings['private_key']}",
        f"Address = {', '.join(addresses)}",
        # Without a DNS line Windows keeps the ISP's resolver on the physical
        # adapter, which both leaks lookups and answers with the wrong country.
        f"DNS = {', '.join(settings.get('dns') or ['1.1.1.1', '8.8.8.8'])}",
    ]
    if settings.get("mtu"):
        lines.append(f"MTU = {settings['mtu']}")
    for key, value in (settings.get("awg") or {}).items():
        lines.append(f"{key} = {value}")

    lines += [
        "",
        "[Peer]",
        f"PublicKey = {settings['public_key']}",
        f"Endpoint = {settings['server']}:{settings['server_port']}",
        f"AllowedIPs = {', '.join(_routable(settings.get('allowed_ips') or ['0.0.0.0/0'], addresses))}",
    ]
    if settings.get("pre_shared_key"):
        lines.append(f"PresharedKey = {settings['pre_shared_key']}")
    lines.append(f"PersistentKeepalive = {settings.get('keepalive') or 25}")
    lines.append("")
    return "\n".join(lines)


def _routable(allowed: list[str], addresses: list[str]) -> list[str]:
    """Drop IPv6 routes when the interface has no IPv6 address to send them from.

    Plenty of published configs carry ``AllowedIPs = 0.0.0.0/0, ::/0`` next to an
    IPv4-only Address. The tunnel service takes the v6 route at face value, so
    every IPv6 packet is handed to an interface that cannot emit it and is
    dropped, instead of going out over the physical link.
    """
    if any(":" in address for address in addresses):
        return allowed
    kept = [route for route in allowed if ":" not in route]
    if len(kept) != len(allowed):
        log.info("Dropped IPv6 routes: the profile has no IPv6 address")
    return kept or ["0.0.0.0/0"]


def _run(argv: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATE_NO_WINDOW,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise AwgEngineError(f"{argv[0]} did not respond within {timeout:.0f}s") from exc
    except OSError as exc:
        raise AwgEngineError(f"Could not run {argv[0]}: {exc}") from exc


def _service_state() -> str:
    """RUNNING / STOPPED / ABSENT, straight from the service database."""
    result = _run(["sc", "query", _SERVICE], timeout=10)
    if result.returncode != 0:
        return "ABSENT"
    for token in ("RUNNING", "STOP_PENDING", "START_PENDING", "STOPPED", "PAUSED"):
        if token in result.stdout:
            return token
    return "STOPPED"


class AwgEngine:
    """Installs and removes the tunnel service for one profile."""

    def __init__(self) -> None:
        self._profile: Profile | None = None

    @property
    def running(self) -> bool:
        return _service_state() in ("RUNNING", "START_PENDING")

    @property
    def profile(self) -> Profile | None:
        return self._profile if self.running else None

    def start(self, profile: Profile) -> None:
        exe = amneziawg_path()
        if exe is None:
            raise AwgEngineError(
                f"amneziawg.exe not found in {AMNEZIAWG_SEARCH_DIRS[0]}. It ships "
                "with Unlock — reinstall, or download the MSI from "
                "github.com/amnezia-vpn/amneziawg-windows-client."
            )
        if not (exe.parent / "wintun.dll").exists():
            raise AwgEngineError(
                f"wintun.dll is missing from {exe.parent} — amneziawg.exe needs it "
                "in its own directory to create the adapter."
            )

        # A service left behind by a crash holds the adapter name we want.
        self.stop()

        AMNEZIAWG_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        AMNEZIAWG_CONFIG_PATH.write_text(build_config(profile), encoding="utf-8")

        log.info("Installing the AmneziaWG tunnel service for '%s'", profile.name)
        result = _run([str(exe), "/installtunnelservice", str(AMNEZIAWG_CONFIG_PATH)])
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            reason = detail[-1] if detail else f"exit code {result.returncode}"
            if "denied" in reason.lower() or result.returncode == 5:
                reason = "installing the tunnel service needs Administrator rights"
            raise AwgEngineError(f"AmneziaWG failed to start: {reason}")

        # /installtunnelservice returns as soon as the service is registered; the
        # handshake happens after. Wait for RUNNING so a bad key or a blocked
        # endpoint surfaces here instead of as a silently dead tunnel.
        deadline = time.monotonic() + _START_TIMEOUT
        while time.monotonic() < deadline:
            state = _service_state()
            if state == "RUNNING":
                self._profile = profile
                log.info("AmneziaWG tunnel is up")
                return
            if state == "ABSENT":
                raise AwgEngineError(
                    "AmneziaWG tunnel service stopped right after starting — "
                    "check the profile's keys and endpoint."
                )
            time.sleep(_POLL)

        self.stop()
        raise AwgEngineError("AmneziaWG tunnel did not come up within 12 seconds.")

    def stop(self) -> None:
        exe = amneziawg_path()
        if exe is None or _service_state() == "ABSENT":
            self._profile = None
            return

        log.info("Removing the AmneziaWG tunnel service")
        _run([str(exe), "/uninstalltunnelservice", AMNEZIAWG_TUNNEL_NAME])

        # Uninstall is asynchronous. The adapter keeps the default route until
        # the service is really gone, so returning early would leave the machine
        # routing through an adapter with no tunnel behind it.
        deadline = time.monotonic() + _STOP_TIMEOUT
        while time.monotonic() < deadline:
            if _service_state() == "ABSENT":
                break
            time.sleep(_POLL)
        else:
            log.warning("Tunnel service still present after %.0fs", _STOP_TIMEOUT)

        self._profile = None
