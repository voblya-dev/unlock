"""Theme palettes, accent colours and the global stylesheet.

Two palettes (dark / light) and a handful of accents. ``apply()`` rebinds the
module-level colour names, so call sites keep using ``theme.TEXT`` and friends
and simply pick up the new value on the next repaint.

In ``system`` mode the palette follows the Windows "app mode" setting, read from
``HKCU\\...\\Themes\\Personalize\\AppsUseLightTheme``.
"""

from __future__ import annotations

import sys

DARK = "dark"
LIGHT = "light"
SYSTEM = "system"

FONT = "Segoe UI"


# Each palette is a plain dict so apply() can drop it straight into globals().
_PALETTES = {
    DARK: {
        "BG": "#0d1117",
        "BG_ELEVATED": "#141b24",
        "CARD": "rgba(255, 255, 255, 0.04)",
        "CARD_BORDER": "rgba(255, 255, 255, 0.08)",
        "HOVER": "rgba(255, 255, 255, 0.08)",
        "PRESSED": "rgba(255, 255, 255, 0.12)",
        "TRACK": "rgba(255, 255, 255, 0.06)",
        "SCROLL": "rgba(255, 255, 255, 0.14)",
        "SCROLL_HOVER": "rgba(255, 255, 255, 0.24)",
        "CONSOLE_BG": "rgba(0, 0, 0, 0.35)",
        "TEXT": "#e8edf5",
        "TEXT_MUTED": "#8b98ab",
        "TEXT_FAINT": "#5d6879",
        "ON_ACCENT": "#06101f",
        "SUCCESS": "#43d18a",
        "DANGER": "#ff5f6d",
        "WARNING": "#f5c451",
        # Power-button body gradient: (idle top, idle bottom, active top, active bottom)
        "ORB": ((30, 38, 50), (16, 21, 28), (30, 62, 48), (16, 26, 24)),
        "ORB_EDGE": (255, 255, 255, 18),
        "RING_TRACK": (255, 255, 255, 20),
    },
    LIGHT: {
        "BG": "#f4f6fa",
        "BG_ELEVATED": "#ffffff",
        "CARD": "rgba(15, 23, 42, 0.03)",
        "CARD_BORDER": "rgba(15, 23, 42, 0.12)",
        "HOVER": "rgba(15, 23, 42, 0.06)",
        "PRESSED": "rgba(15, 23, 42, 0.10)",
        "TRACK": "rgba(15, 23, 42, 0.08)",
        "SCROLL": "rgba(15, 23, 42, 0.18)",
        "SCROLL_HOVER": "rgba(15, 23, 42, 0.30)",
        "CONSOLE_BG": "rgba(15, 23, 42, 0.04)",
        "TEXT": "#16202e",
        "TEXT_MUTED": "#5a6a7e",
        "TEXT_FAINT": "#8b98ab",
        "ON_ACCENT": "#ffffff",
        "SUCCESS": "#0f9d58",
        "DANGER": "#d92c3c",
        "WARNING": "#b3801a",
        "ORB": ((255, 255, 255), (232, 237, 245), (226, 247, 237), (203, 235, 220)),
        "ORB_EDGE": (15, 23, 42, 28),
        "RING_TRACK": (15, 23, 42, 30),
    },
}

# Accents carry a separate pair per palette: the dark-mode hue is too pale to
# read as a button fill on white, so light mode gets a deeper one.
ACCENTS: dict[str, dict] = {
    "blue":   {"dark": ("#5b9dff", "#3f7bd8"), "light": ("#2f6fd0", "#245aad")},
    "green":  {"dark": ("#43d18a", "#2ba76a"), "light": ("#0f9d58", "#0b7c45")},
    "purple": {"dark": ("#a78bfa", "#7c5cf0"), "light": ("#6d44d9", "#5734ae")},
    "orange": {"dark": ("#ffa657", "#e07f2e"), "light": ("#d9711a", "#ad5a15")},
    "rose":   {"dark": ("#ff7b9c", "#e04d75"), "light": ("#d63a63", "#ad2e4f")},
}

DEFAULT_ACCENT = "blue"

