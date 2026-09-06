"""The VPN half: the tunnel, its counters and the servers the user saved.

Runs on its own switch and its own state machine, independent of the bypass
button: a user can tunnel without the DPI filter, or filter without the tunnel.

There is no VPN page in the current UI — the surface was removed when the app
became bypass-first — so this controller is driven from the tray and from
``autostart()``. It is kept whole rather than deleted because the engines,
profile parsing and split-tunnel routing are the part that is expensive to get
right, and none of it is coupled to the page that used to show it.
"""

from __future__ import annotations

from PyQt6.QtCore import QThread, QTimer, pyqtSignal

from .. import awg_engine, sounds
from ..awg_engine import AwgEngine
from ..config import Config
from ..dpi_engine import is_admin
from ..split_tunnel import SplitTunnelingManager
from ..system_proxy import SystemProxy
from ..tunnel_stats import TunnelStats
from ..vpn_engine import VpnEngine, VpnEngineError
from ..vpn_links import Profile
from .base import BUSY_STATES, PingWorker, State, WorkerOwner, log

_NO_SERVER = "No VPN server selected"


class VpnPingWorker(PingWorker):
    """Round-trip time measured through the tunnel that is currently up.

    Not a probe of the server's own endpoint: WireGuard and AmneziaWG speak UDP,
    so nothing answers a TCP connect there. What is measured instead is a TCP
    handshake to a public address carried over the tunnel, which is the number
    the user actually experiences.

    In TUN mode the connect is made directly and the virtual adapter routes it.
    With wireproxy there is no adapter, so the same handshake is asked for
    through its SOCKS5 port.
    """

    _TARGET = ("1.1.1.1", 443)
    _WARMUP = 4                             # failures tolerated before it routes

    def __init__(self, socks_port: int | None, interval_s: float = 2.0) -> None:
        super().__init__(interval_s, timeout_s=3.0)
        self._socks_port = socks_port

    def _probe(self) -> float:
        host, port = self._TARGET
        if self._socks_port is None:
            return self._connect_ms(host, port)
        return self._socks_ms(host, port)

    def _socks_ms(self, host: str, port: int) -> float:
        import socket
        import struct
        import time

        started = time.perf_counter()
        try:
            with socket.create_connection(
                ("127.0.0.1", self._socks_port), timeout=self._timeout
            ) as sock:
                sock.sendall(b"\x05\x01\x00")
                if sock.recv(2)[:2] != b"\x05\x00":
                    raise OSError("SOCKS5 handshake refused")
                sock.sendall(
                    b"\x05\x01\x00\x01" + socket.inet_aton(host) + struct.pack(">H", port)
                )
                reply = sock.recv(10)
                if len(reply) < 2 or reply[1] != 0:
                    raise OSError("SOCKS5 connect refused")
        except OSError:
            return -1.0
        return (time.perf_counter() - started) * 1000.0


class VpnConnectWorker(QThread):
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, vpn: "VpnController") -> None:
        super().__init__()
        self._vpn = vpn

    def run(self) -> None:
        try:
            self.finished_ok.emit(self._vpn.start_blocking())
        except (VpnEngineError, RuntimeError) as exc:
            self._vpn.stop_blocking()
            self.failed.emit(str(exc))


class VpnDisconnectWorker(QThread):
    finished_ok = pyqtSignal()

    def __init__(self, vpn: "VpnController") -> None:
        super().__init__()
        self._vpn = vpn

    def run(self) -> None:
        self._vpn.stop_blocking()
        self.finished_ok.emit()


class VpnReconnectWorker(QThread):
    """Switch a live tunnel to the currently selected server."""

    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, vpn: "VpnController") -> None:
        super().__init__()
        self._vpn = vpn

    def run(self) -> None:
        try:
            self._vpn.stop_blocking()
            self.finished_ok.emit(self._vpn.start_blocking())
        except (VpnEngineError, RuntimeError) as exc:
            self._vpn.stop_blocking()
            self.failed.emit(str(exc))


