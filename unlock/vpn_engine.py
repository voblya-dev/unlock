"""Runs a user-supplied VPN profile through a bundled proxy engine.

Two engines, picked by protocol: sing-box for the v2ray family (vless, vmess,
trojan, shadowsocks, hysteria2) and wireproxy for WireGuard and AmneziaWG.
Both are bundled, and both are also looked for next to the .exe so a newer
build can replace them without rebuilding the app.

Either way the profile is exposed as a local SOCKS + HTTP pair rather than a
TUN device. No driver, no elevation beyond what winws already needs, and the
Windows system proxy can be pointed at it so ordinary apps follow along.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .split_tunnel import SplitTunnelingManager

from .constants import (
    SINGBOX_SEARCH_DIRS,
    VPN_CONFIG_PATH,
    VPN_HTTP_PORT,
    VPN_SOCKS_PORT,
    VPN_TUN_ADDRESS,
    VPN_TUN_CONFIG_PATH,
    VPN_TUN_MTU,
    WIREPROXY_CONFIG_PATH,
    WIREPROXY_SEARCH_DIRS,
    XRAY_CONFIG_PATH,
    XRAY_SEARCH_DIRS,
)
from .logger import get_logger
from .vpn_links import Profile

log = get_logger("vpn")

_CREATE_NO_WINDOW = 0x08000000
_SETTLE_TIMEOUT = 3.0
_SETTLE_POLL = 0.05

# Protocols wireproxy handles; everything else goes to sing-box.
_WIREGUARD_PROTOCOLS = ("wireguard", "amneziawg")


class VpnEngineError(RuntimeError):
    pass


def _find(directories, filename: str):
    for directory in directories:
        candidate = directory / filename
        if candidate.exists():
            return candidate
    return None


def singbox_path():
    """Locate sing-box.exe now, not at import time.

    The bundled copy can be superseded by one dropped next to the .exe, and the
    user may well do that while Unlock is already open — caching the answer
    would make that require a restart for no reason.
    """
    return _find(SINGBOX_SEARCH_DIRS, "sing-box.exe")


def wireproxy_path():
    return _find(WIREPROXY_SEARCH_DIRS, "wireproxy.exe")


def xray_path():
    return _find(XRAY_SEARCH_DIRS, "xray.exe")


def engine_for(profile: Profile) -> str:
    if profile.protocol in _WIREGUARD_PROTOCOLS:
        return "wireproxy"
    return "xray" if profile.outbound.get("_xray") else "sing-box"


def build_config(profile: Profile) -> dict:
    """sing-box config: two local listeners in front of the user's outbound."""
    outbound = dict(profile.outbound)
    outbound["tag"] = "proxy"
    return {
        "log": {"level": "warn", "timestamp": False},
        "dns": {
            "servers": [
                # Resolved through the proxy so the local resolver never sees
                # the hostnames the user is trying to reach. This is the typed
                # server form sing-box 1.12+ requires; the old "address" string
                # is refused outright unless a legacy env var is set.
                {
                    "type": "https",
                    "tag": "remote",
                    "server": "1.1.1.1",
                    "detour": "proxy",
                },
            ],
            "strategy": "prefer_ipv4",
        },
        "inbounds": [
            {
                "type": "socks",
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "listen_port": VPN_SOCKS_PORT,
            },
            {
                "type": "http",
                "tag": "http-in",
                "listen": "127.0.0.1",
                "listen_port": VPN_HTTP_PORT,
            },
        ],
        "outbounds": [
            outbound,
            {"type": "direct", "tag": "direct"},
        ],
        "route": {
            "rules": [
                # Sniffing moved out of the inbound and into a route action.
                {"inbound": ["socks-in", "http-in"], "action": "sniff"},
                # Anything aimed at the machine itself stays off the tunnel,
                # otherwise the Telegram bridge would loop back through the VPN.
                {"ip_is_private": True, "outbound": "direct"},
            ],
            "final": "proxy",
        },
    }


