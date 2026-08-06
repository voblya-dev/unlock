"""Windows autostart.

The build ships a ``requireAdministrator`` manifest (see ``unlock.spec``), and
Windows silently skips elevated entries in ``HKCU\\Run`` at logon instead of
prompting for UAC. So the scheduled task is the real mechanism; the Run key is
only a fallback for unelevated source checkouts, which do not need elevation to
be registered.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import winreg
from pathlib import Path

from .constants import APP_NAME
from .logger import get_logger

log = get_logger("autostart")

_CREATE_NO_WINDOW = 0x08000000
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_TASK_NAME = f"{APP_NAME}Autostart"

_TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Launches {app} at sign-in with the elevation WinDivert needs.</Description>
    <URI>\\{task}</URI>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{user}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>false</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <DisallowStartOnRemoteAppSession>false</DisallowStartOnRemoteAppSession>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{workdir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _target() -> tuple[str, str, str]:
    """Returns (command, arguments, working directory) for the launch action."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return str(exe), "--minimized", str(exe.parent)
    script = Path(sys.argv[0]).resolve()
    return str(Path(sys.executable).resolve()), f'"{script}" --minimized', str(script.parent)


def _launch_command() -> str:
    command, arguments, _ = _target()
    return f'"{command}" {arguments}'


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        text=True,
        creationflags=_CREATE_NO_WINDOW,
    )


def _current_user() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    user = os.environ.get("USERNAME", "")
    return f"{domain}\\{user}" if domain else user


def _task_exists() -> bool:
    return _schtasks("/Query", "/TN", _TASK_NAME).returncode == 0


def _create_task() -> bool:
    command, arguments, workdir = _target()
    xml = _TASK_XML.format(
        app=_xml_escape(APP_NAME),
        task=_xml_escape(_TASK_NAME),
        user=_xml_escape(_current_user()),
        command=_xml_escape(command),
        arguments=_xml_escape(arguments),
        workdir=_xml_escape(workdir),
    )
    # schtasks /XML insists on a real file, and only reads UTF-16 reliably.
    handle, path = tempfile.mkstemp(suffix=".xml")
    os.close(handle)
    try:
        Path(path).write_text(xml, encoding="utf-16")
        result = _schtasks("/Create", "/TN", _TASK_NAME, "/XML", path, "/F")
        if result.returncode != 0:
            log.error("schtasks /Create failed: %s", (result.stderr or result.stdout).strip())
            return False
        return True
    finally:
        Path(path).unlink(missing_ok=True)


def _delete_task() -> bool:
    if not _task_exists():
        return True
    result = _schtasks("/Delete", "/TN", _TASK_NAME, "/F")
    if result.returncode != 0:
        log.error("schtasks /Delete failed: %s", (result.stderr or result.stdout).strip())
        return False
    return True


def _run_key_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        log.warning("Autostart check failed: %s", exc)
        return False


def _set_run_key(enabled: bool) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _launch_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError as exc:
        log.error("Autostart registry update failed: %s", exc)
        return False


def is_enabled() -> bool:
    return _task_exists() or _run_key_enabled()


def set_enabled(enabled: bool) -> bool:
    if not enabled:
        ok_task = _delete_task()
        ok_key = _set_run_key(False)
        log.info("Autostart disabled")
        return ok_task and ok_key

    if _create_task():
        # Both mechanisms firing would race the single-instance guard.
        _set_run_key(False)
        log.info("Autostart enabled via scheduled task")
        return True

    # Creating the task needs elevation; an unelevated source run falls back.
    if _set_run_key(True):
        log.warning("Autostart enabled via Run key — the frozen build needs the task instead")
        return True
    return False
