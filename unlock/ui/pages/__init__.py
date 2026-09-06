"""The three content pages behind the sidebar, one module each.

``main_window`` used to build all of them inline, which is how a single file
reached 1380 lines: the window frame, the tray, the controller wiring and every
card on every tab shared one namespace, so a Settings switch and a resize grip
were neighbours.  Each page now owns the widgets it builds and exposes a small
surface — ``apply_state``, ``load_from_config``, ``restyle`` — leaving the window
to route signals between the controller and the pages.
"""

from __future__ import annotations

from .home import HomePage, state_headline
from .logs import LogsPage
from .settings import SettingsPage

__all__ = ["HomePage", "LogsPage", "SettingsPage", "state_headline"]