def build_xray_config(profile: Profile) -> dict:
    """Xray config for VLESS mKCP and XHTTP links.

    Those transports are intentionally unsupported by sing-box. Xray exposes
    the same local SOCKS/HTTP ports, so the rest of Unlock (TUN, system proxy
    and traffic stats) continues to work without a separate UI path.
    """
    settings = profile.outbound.get("_xray") or {}
    stream = dict(settings.get("stream") or {})
    user = {
        "id": profile.outbound["uuid"],
        "encryption": settings.get("encryption") or "none",
    }
    if profile.outbound.get("flow"):
        user["flow"] = profile.outbound["flow"]
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": VPN_SOCKS_PORT,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
                "tag": "socks-in",
            },
            {
                "listen": "127.0.0.1",
                "port": VPN_HTTP_PORT,
                "protocol": "http",
                "settings": {},
                "tag": "http-in",
            },
        ],
        "outbounds": [
            {
                "protocol": "vless",
                "tag": "proxy",
                "settings": {
                    "vnext": [{
                        "address": profile.server,
                        "port": profile.port,
                        "users": [user],
                    }],
                },
                "streamSettings": stream,
            },
            {"protocol": "freedom", "tag": "direct"},
        ],
        "routing": {"domainStrategy": "AsIs", "rules": []},
    }


def build_wireproxy_config(profile: Profile) -> str:
    """wg-quick-style INI for wireproxy, with the two local listeners appended."""
    settings = profile.outbound
    lines = [
        "[Interface]",
        f"PrivateKey = {settings['private_key']}",
        f"Address = {', '.join(settings.get('address') or ['10.0.0.2/32'])}",
    ]
    dns = settings.get("dns")
    if dns:
        lines.append(f"DNS = {', '.join(dns)}")
    if settings.get("mtu"):
        lines.append(f"MTU = {settings['mtu']}")
    # The obfuscation knobs must sit in [Interface], before the peer section.
    for key, value in (settings.get("awg") or {}).items():
        lines.append(f"{key} = {value}")

    lines += [
        "",
        "[Peer]",
        f"PublicKey = {settings['public_key']}",
        f"Endpoint = {settings['server']}:{settings['server_port']}",
        f"AllowedIPs = {', '.join(settings.get('allowed_ips') or ['0.0.0.0/0'])}",
    ]
    if settings.get("pre_shared_key"):
        lines.append(f"PresharedKey = {settings['pre_shared_key']}")
    if settings.get("keepalive"):
        lines.append(f"PersistentKeepalive = {settings['keepalive']}")

    lines += [
        "",
        "[Socks5]",
        f"BindAddress = 127.0.0.1:{VPN_SOCKS_PORT}",
        "",
        "[http]",
        f"BindAddress = 127.0.0.1:{VPN_HTTP_PORT}",
        "",
    ]
    return "\n".join(lines)