_mode = DARK
_accent = DEFAULT_ACCENT


def windows_prefers_dark() -> bool:
    """True when the Windows app mode is dark. Defaults to dark off-Windows."""
    if sys.platform != "win32":
        return True
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            return not winreg.QueryValueEx(key, "AppsUseLightTheme")[0]
    except OSError:
        return True


def resolve_mode(preference: str) -> str:
    if preference in (DARK, LIGHT):
        return preference
    return DARK if windows_prefers_dark() else LIGHT


def current_mode() -> str:
    return _mode


def current_accent() -> str:
    return _accent


def qcolor(value: str) -> "QColor":
    """QColor from a palette entry, including the ``rgba(r, g, b, a)`` form.

    Half the palette is written as CSS so it can go straight into the
    stylesheet, and QColor's own parser rejects that syntax — a hand-painted
    widget asking for ``theme.TRACK`` would silently get black.
    """
    from PyQt6.QtGui import QColor

    text = value.strip()
    if text.lower().startswith(("rgba(", "rgb(")):
        parts = text[text.index("(") + 1:text.rindex(")")].split(",")
        red, green, blue = (int(float(p)) for p in parts[:3])
        alpha = float(parts[3]) if len(parts) > 3 else 1.0
        # CSS allows either 0..1 or 0..255 for the alpha channel.
        return QColor(red, green, blue, round(alpha * 255 if alpha <= 1 else alpha))
    return QColor(text)


def apply(preference: str = SYSTEM, accent: str = DEFAULT_ACCENT) -> str:
    """Rebind the palette globals and rebuild STYLESHEET. Returns the mode used."""
    global _mode, _accent
    _mode = resolve_mode(preference)
    _accent = accent if accent in ACCENTS else DEFAULT_ACCENT

    values = dict(_PALETTES[_mode])
    main, dim = ACCENTS[_accent][_mode]
    values["ACCENT"] = main
    values["ACCENT_DIM"] = dim

    globals().update(values)
    globals()["STYLESHEET"] = _build_stylesheet()
    return _mode


