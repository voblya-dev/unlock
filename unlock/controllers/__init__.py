"""Controllers: one per engine, plus the façade the GUI actually holds.

``unlock.controller`` used to be a single 1100-line object that owned the DPI
filter, the Telegram bridge, the VPN tunnel and every worker thread between them.
It is now four files — :mod:`~unlock.controllers.dpi`,
:mod:`~unlock.controllers.telegram`, :mod:`~unlock.controllers.vpn` and the
:class:`~unlock.controllers.facade.Controller` that composes them.

Importing from the package keeps the call sites short, and means the UI never has
to know which half a given signal came from.
"""

from __future__ import annotations

from .base import BUSY_STATES, PingWorker, State, WorkerOwner
from .checks import BootstrapWorker, RecoveryWorker, SelfTestWorker, UpdateCheckWorker
from .dpi import BenchmarkWorker, DpiController
from .facade import ConnectWorker, Controller, DisconnectWorker
from .telegram import TelegramController
from .vpn import VpnController

__all__ = [
    "BUSY_STATES",
    "BenchmarkWorker",
    "BootstrapWorker",
    "ConnectWorker",
    "Controller",
    "DisconnectWorker",
    "DpiController",
    "PingWorker",
    "RecoveryWorker",
    "SelfTestWorker",
    "State",
    "TelegramController",
    "UpdateCheckWorker",
    "VpnController",
    "WorkerOwner",
]