def build_tun_config(
    profile: Profile,
    *,
    split: "SplitTunnelingManager | None" = None,
) -> dict:
    """sing-box config for the TUN adapter that fronts the local proxy.

    ``auto_route`` installs the default route, so every app follows the tunnel
    without knowing anything about proxies — the same thing WireSock does, and
    the reason apps like Telegram Desktop (which ignores the Windows proxy
    setting) work under it but not under a bare SOCKS listener.
    """
    if engine_for(profile) in ("wireproxy", "xray"):
        # wireproxy already terminates the WireGuard session and exposes it as
        # SOCKS, so sing-box only has to hand traffic over. That listener is
        # TCP-only, which the routing rules below have to work around.
        udp_blocked = engine_for(profile) == "wireproxy"
        outbound = {
            "type": "socks",
            "tag": "proxy",
            "server": "127.0.0.1",
            "server_port": VPN_SOCKS_PORT,
            "version": "5",
        }
    else:
        udp_blocked = False
        outbound = dict(profile.outbound)
        outbound["tag"] = "proxy"

    return {
        "log": {"level": "warn", "timestamp": False},
        "dns": {
            "servers": [
                # Resolved over the tunnel, and over HTTPS: wireproxy's SOCKS
                # listener speaks TCP only, so a plain UDP resolver would never
                # get an answer once traffic is routed through it.
                {"type": "https", "tag": "remote", "server": "1.1.1.1", "detour": "proxy"},
            ],
            "strategy": "prefer_ipv4",
            "independent_cache": True,
        },
        "inbounds": [
            {
                "type": "tun",
                "tag": "tun-in",
                "address": [VPN_TUN_ADDRESS],
                "mtu": VPN_TUN_MTU,
                "auto_route": True,
                # strict_route also blocks traffic that bypasses the adapter,
                # which takes winws down with it when the DPI bypass is running.
                "strict_route": False,
                "stack": "gvisor",
            },
        ],
        "outbounds": [
            outbound,
            {"type": "direct", "tag": "direct"},
        ],
        "route": {
            "rules": [
                {"action": "sniff"},
                # Every DNS query on the machine is answered over the tunnel.
                # Without this apps resolve through the ISP's resolver, which
                # both leaks the lookup and hands back addresses picked for the
                # wrong country.
                {"protocol": "dns", "action": "hijack-dns"},
                # The tunnel's own packets must not re-enter the adapter, and
                # neither must anything aimed at this machine — the Telegram
                # bridge and winws both listen on loopback.
                {"ip_is_private": True, "outbound": "direct"},
                # wireproxy's own UDP to the WireGuard endpoint must not be
                # routed back into the adapter it is feeding.
                {"process_name": ["wireproxy.exe", "xray.exe"], "outbound": "direct"},
                # wireproxy's SOCKS listener speaks TCP only, so UDP cannot
                # cross it. Refusing it outright makes browsers and Telegram
                # fall back to TCP immediately instead of waiting out a
                # timeout on every QUIC attempt.
                *([{"network": "udp", "action": "reject"}] if udp_blocked else []),
                # Per-app / per-domain / per-IP split tunnel rules, if any.
                *(split.singbox_route_rules() if split else []),
            ],
            "auto_detect_interface": True,
            "final": (split.whitelist_final_outbound() or "proxy") if split else "proxy",
        },
    }