def _build_stylesheet() -> str:
    g = globals()
    return f"""
QWidget {{
    background: transparent;
    color: {g['TEXT']};
    font-family: "{FONT}";
    font-size: 13px;
}}

#root {{
    background: {g['BG']};
    border: 1px solid {g['CARD_BORDER']};
    border-radius: 14px;
}}

#titleBar {{
    background: {g['BG_ELEVATED']};
    border-bottom: 1px solid {g['CARD_BORDER']};
    border-top-left-radius: 13px;
    border-top-right-radius: 13px;
}}

#appTitle {{
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.4px;
}}

#windowButton, #closeButton {{
    background: transparent;
    border: none;
    color: {g['TEXT_MUTED']};
    font-size: 14px;
    padding: 0;
}}
#windowButton:hover {{
    background: {g['CARD']};
    color: {g['TEXT']};
    border-radius: 4px;
}}
#closeButton:hover {{
    background: {g['DANGER']};
    color: white;
    border-radius: 4px;
}}

QTabWidget::pane {{
    border: none;
}}
QTabWidget::tab-bar {{
    alignment: center;
}}
QTabBar::tab {{
    background: transparent;
    color: {g['TEXT_MUTED']};
    padding: 9px 20px;
    margin: 0 2px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 500;
}}
QTabBar::tab:hover {{
    color: {g['TEXT']};
}}
QTabBar::tab:selected {{
    color: {g['ACCENT']};
    border-bottom: 2px solid {g['ACCENT']};
}}

#card {{
    background: {g['CARD']};
    border: 1px solid {g['CARD_BORDER']};
    border-radius: 12px;
}}

#statusHeadline {{
    font-size: 17px;
    font-weight: 600;
}}
#statusDetail {{
    color: {g['TEXT_MUTED']};
    font-size: 12px;
}}
#metricLabel {{
    color: {g['TEXT_FAINT']};
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
#metricValue {{
    font-size: 20px;
    font-weight: 600;
}}
#sectionTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {g['TEXT']};
}}
#statFigure {{
    font-size: 14px;
    font-weight: 600;
    color: {g['TEXT']};
}}
#statCaption {{
    color: {g['TEXT_FAINT']};
    font-size: 10px;
}}
#statRow {{
    color: {g['TEXT_MUTED']};
    font-size: 11px;
}}
#statClock {{
    font-size: 17px;
    font-weight: 600;
    color: {g['TEXT']};
}}
#statRule {{
    background: {g['CARD_BORDER']};
    border: none;
}}
#hint {{
    color: {g['TEXT_FAINT']};
    font-size: 11px;
}}

QPushButton {{
    background: {g['CARD']};
    border: 1px solid {g['CARD_BORDER']};
    border-radius: 8px;
    padding: 8px 16px;
    color: {g['TEXT']};
    font-weight: 500;
}}
QPushButton:hover {{
    background: {g['HOVER']};
    border-color: {g['ACCENT_DIM']};
}}
QPushButton:pressed {{
    background: {g['PRESSED']};
}}
QPushButton:disabled {{
    color: {g['TEXT_FAINT']};
    border-color: {g['TRACK']};
}}
QPushButton#primary {{
    background: {g['ACCENT']};
    border: none;
    color: {g['ON_ACCENT']};
    font-weight: 600;
}}
QPushButton#primary:hover {{
    background: {g['ACCENT_DIM']};
}}

QCheckBox {{
    spacing: 10px;
    padding: 4px 0;
    background: transparent;
}}
/* ui.widgets.Switch paints its own track and knob, so the stock indicator is
   suppressed rather than styled. */
QCheckBox::indicator {{
    width: 0;
    height: 0;
}}

#vpnCard, #vpnCardActive {{
    background: {g['CARD']};
    border: 1px solid {g['CARD_BORDER']};
    border-radius: 10px;
}}
#vpnCard:hover {{
    background: {g['HOVER']};
}}
#vpnCardActive {{
    background: {g['HOVER']};
    border: 1px solid {g['ACCENT']};
}}
/* No hover rule for the active card: it is already the highlighted one, and a
   second highlight makes two servers look selected at once. */

#dropZone, #dropZoneActive {{
    border: 1px dashed {g['CARD_BORDER']};
    border-radius: 10px;
    background: {g['CARD']};
}}
#dropZone:hover {{
    border-color: {g['ACCENT_DIM']};
}}
#dropZoneActive {{
    border: 1px dashed {g['ACCENT']};
    background: {g['HOVER']};
}}

QComboBox, QLineEdit {{
    background: {g['CARD']};
    border: 1px solid {g['CARD_BORDER']};
    border-radius: 8px;
    padding: 7px 10px;
    min-width: 150px;
}}
QComboBox:hover, QLineEdit:hover {{
    border-color: {g['ACCENT_DIM']};
}}
QLineEdit:focus {{
    border-color: {g['ACCENT']};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: {g['BG_ELEVATED']};
    border: 1px solid {g['CARD_BORDER']};
    border-radius: 8px;
    selection-background-color: {g['ACCENT_DIM']};
    selection-color: {g['ON_ACCENT']};
    padding: 4px;
    outline: none;
}}

QProgressBar {{
    background: {g['TRACK']};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {g['ACCENT']};
    border-radius: 4px;
}}

QPlainTextEdit {{
    background: {g['CONSOLE_BG']};
    border: 1px solid {g['CARD_BORDER']};
    border-radius: 10px;
    padding: 10px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
    color: {g['TEXT_MUTED']};
    selection-background-color: {g['ACCENT_DIM']};
    selection-color: {g['ON_ACCENT']};
}}

QScrollArea, QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {g['SCROLL']};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {g['SCROLL_HOVER']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0;
    background: transparent;
}}

QMenu {{
    background: {g['BG_ELEVATED']};
    border: 1px solid {g['CARD_BORDER']};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 22px 7px 14px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: {g['ACCENT_DIM']};
    color: {g['ON_ACCENT']};
}}
QMenu::separator {{
    height: 1px;
    background: {g['CARD_BORDER']};
    margin: 5px 8px;
}}
"""


apply(DARK, DEFAULT_ACCENT)
