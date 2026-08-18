"""Lifecycle management for the bundled winws.exe DPI-bypass engine."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import subprocess
import threading
import time
from collections import deque

from .constants import STRATEGY_SETTLE_POLL, STRATEGY_SETTLE_TIMEOUT, WINWS_EXE, ZAPRET_DIR
from .logger import get_logger
from .strategies import DpiStrategy

log = get_logger("dpi")

# Hide the console window of the child process.
_CREATE_NO_WINDOW = 0x08000000

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kernel32() -> ctypes.WinDLL:
    """kernel32 with explicit signatures.

    The defaults truncate a returned HANDLE to a 32-bit int, which silently
    corrupts every handle above 2 GB on 64-bit Windows.
    """
    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    lib.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    lib.CreateJobObjectW.restype = wintypes.HANDLE
    lib.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD
    ]
    lib.SetInformationJobObject.restype = wintypes.BOOL
    lib.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    lib.AssignProcessToJobObject.restype = wintypes.BOOL
    lib.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    lib.OpenProcess.restype = wintypes.HANDLE
    lib.CloseHandle.argtypes = [wintypes.HANDLE]
    lib.CloseHandle.restype = wintypes.BOOL
    return lib


def _create_kill_on_close_job() -> wintypes.HANDLE | None:
    """Job whose children die when the last handle to it closes.

    winws.exe lives inside the PyInstaller ``_MEI`` temp directory, so an
    orphaned copy keeps that directory locked and the bootloader shows a
    "Failed to remove temporary directory" warning on the next exit. A job
    object is the only teardown that also covers a hard kill or a Windows
    shutdown, where no Python cleanup code gets to run.
    """
    kernel32 = _kernel32()
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        log.warning(
            "CreateJobObject failed (%s); winws may outlive a crash",
            ctypes.get_last_error(),
        )
        return None

    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        handle, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)
    ):
        log.warning("SetInformationJobObject failed (%s)", ctypes.get_last_error())
        kernel32.CloseHandle(handle)
        return None
    return handle


def _assign_to_job(job: wintypes.HANDLE, pid: int) -> None:
    kernel32 = _kernel32()
    proc = kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
    if not proc:
        log.warning("OpenProcess for job assignment failed (%s)", ctypes.get_last_error())
        return
    try:
        if not kernel32.AssignProcessToJobObject(job, proc):
            log.warning("AssignProcessToJobObject failed (%s)", ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(proc)


def is_admin() -> bool:
    """WinDivert needs SeLoadDriverPrivilege, i.e. an elevated process."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class DpiEngineError(RuntimeError):
    pass


class DpiEngine:
    """Starts/stops one winws.exe instance and mirrors its output into the log."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._strategy: DpiStrategy | None = None
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()
        self._job = _create_kill_on_close_job()

    # ------------------------------------------------------------- state

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def strategy(self) -> DpiStrategy | None:
        return self._strategy if self.running else None

    # ------------------------------------------------------------- control

    def start(self, strategy: DpiStrategy, *, settle: float = STRATEGY_SETTLE_TIMEOUT) -> None:
        with self._lock:
            if self.running:
                self._stop_locked()

            if not WINWS_EXE.exists():
                raise DpiEngineError(
                    f"winws.exe not found at {WINWS_EXE}. See README 'Bundling binaries'."
                )
            if not is_admin():
                raise DpiEngineError(
                    "Administrator rights are required to load the WinDivert driver."
                )

            cmd = strategy.command(WINWS_EXE)
            log.info("Starting winws with strategy '%s'", strategy.name)
            log.debug("Command: %s", " ".join(cmd))

            try:
                self._proc = subprocess.Popen(
                    cmd,
                    cwd=str(ZAPRET_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    creationflags=_CREATE_NO_WINDOW,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                raise DpiEngineError(f"Failed to launch winws.exe: {exc}") from exc

            self._strategy = strategy
            if self._job is not None:
                _assign_to_job(self._job, self._proc.pid)
            output = deque(maxlen=12)
            self._reader = threading.Thread(
                target=self._drain_output, args=(self._proc, output), daemon=True
            )
            self._reader.start()

            # winws exits immediately on a bad argument vector; catch that here
            # instead of reporting a false "connected" state to the user. Polling
            # returns as soon as it is clear the process survived.
            deadline = time.monotonic() + settle
            while time.monotonic() < deadline:
                if self._proc.poll() is not None:
                    code = self._proc.returncode
                    if self._reader is not None:
                        self._reader.join(timeout=0.25)
                    detail = " | ".join(output) or "no diagnostic output"
                    self._proc = None
                    self._strategy = None
                    raise DpiEngineError(
                        f"winws exited immediately (code {code}): {detail}"
                    )
                time.sleep(STRATEGY_SETTLE_POLL)

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._proc is None:
            return
        log.info("Stopping winws")
        try:
            self._proc.terminate()
            self._proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            log.warning("winws did not exit, killing")
            self._proc.kill()
            # kill() only posts the request on Windows. winws.exe is loaded from
            # the one-file unpack dir, so returning before it is really gone
            # leaves the bootloader unable to delete _MEIxxxxx on exit.
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                log.warning("winws still alive after kill")
        except OSError as exc:
            log.warning("Error stopping winws: %s", exc)
        finally:
            self._proc = None
            self._strategy = None

    def _drain_output(self, proc: subprocess.Popen, output: deque[str]) -> None:
        """Pipe must be read or winws blocks once the buffer fills."""
        if proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                output.append(line)
                log.debug("winws: %s", line)