class VpnEngine:
    """Starts/stops one engine process for the selected profile."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._tun_proc: subprocess.Popen | None = None
        self._profile: Profile | None = None
        self._tail: list[str] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------- state

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def tun_running(self) -> bool:
        return self._tun_proc is not None and self._tun_proc.poll() is None

    @property
    def profile(self) -> Profile | None:
        return self._profile if self.running else None

    @property
    def socks_port(self) -> int:
        return VPN_SOCKS_PORT

    @property
    def http_port(self) -> int:
        return VPN_HTTP_PORT

    # ------------------------------------------------------------- control

    def _command(self, profile: Profile) -> list[str]:
        """Write the engine's config file and return the argv to run it."""
        if engine_for(profile) == "wireproxy":
            exe = wireproxy_path()
            if exe is None:
                raise VpnEngineError(
                    f"wireproxy.exe not found in {WIREPROXY_SEARCH_DIRS[0]}. "
                    "It ships with Unlock — reinstall, or download it from "
                    "github.com/artem-russkikh/wireproxy-awg."
                )
            WIREPROXY_CONFIG_PATH.write_text(
                build_wireproxy_config(profile), encoding="utf-8"
            )
            return [str(exe), "-c", str(WIREPROXY_CONFIG_PATH)]

        if engine_for(profile) == "xray":
            exe = xray_path()
            if exe is None:
                raise VpnEngineError(
                    f"xray.exe not found in {XRAY_SEARCH_DIRS[0]}. "
                    "It is required for VLESS mKCP and XHTTP links — reinstall Unlock."
                )
            XRAY_CONFIG_PATH.write_text(
                json.dumps(build_xray_config(profile), indent=2), encoding="utf-8"
            )
            return [str(exe), "run", "-c", str(XRAY_CONFIG_PATH)]

        exe = singbox_path()
        if exe is None:
            raise VpnEngineError(
                f"sing-box.exe not found in {SINGBOX_SEARCH_DIRS[0]}. "
                "It ships with Unlock — reinstall, or download it from "
                "github.com/SagerNet/sing-box."
            )
        VPN_CONFIG_PATH.write_text(
            json.dumps(build_config(profile), indent=2), encoding="utf-8"
        )
        return [str(exe), "run", "-c", str(VPN_CONFIG_PATH)]

    def start(self, profile: Profile, *, tun: bool = False,
              split: "SplitTunnelingManager | None" = None) -> None:
        """Bring the tunnel up, optionally behind a TUN adapter.

        ``tun`` adds a second sing-box process that owns a virtual adapter and
        forwards into the proxy the first one exposes. Two processes rather than
        one because wireproxy is the only thing here that speaks AmneziaWG, and
        sing-box is the only thing that can create the adapter.
        """
        with self._lock:
            if self.running:
                self._stop_locked()

            argv = self._command(profile)
            engine = engine_for(profile)
            log.info(
                "Starting %s for '%s' (%s)", engine, profile.name, profile.endpoint
            )

            self._tail = []
            self._proc = self._spawn(argv, engine)
            self._profile = profile

            # A bad outbound makes the engine exit during config validation;
            # catch that here rather than reporting a tunnel that is not there.
            deadline = time.monotonic() + _SETTLE_TIMEOUT
            while time.monotonic() < deadline:
                if self._proc.poll() is not None:
                    reason = self._tail[-1] if self._tail else f"exit code {self._proc.returncode}"
                    self._proc = None
                    self._profile = None
                    raise VpnEngineError(f"{engine} quit: {reason}")
                time.sleep(_SETTLE_POLL)

            if tun:
                try:
                    self._start_tun(profile, split=split)
                except VpnEngineError:
                    self._stop_locked()
                    raise

    def _spawn(self, argv: list[str], engine: str) -> subprocess.Popen:
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(WIREPROXY_CONFIG_PATH.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=_CREATE_NO_WINDOW,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise VpnEngineError(f"Failed to launch {engine}: {exc}") from exc

        threading.Thread(
            target=self._drain_output, args=(proc,), daemon=True
        ).start()
        return proc

    def _start_tun(self, profile: Profile,
                   *, split: "SplitTunnelingManager | None" = None) -> None:
        exe = singbox_path()
        if exe is None:
            raise VpnEngineError(
                f"sing-box.exe not found in {SINGBOX_SEARCH_DIRS[0]} — "
                "it is what creates the TUN adapter."
            )
        VPN_TUN_CONFIG_PATH.write_text(
            json.dumps(build_tun_config(profile, split=split), indent=2), encoding="utf-8"
        )
        log.info("Starting the TUN adapter")
        self._tun_proc = self._spawn(
            [str(exe), "run", "-c", str(VPN_TUN_CONFIG_PATH)], "sing-box (TUN)"
        )

        deadline = time.monotonic() + _SETTLE_TIMEOUT
        while time.monotonic() < deadline:
            if self._tun_proc.poll() is not None:
                reason = self._tail[-1] if self._tail else f"exit code {self._tun_proc.returncode}"
                self._tun_proc = None
                if "Access is denied" in reason:
                    reason = "creating the adapter needs Administrator rights"
                raise VpnEngineError(f"TUN mode failed: {reason}")
            time.sleep(_SETTLE_POLL)

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        # The adapter goes first: while it holds the default route, tearing the
        # proxy down underneath it would black-hole every app on the machine.
        self._tun_proc = self._terminate(self._tun_proc, "TUN adapter")
        self._proc = self._terminate(self._proc, "VPN engine")
        self._profile = None

    @staticmethod
    def _terminate(proc: subprocess.Popen | None, what: str) -> None:
        if proc is None:
            return None
        log.info("Stopping the %s", what)
        try:
            proc.terminate()
            proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            log.warning("%s did not exit, killing", what)
            proc.kill()
            # kill() is asynchronous on Windows; wait so the process is really
            # gone before the caller moves on to tearing the app down.
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                log.warning("%s still alive after kill", what)
        except OSError as exc:
            log.warning("Error stopping the %s: %s", what, exc)
        return None

    def _drain_output(self, proc: subprocess.Popen) -> None:
        """Pipe must be read or the engine blocks once the buffer fills."""
        if proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            log.debug("vpn: %s", line)
            # Keep only the last few lines: enough to explain a startup failure
            # without holding a whole session's logs in memory.
            self._tail = [*self._tail[-4:], line]
