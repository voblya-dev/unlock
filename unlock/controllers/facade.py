"""The object the GUI talks to: three controllers behind one façade.

Nothing here starts an engine directly. What lives at this level is the part that
genuinely spans them — the shared state machine behind the power button, the
crash watchdog, the post-connect self-test, and the protection-time counter —
plus straight delegation for everything the UI already called by name.
"""

from __future__ import annotations

from PyQt6.QtCore import QThread, QTimer, pyqtSignal

from .. import sounds, system_proxy
from ..app_update import UpdateInfo
from ..config import Config
from ..constants import (
    UPDATE_CHECK_INTERVAL_H,
    WATCHDOG_INTERVAL_MS,
    WATCHDOG_MAX_RESTARTS,
)
from ..dpi_engine import DpiEngineError, is_admin
from ..selftest import SelfTestReport
from ..site_lists import SiteListManager
from ..telegram_proxy import TelegramProxyError
from ..uptime import UptimeTracker, elapsed_since, now_stamp
from ..vpn_engine import VpnEngineError
from ..vpn_links import Profile
from .base import BUSY_STATES, State, WorkerOwner, log
from .checks import BootstrapWorker, RecoveryWorker, SelfTestWorker, UpdateCheckWorker
from .dpi import BenchmarkWorker, DpiController
from .telegram import TelegramController
from .vpn import VpnController

# Labels used in watchdog messages and restart bookkeeping.
_DPI = "DPI bypass"
_BRIDGE = "Telegram bridge"

# How long a connect will wait for the zapret pack update to settle. Swapping the
# pack directory cannot work while winws is running out of it, so the update goes
# first — but never at the cost of leaving the user unprotected for longer than
# this if the download is slow or stalled.
_PACK_GRACE_MS = 8000


class ConnectWorker(QThread):
    """Starts every enabled engine, reporting one line for the status bar."""

    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, controller: "Controller") -> None:
        super().__init__()
        self._c = controller

    def run(self) -> None:
        try:
            parts = self._c.start_engines()
            self.finished_ok.emit(" + ".join(parts) if parts else "Nothing enabled")
        except (DpiEngineError, TelegramProxyError, VpnEngineError, RuntimeError) as exc:
            self._c.stop_engines()
            self.failed.emit(str(exc))


class DisconnectWorker(QThread):
    finished_ok = pyqtSignal()

    def __init__(self, controller: "Controller") -> None:
        super().__init__()
        self._c = controller

    def run(self) -> None:
        self._c.stop_engines()
        self.finished_ok.emit()