class VpnController(WorkerOwner):
    """Tunnel lifecycle, saved servers, live counters and tunnel latency."""

    state_changed = pyqtSignal(object)      # State
    status_message = pyqtSignal(str)
    error = pyqtSignal(str)
    latency_changed = pyqtSignal(float)
    loss_changed = pyqtSignal(float)
    stats_changed = pyqtSignal(object)      # tunnel_stats.Snapshot | None

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.engine = VpnEngine()
        self.awg = AwgEngine()
        self.split_tunnel = SplitTunnelingManager(config)
        self._system_proxy = SystemProxy()
        self._state = State.IDLE
        self._ping_worker: VpnPingWorker | None = None

        # Live tunnel counters. Polled on the UI thread: one named-pipe round
        # trip per second is far too cheap to justify a thread, and the reply is
        # a few hundred bytes.
        self._stats = TunnelStats()
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(1000)
        self._stats_timer.timeout.connect(self._poll_stats)

    # ------------------------------------------------------------- state

    @property
    def state(self) -> State:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state is State.ACTIVE

    def _set_state(self, state: State) -> None:
        if state is not self._state:
            self._state = state
            log.info("VPN state -> %s", state.name)
            self.state_changed.emit(state)

    def _poll_stats(self) -> None:
        self.stats_changed.emit(self._stats.read())

    # ------------------------------------------------------------- profiles

    def profiles(self) -> list[Profile]:
        items = self.config.get("vpn_profiles") or []
        if not isinstance(items, list):
            log.warning("Ignoring malformed VPN profile list")
            return []
        profiles: list[Profile] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                profiles.append(Profile.from_dict(item))
            except (TypeError, ValueError):
                log.warning("Ignoring malformed VPN profile")
        return profiles

    def active_profile(self) -> Profile | None:
        active = self.config.get("vpn_active")
        return next((p for p in self.profiles() if p.id == active), None)

    def save_profiles(self, profiles: list[Profile]) -> None:
        updates: dict = {"vpn_profiles": [p.as_dict() for p in profiles]}
        if not any(p.id == self.config.get("vpn_active") for p in profiles):
            updates["vpn_active"] = profiles[0].id if profiles else None
        self.config.update(updates)

    def add_profiles(self, profiles: list[Profile]) -> list[Profile]:
        """Store new servers, skipping ones already saved. Returns those added."""
        existing = self.profiles()
        known = {(p.protocol, p.server, p.port) for p in existing}
        fresh = [p for p in profiles if (p.protocol, p.server, p.port) not in known]
        if fresh:
            self.save_profiles([*existing, *fresh])
            if self.config.get("vpn_active") is None:
                self.config.set("vpn_active", fresh[0].id)
        return fresh

    def remove_profile(self, profile_id: str) -> None:
        self.save_profiles([p for p in self.profiles() if p.id != profile_id])

    def set_active_profile(self, profile_id: str | None) -> None:
        """Select a server, switching a live tunnel over to it.

        Picking a different server while connected used to change only which one
        the *next* connect would use, so the app kept routing through the old one
        while the UI showed the new name.
        """
        if profile_id == self.config.get("vpn_active"):
            return
        self.config.set("vpn_active", profile_id)
        if profile_id is not None and self._state in (State.ACTIVE, State.CONNECTING):
            log.info("Active server changed while connected — reconnecting")
            self.reconnect()

    # ------------------------------------------------------------- actions

    def autostart(self) -> None:
        """Bring the tunnel up on launch, if the user asked for that."""
        if self.config.flag("enable_vpn") and self.active_profile() is not None:
            self.connect()

    def toggle(self) -> None:
        if self._state in BUSY_STATES:
            return
        if self.is_active:
            self.disconnect()
        else:
            self.connect()

    def connect(self) -> None:
        if self.active_profile() is None:
            self.error.emit(f"{_NO_SERVER} — add one before starting the tunnel.")
            return
        self._set_state(State.CONNECTING)
        self._run(VpnConnectWorker(self))

    def disconnect(self) -> None:
        self._set_state(State.DISCONNECTING)
        worker = VpnDisconnectWorker(self)
        worker.finished_ok.connect(self._on_disconnected)
        self._track(worker)
        worker.start()

    def reconnect(self) -> None:
        """Tear the tunnel down and bring it back up on the current profile.

        Reported as CONNECTING throughout rather than dropping to IDLE first: the
        user asked for a different server, not for the VPN to go off.
        """
        self._set_state(State.CONNECTING)
        self._run(VpnReconnectWorker(self))

    def _run(self, worker: VpnConnectWorker | VpnReconnectWorker) -> None:
        worker.finished_ok.connect(self._on_connected)
        worker.failed.connect(self._on_connect_failed)
        self._track(worker)
        worker.start()

    # ------------------------------------------------------------- engine glue

    def start_blocking(self) -> str:
        profile = self.active_profile()
        if profile is None:
            raise VpnEngineError(f"{_NO_SERVER} — add one before starting the tunnel.")

        tun_requested = self.config.flag("vpn_tun")
        if tun_requested and not is_admin():
            raise VpnEngineError(
                "TUN mode needs Administrator rights; refusing an unsafe proxy fallback"
            )

        split_has_rules = (
            self.split_tunnel.enabled and bool(self.split_tunnel.singbox_route_rules())
        )
        if (
            tun_requested
            and not split_has_rules
            and awg_engine.amneziawg_path() is not None
            and profile.protocol in ("wireguard", "amneziawg")
        ):
            # Amnezia's own client drives a real Wintun adapter, so UDP crosses
            # the tunnel — Discord voice, games, QUIC. The wireproxy+sing-box
            # pairing below cannot do that: it hands traffic over via SOCKS, which
            # carries TCP only. With split-tunnel rules active we fall through to
            # sing-box, because the native AWG client has no routing rule support.
            self.awg.start(profile)
            return profile.name

        self.engine.start(
            profile, tun=tun_requested, split=self.split_tunnel if tun_requested else None
        )
        if tun_requested:
            # The adapter already carries every app, including the ones that
            # ignore the Windows proxy setting; layering the proxy on top would
            # only send their traffic through the tunnel twice.
            return profile.name

        if self.config.flag("vpn_system_proxy"):
            if not self._system_proxy.apply("127.0.0.1", self.engine.http_port):
                self.engine.stop()
                raise VpnEngineError(
                    "Could not apply the system proxy; VPN was stopped to prevent leaks"
                )
        # The Telegram bridge is not carried by proxy mode: it reaches Telegram
        # over its own WebSocket connections, and the Windows proxy setting cannot
        # redirect those. TUN mode is the default precisely because it can.
        log.warning("Proxy mode: the Telegram bridge is not routed through the tunnel")
        return profile.name

    def stop_blocking(self) -> None:
        # The system proxy points at the tunnel's listener, so it has to be
        # released first or every app loses its connection.
        self._system_proxy.restore()
        self.awg.stop()
        self.engine.stop()

    # ------------------------------------------------------------- monitors

    def _start_ping_monitor(self) -> None:
        self._stop_ping_monitor()
        # awg owns a real adapter, so its traffic needs no proxy hop; the
        # sing-box/wireproxy path only exists behind its SOCKS port.
        socks = None if self.awg.running else self.engine.socks_port
        worker = VpnPingWorker(socks)
        worker.measured.connect(self.latency_changed)
        worker.loss_measured.connect(self.loss_changed)
        self._ping_worker = worker
        worker.start()

    def _stop_ping_monitor(self) -> None:
        if self._ping_worker is not None:
            worker, self._ping_worker = self._ping_worker, None
            worker.stop()
            # The worker sleeps in slices; let it leave the loop before this
            # thread races ahead into a state change and a repaint.
            worker.wait(150)
            if worker.isRunning():
                self._track(worker)
        self.latency_changed.emit(-1.0)

    def _stop_stats(self) -> None:
        self._stats_timer.stop()
        self._stats.reset()
        self._stop_ping_monitor()
        # One last emit so the panel clears instead of freezing on the final
        # reading of a tunnel that is no longer up.
        self.stats_changed.emit(None)

    # ------------------------------------------------------------- slots

    def _on_connected(self, name: str) -> None:
        self._set_state(State.ACTIVE)
        self.status_message.emit(f"VPN connected — {name}")
        # Counters belong to the tunnel that just came up, not the one before it.
        self._stats.reset()
        self._stats_timer.start()
        self._start_ping_monitor()
        sounds.connected()

    def _on_connect_failed(self, message: str) -> None:
        self._set_state(State.IDLE)
        self._stop_stats()
        sounds.failed()
        self.error.emit(message)

    def _on_disconnected(self) -> None:
        self._set_state(State.IDLE)
        self.status_message.emit("VPN disconnected")
        self._stop_stats()
        sounds.disconnected()

    def shutdown(self) -> None:
        self._stats_timer.stop()
        self._stop_ping_monitor()
        self.stop_blocking()
        self.join_workers()