class Controller(WorkerOwner):
    """Composes the three controllers and owns what is shared between them."""

    state_changed = pyqtSignal(object)      # State
    vpn_state_changed = pyqtSignal(object)  # State, for the VPN alone
    status_message = pyqtSignal(str)
    latency_changed = pyqtSignal(float)
    loss_changed = pyqtSignal(float)        # percent of packets lost
    vpn_latency_changed = pyqtSignal(float)
    vpn_loss_changed = pyqtSignal(float)
    stats_changed = pyqtSignal(object)      # tunnel_stats.Snapshot | None
    benchmark_progress = pyqtSignal(int, str)
    benchmark_done = pyqtSignal(object)     # BenchmarkReport
    error = pyqtSignal(str)
    # --- reliability and housekeeping
    selftest_done = pyqtSignal(object)      # selftest.SelfTestReport
    engine_crashed = pyqtSignal(str)        # label; a restart is being attempted
    engine_restored = pyqtSignal(str)       # label; it is running again
    engine_lost = pyqtSignal(str)           # label; gave up after N restarts
    update_available = pyqtSignal(object)   # app_update.UpdateInfo
    pack_updated = pyqtSignal(str)          # zapret pack version now installed

    def __init__(self) -> None:
        super().__init__()
        self.config = Config()
        sounds.set_enabled(self.config.flag("sounds"))
        # Site rules have an independent, unencrypted file because they are
        # consumed by winws directly and must survive application updates.
        self.site_lists = SiteListManager()

        self.dpi = DpiController(self.config, self.site_lists)
        self.telegram = TelegramController(self.config)
        self.vpn = VpnController(self.config)
        self.uptime = UptimeTracker(self.config)

        self._state = State.IDLE
        self._shut_down = False
        self._pack_pending = False
        self._connect_when_ready = False
        self._restarts: dict[str, int] = {}
        self._recovering: set[str] = set()
        self._lost: set[str] = set()

        self._watchdog = QTimer(self)
        self._watchdog.setInterval(WATCHDOG_INTERVAL_MS)
        self._watchdog.timeout.connect(self._check_engines)

        self._wire()
        # A previous run that was killed before it could clean up leaves the
        # machine pointed at a local port that no longer listens, which looks to
        # the user like the network itself died.
        if system_proxy.restore_orphaned():
            self.status_message.emit("Restored the system proxy left by a previous run")

    def _wire(self) -> None:
        """Re-emit what the UI subscribes to, so nothing has to know the split."""
        self.dpi.status_message.connect(self.status_message)
        self.dpi.error.connect(self.error)
        self.dpi.latency_changed.connect(self.latency_changed)
        self.dpi.loss_changed.connect(self.loss_changed)
        self.dpi.benchmark_progress.connect(self.benchmark_progress)
        self.dpi.benchmark_done.connect(self._on_benchmark_done)
        self.dpi.benchmark_failed.connect(self._on_benchmark_failed)

        self.telegram.status_message.connect(self.status_message)
        self.telegram.error.connect(self.error)
        self.telegram.bridge_lost.connect(self._on_bridge_lost)

        self.vpn.state_changed.connect(self.vpn_state_changed)
        self.vpn.status_message.connect(self.status_message)
        self.vpn.error.connect(self.error)
        self.vpn.latency_changed.connect(self.vpn_latency_changed)
        self.vpn.loss_changed.connect(self.vpn_loss_changed)
        self.vpn.stats_changed.connect(self.stats_changed)

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
            log.info("State -> %s", state.name)
            self.state_changed.emit(state)

    @property
    def vpn_state(self) -> State:
        return self.vpn.state

    @property
    def vpn_is_active(self) -> bool:
        return self.vpn.is_active

    def active_summary(self) -> str:
        parts = [part for part in (self.dpi.summary(), self.telegram.summary()) if part]
        return " | ".join(parts) or "Inactive"

    def uptime_phrase(self, lang: str = "en") -> str:
        """«Вы защищены уже 47 дней» — total protected time, across sessions."""
        return self.uptime.phrase(lang)

    # ------------------------------------------------------------- DPI

    @property
    def game_filter(self) -> bool:
        return self.dpi.game_filter

    def set_game_filter(self, enabled: bool) -> bool:
        """Persist the setting. True means winws has to be relaunched."""
        if not self.dpi.set_game_filter(enabled):
            return False
        self.restart_dpi(success_message="Filter scope updated")
        return True
    def set_dpi_strategy(self, name: str | None) -> bool:
        """Persist a preset and immediately apply it when winws is running.

        Zapret-GUI restarts its service on a profile switch. Merely updating a
        combo box made Unlock show the new name while winws carried on with the
        old argument vector until some later reconnect.
        """
        if name is not None and not self.dpi.is_available(name):
            self.error.emit("Selected DPI strategy is not available")
            return False
        if name == self.dpi.selected:
            return True
        self.dpi.select(name)
        if self.dpi.running:
            self.restart_dpi(success_message="DPI profile switched")
        elif self._state in (State.IDLE, State.ERROR) and self.dpi.enabled:
            # Match Zapret-GUI's profile picker: choosing a profile is enough to
            # begin protection, not merely to stage it for a later click.
            self.connect()
        else:
            self.status_message.emit("DPI profile saved — applies at next bypass start")
        return True

    def restart_dpi(self, *, success_message: str | None = None) -> None:
        """Re-launch only winws so a changed argument vector takes effect.

        The bridge and the tunnel are untouched, and the run is reported as a
        restart rather than a fresh connect: from the user's side protection
        never lapsed, so there is no chime, no self-test and no uptime reset.
        """
        if not self.dpi.running:
            return
        message = success_message or "Bypass restarted"
        self._set_state(State.CONNECTING)
        self.status_message.emit("Applying the new filter…")

        worker = self.dpi.restart_worker()
        worker.finished_ok.connect(lambda _summary: self._on_dpi_restarted(message))
        worker.failed.connect(self._on_connect_failed)
        worker.start()

    def apply_site_lists(self) -> None:
        """Apply a saved site-list edit without disturbing the bridge or tunnel."""
        if self.dpi.running:
            self.restart_dpi(success_message="DPI restarted — changes applied")
        else:
            self.status_message.emit("List saved — applies at next bypass start")

    @property
    def needs_benchmark(self) -> bool:
        return self.dpi.needs_benchmark
    # ------------------------------------------------------------- Telegram

    @property
    def fake_tls(self) -> bool:
        return self.telegram.fake_tls

    def set_fake_tls(self, enabled: bool) -> bool:
        """Switch the handshake flavour. Returns the mode actually in force."""
        return self.telegram.set_fake_tls(enabled)

    @property
    def proxy_link(self) -> str | None:
        """The tg:// link, for the copy button on the Telegram card."""
        return self.telegram.proxy_link

    def offer_telegram_proxy(self) -> bool:
        return self.telegram.offer_proxy()

    # ------------------------------------------------------------- VPN
    #
    # Delegation kept under the names the tray and the launcher already use. The
    # tunnel has its own state machine and its own switch: it is not part of the
    # power button, and stopping the bypass does not take it down.

    def autostart_vpn(self) -> None:
        self.vpn.autostart()

    def vpn_toggle(self) -> None:
        self.vpn.toggle()

    def vpn_connect(self) -> None:
        self.vpn.connect()

    def vpn_disconnect(self) -> None:
        self.vpn.disconnect()

    def vpn_reconnect(self) -> None:
        self.vpn.reconnect()

    def vpn_profiles(self) -> list[Profile]:
        return self.vpn.profiles()

    def active_vpn_profile(self) -> Profile | None:
        return self.vpn.active_profile()

    def save_vpn_profiles(self, profiles: list[Profile]) -> None:
        self.vpn.save_profiles(profiles)
    def add_vpn_profiles(self, profiles: list[Profile]) -> list[Profile]:
        return self.vpn.add_profiles(profiles)

    def remove_vpn_profile(self, profile_id: str) -> None:
        self.vpn.remove_profile(profile_id)

    def set_active_vpn_profile(self, profile_id: str | None) -> None:
        self.vpn.set_active_profile(profile_id)

    # ------------------------------------------------------------- the button

    def toggle(self) -> None:
        if self._state in BUSY_STATES:
            return
        if self.is_active:
            self.disconnect()
        else:
            self.connect()

    def connect(self) -> None:
        if self._state in (State.CONNECTING, State.ACTIVE):
            # A second click used to start a second set of engines on top of the
            # first, leaving two winws processes fighting over the filter driver.
            return
        if not self._preflight():
            return
        if self._pack_pending:
            # The pack directory cannot be swapped while winws is running out of
            # it, so the update goes first — under the _PACK_GRACE_MS cap, which
            # is what stops a stalled download from withholding protection.
            self._connect_when_ready = True
            self.status_message.emit("Updating the zapret pack…")
            return

        self._set_state(State.CONNECTING)
        self.status_message.emit("Starting bypass…")

        worker = ConnectWorker(self)
        worker.finished_ok.connect(self._on_connected)
        worker.failed.connect(self._on_connect_failed)
        self._track(worker)
        worker.start()

    def _preflight(self) -> bool:
        """Refuse a connect that cannot succeed, with the reason the user needs."""
        if self.dpi.benchmark_pending:
            self.error.emit("Still finishing the cancelled test — try again in a moment.")
            return False
        if not (self.dpi.enabled or self.telegram.enabled):
            self.error.emit("Both bypass engines are disabled in Settings.")
            return False
        if self.dpi.enabled and not is_admin():
            self.error.emit("Restart Unlock as Administrator — WinDivert needs elevation.")
            return False
        return True
    def disconnect(self) -> None:
        if self._state in (State.IDLE, State.DISCONNECTING):
            return
        self._connect_when_ready = False
        self._set_state(State.DISCONNECTING)
        self.status_message.emit("Stopping bypass…")
        self._watchdog.stop()
        self.dpi.stop_latency_monitor()
        # Written here rather than on a timer: the counter is in the DPAPI-sealed
        # config, so persisting it every second would mean a re-encrypt per tick.
        self.uptime.stop()

        worker = DisconnectWorker(self)
        worker.finished_ok.connect(self._on_disconnected)
        self._track(worker)
        worker.start()

    # ------------------------------------------------------------- engine glue

    def start_engines(self) -> list[str]:
        """Start every enabled engine. Runs on ConnectWorker's thread.

        The tunnel is deliberately absent: it has its own switch, so a user can
        run it alone or run the bypass without it.
        """
        started: list[str] = []
        if self.dpi.enabled:
            started.append(self.dpi.start_blocking())
        if self.telegram.enabled:
            started.append(self.telegram.start_blocking())
        return started

    def stop_engines(self) -> None:
        """Stop the bypass engines, leaving the tunnel as the user set it."""
        self.telegram.stop()
        self.dpi.stop()

    # ------------------------------------------------------------- benchmark

    def run_benchmark(self) -> BenchmarkWorker:
        # Every strategy is tried in turn against a live winws, so nothing else
        # may hold the filter driver while the run is in progress.
        self._watchdog.stop()
        self.uptime.stop()
        self.stop_engines()
        self._set_state(State.BENCHMARKING)
        return self.dpi.start_benchmark(self.telegram)

    def abort_benchmark(self) -> None:
        if not self.dpi.abort_benchmark():
            return
        self._set_state(State.IDLE)
        self.status_message.emit("Testing cancelled — pick a strategy in Settings")
    def _on_benchmark_done(self, report: object) -> None:
        # The DPI controller has already persisted the winner and reported it;
        # only the shared state machine is left to unwind.
        self._set_state(State.IDLE)
        self.benchmark_done.emit(report)

    def _on_benchmark_failed(self, message: str) -> None:
        self._set_state(State.IDLE)
        self.error.emit(f"Benchmark failed: {message}")

    # ------------------------------------------------------------- startup

    def start_background_tasks(self) -> None:
        """Begin the slow, optional startup work. Call once the window is up.

        Neither task is on the critical path: the bundled pack is already
        installed synchronously by ``zapret_update.ensure_local_pack()``, and the
        version check is advisory.
        """
        self._start_pack_update()
        self._maybe_check_update()

    def _start_pack_update(self) -> None:
        self._pack_pending = True
        worker = BootstrapWorker()
        worker.finished_ok.connect(self._on_pack_ready)
        worker.failed.connect(self._on_pack_failed)
        self._track(worker)
        worker.start()
        # A connect must not wait on a download that has stalled. After the grace
        # period the local pack is good enough — it is a verified one.
        QTimer.singleShot(_PACK_GRACE_MS, self._pack_grace_expired)

    def _on_pack_ready(self, result: object) -> None:
        self._pack_pending = False
        version = getattr(result, "version", "")
        if getattr(result, "source", "") == "github" and version:
            self.status_message.emit(f"Zapret pack updated — {version}")
            self.pack_updated.emit(version)
        self._flush_deferred_connect()

    def _on_pack_failed(self, message: str) -> None:
        # Not an error path: the verified local pack is still in place, which is
        # the entire reason it is installed before the network is touched.
        log.info("Zapret update unavailable, keeping the local pack: %s", message)
        self._pack_pending = False
        self._flush_deferred_connect()
    def _pack_grace_expired(self) -> None:
        if not self._pack_pending:
            return
        log.warning("Zapret update still running after %d ms; using the local pack",
                    _PACK_GRACE_MS)
        self._pack_pending = False
        self._flush_deferred_connect()

    def _flush_deferred_connect(self) -> None:
        if self._connect_when_ready:
            self._connect_when_ready = False
            self.connect()

    def _maybe_check_update(self) -> None:
        """Compare the running version against the latest tag, at most daily."""
        if not self.config.flag("app_update_check"):
            return
        last = self.config.get("last_app_update_check_utc")
        if last and elapsed_since(last) < UPDATE_CHECK_INTERVAL_H * 3600:
            return
        worker = UpdateCheckWorker()
        worker.finished_ok.connect(self._on_update_checked)
        self._track(worker)
        worker.start()

    def _on_update_checked(self, info: UpdateInfo | None) -> None:
        # Only reached on a successful lookup, so a machine that was offline
        # tries again next launch instead of waiting out the whole interval.
        self.config.set("last_app_update_check_utc", now_stamp())
        if info is not None and info.available:
            log.info("Update available: %s -> %s", info.current, info.latest)
            self.update_available.emit(info)

    # ------------------------------------------------------------- self-test

    def _run_selftest(self) -> None:
        if not self.config.flag("connectivity_check"):
            return
        port = self.telegram.port if self.telegram.running else None
        worker = SelfTestWorker(port)
        worker.finished_ok.connect(self._on_selftest_done)
        self._track(worker)
        worker.start()

    def _on_selftest_done(self, report: SelfTestReport) -> None:
        # Advisory only. A site can be down on its own, and on some networks only
        # one of the two is blocked in the first place, so a failed probe is not
        # a reason to tear down a bypass that is otherwise working.
        if report.ok:
            self.status_message.emit(f"Verified — {report.summary()}")
        else:
            self.status_message.emit(f"Still blocked — {report.summary()}")
        self.selftest_done.emit(report)
    # ------------------------------------------------------------- watchdog

    def _check_engines(self) -> None:
        """Notice an engine that died on its own. Only meaningful while ACTIVE.

        winws is a child process that can be killed by an antivirus, a driver
        reload or a Windows update, and the bridge can lose its listener. Neither
        tells anyone: before this existed the UI kept reading ACTIVE over a dead
        process, which is the worst possible failure for a bypass tool.
        """
        if self._state is not State.ACTIVE:
            return
        for label, enabled, running in (
            (_DPI, self.dpi.enabled, self.dpi.running),
            (_BRIDGE, self.telegram.enabled, self.telegram.running),
        ):
            if not enabled or running:
                continue
            if label in self._recovering or label in self._lost:
                continue
            self._handle_crash(label)

    def _handle_crash(self, label: str) -> None:
        log.warning("%s stopped unexpectedly", label)
        attempts = self._restarts.get(label, 0) + 1
        if not self.config.flag("crash_recovery") or attempts > WATCHDOG_MAX_RESTARTS:
            self._give_up(label)
            return
        self._restarts[label] = attempts
        self._recovering.add(label)
        self.engine_crashed.emit(label)

        restart = self.dpi.restart_blocking if label == _DPI else self.telegram.restart_blocking
        worker = RecoveryWorker(label, restart)
        worker.finished_ok.connect(self._on_recovered)
        worker.failed.connect(self._on_recovery_failed)
        self._track(worker)
        worker.start()

    def _on_recovered(self, label: str) -> None:
        self._recovering.discard(label)
        log.info("%s restarted after a crash", label)
        self.engine_restored.emit(label)
        self.status_message.emit(f"{label} recovered")

    def _on_recovery_failed(self, label: str, message: str) -> None:
        self._recovering.discard(label)
        log.warning("Could not bring %s back: %s", label, message)
        if self._restarts.get(label, 0) >= WATCHDOG_MAX_RESTARTS:
            self._give_up(label)
        # Otherwise the next tick tries again, up to the restart budget.
    def _give_up(self, label: str) -> None:
        """Report an engine as gone and stop retrying it for this session."""
        if label in self._lost:
            return
        self._lost.add(label)
        self._recovering.discard(label)
        log.error("Giving up on %s", label)
        self.engine_lost.emit(label)
        if self.dpi.running or self.telegram.running:
            # The other engine is still up, so the user keeps partial protection;
            # the notification is what tells them which half is missing.
            self.status_message.emit(f"{label} is down — {self.active_summary()}")
            return
        # Nothing is left running: the button must stop claiming protection.
        self._watchdog.stop()
        self.dpi.stop_latency_monitor()
        self.uptime.stop()
        self._set_state(State.ERROR)
        self.status_message.emit("Bypass stopped")

    def _on_bridge_lost(self, message: str) -> None:
        """The bridge could not be rebound after a settings change."""
        self.error.emit(message)
        self._give_up(_BRIDGE)

    # ------------------------------------------------------------- slots

    def _on_connected(self, summary: str) -> None:
        self._set_state(State.ACTIVE)
        self.status_message.emit(f"Active — {summary}")
        self.dpi.start_latency_monitor()
        # A fresh connect earns a fresh restart budget: the counters exist to
        # stop a boot loop, not to hold a failure from an hour ago against it.
        self._restarts.clear()
        self._recovering.clear()
        self._lost.clear()
        self._watchdog.start()
        self.uptime.start()
        sounds.connected()
        self._run_selftest()

    def _on_dpi_restarted(self, message: str) -> None:
        """Finish a targeted restart without announcing a whole reconnect."""
        self._set_state(State.ACTIVE)
        self.status_message.emit(message)
        self.dpi.start_latency_monitor()
        if not self._watchdog.isActive():
            self._watchdog.start()
    def _on_connect_failed(self, message: str) -> None:
        # Left in ERROR rather than bounced straight back to IDLE: both
        # transitions used to happen in this one slot, so no UI could ever
        # observe the failure and the button looked as if nothing was pressed.
        # The next connect() leaves the state.
        self._watchdog.stop()
        self.dpi.stop_latency_monitor()
        self.uptime.stop()
        self._set_state(State.ERROR)
        self.status_message.emit("Failed to start")
        sounds.failed()
        self.error.emit(message)

    def _on_disconnected(self) -> None:
        self._set_state(State.IDLE)
        self.status_message.emit("Disconnected")
        sounds.disconnected()

    # ------------------------------------------------------------- shutdown

    def shutdown(self) -> None:
        if self._shut_down:
            return
        self._shut_down = True
        self._watchdog.stop()
        # Order matters: the protected time is written before the engines go, so a
        # crash during teardown cannot cost the user their streak.
        self.uptime.stop()
        self.vpn.shutdown()
        self.telegram.shutdown()
        self.dpi.shutdown()
        self.join_workers()
        log.info("Controller shut down")

