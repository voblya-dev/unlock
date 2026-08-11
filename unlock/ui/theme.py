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
        "BG": "#071522",
        "BG_ELEVATED": "#0b2030",
        # Deep-ocean glass surfaces shared by every page and dialog.
        "SIDEBAR_ACTIVE": "#173b4d",
        "CARD": "rgba(18, 55, 72, 0.72)",
        "CARD_BORDER": "rgba(126, 190, 205, 0.20)",
        "HOVER": "rgba(72, 139, 158, 0.22)",
        "PRESSED": "rgba(92, 166, 181, 0.30)",
        "TRACK": "rgba(126, 190, 205, 0.12)",
        # Switches use a bright, solid off-state so the monochrome accent does
        # not turn the whole control into one indistinguishable white blob.
        "SWITCH_OFF": "#f2f2f7",
        "SWITCH_KNOB_OFF": "#111214",
        "SCROLL": "rgba(255, 255, 255, 0.14)",
        "SCROLL_HOVER": "rgba(255, 255, 255, 0.24)",
        "CONSOLE_BG": "rgba(0, 0, 0, 0.30)",
        "TEXT": "#f2f2f7",
        "TEXT_MUTED": "#8e8e93",
        "TEXT_FAINT": "#5c5c61",
        "ON_ACCENT": "#ffffff",
        "SUCCESS": "#32d74b",
        "DANGER": "#ff453a",
        "WARNING": "#ffd60a",
        # Power-button body gradient: (idle top, idle bottom, active top, active bottom)
        "ORB": ((30, 30, 32), (18, 18, 20), (28, 58, 44), (16, 26, 22)),
        "ORB_EDGE": (255, 255, 255, 16),
        "RING_TRACK": (255, 255, 255, 18),
    },
    LIGHT: {
        "BG": "#f4f6fa",
        "BG_ELEVATED": "#ffffff",
        "SIDEBAR_ACTIVE": "#e5e5ea",
        "CARD": "rgba(15, 23, 42, 0.03)",
        "CARD_BORDER": "rgba(15, 23, 42, 0.12)",
        "HOVER": "rgba(15, 23, 42, 0.06)",
        "PRESSED": "rgba(15, 23, 42, 0.10)",
        "TRACK": "rgba(15, 23, 42, 0.08)",
        "SWITCH_OFF": "#ffffff",
        "SWITCH_KNOB_OFF": "#16202e",
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
    "mono":   {"dark": ("#f2f5f7", "#aeb7bf"), "light": ("#20252b", "#4d5762")},
    "blue":   {"dark": ("#5b9dff", "#3f7bd8"), "light": ("#2f6fd0", "#245aad")},
    "green":  {"dark": ("#32d74b", "#25a838"), "light": ("#0f9d58", "#0b7c45")},
    "purple": {"dark": ("#bf5af2", "#9b3dd9"), "light": ("#6d44d9", "#5734ae")},
    "orange": {"dark": ("#ff9f0a", "#d9820a"), "light": ("#d9711a", "#ad5a15")},
    "rose":   {"dark": ("#ff375f", "#d92c4a"), "light": ("#d63a63", "#ad2e4f")},
}

DEFAULT_ACCENT = "mono"

_mode = DARK
_accent = DEFAULT_ACCENT


def _darken_hex(hex_str: str, factor: float = 0.76) -> str:
    h = hex_str.lstrip("#")
    r = round(int(h[0:2], 16) * factor)
    g = round(int(h[2:4], 16) * factor)
    b = round(int(h[4:6], 16) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


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


def is_custom_hex(value: str) -> bool:
    """True for a #rrggbb / #rgb user-supplied colour, false for a named accent key."""
    import re
    return bool(re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", value.strip()))


def contrast_color(value: str) -> str:
    """Return a readable black/white foreground for an accent colour."""
    colour = qcolor(value)
    # Relative luminance is more useful here than Qt's lightness for bright
    # yellow/green accents, which otherwise get a washed-out white knob.
    channels = []
    for channel in (colour.red(), colour.green(), colour.blue()):
        linear = channel / 255.0
        channels.append(linear / 12.92 if linear <= 0.04045 else ((linear + 0.055) / 1.055) ** 2.4)
    luminance = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    # This is the crossover where black produces a higher WCAG contrast ratio
    # than white against the accent.
    return "#111214" if luminance >= 0.18 else "#ffffff"


def apply(preference: str = SYSTEM, accent: str = DEFAULT_ACCENT) -> str:
    """Rebind the palette globals and rebuild STYLESHEET. Returns the mode used."""
    global _mode, _accent
    _mode = resolve_mode(preference)

    values = dict(_PALETTES[_mode])
    if is_custom_hex(accent):
        _accent = accent
        values["ACCENT"] = accent
        values["ACCENT_DIM"] = _darken_hex(accent)
    else:
        _accent = accent if accent in ACCENTS else DEFAULT_ACCENT
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

/* ── Root shell ─────────────────────────────────────── */
#root {{
    background: {g['BG']};
    border: 1px solid {g['CARD_BORDER']};
    border-radius: 18px;
}}

/* ── Sidebar ─────────────────────────────────────────── */
#sidebar {{
    background: {g['BG_ELEVATED']};
    border-right: 1px solid {g['CARD_BORDER']};
    border-top-left-radius: 17px;
    border-bottom-left-radius: 17px;
}}

#sidebarHeader {{
    background: transparent;
}}

#appTitle {{
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 0.2px;
    color: {g['TEXT']};
}}

/* Search bar container */
#searchBar {{
    background: {g['BG']};
    border: 1px solid {g['CARD_BORDER']};
    border-radius: 10px;
}}
#searchField {{
    background: transparent;
    border: none;
    color: {g['TEXT_MUTED']};
    font-size: 13px;
    padding: 0;
}}
#searchField:focus {{
    color: {g['TEXT']};
}}
/* "/" hotkey badge inside search bar */
#slashBadge {{
    background: {g['CARD']};
    border: 1px solid {g['CARD_BORDER']};
    border-radius: 5px;
    color: {g['TEXT_FAINT']};
    font-size: 11px;
    padding: 1px 5px;
    min-width: 14px;
    max-width: 14px;
}}

/* Sidebar nav items */
#navItem {{
    background: transparent;
    border: none;
    border-radius: 10px;
    text-align: left;
    padding: 9px 12px;
    color: {g['TEXT_MUTED']};
    font-size: 13px;
    font-weight: 500;
}}
#navItem:hover {{
    background: {g['HOVER']};
    color: {g['TEXT']};
}}
#navItemActive {{
    background: {g['SIDEBAR_ACTIVE']};
    border: none;
    border-radius: 10px;
    text-align: left;
    padding: 9px 12px;
    color: {g['TEXT']};
    font-size: 13px;
    font-weight: 600;
}}
#navItemActive:hover {{
    background: {g['SIDEBAR_ACTIVE']};
}}

/* Window control buttons in sidebar header */
#windowButton, #closeButton {{
    background: transparent;
    border: none;
    color: {g['TEXT_FAINT']};
    font-size: 13px;
    padding: 0;
}}
#windowButton:hover {{
    background: {g['HOVER']};
    color: {g['TEXT']};
    border-radius: 4px;
}}
#closeButton:hover {{
    background: {g['DANGER']};
    color: white;
    border-radius: 4px;
}}

/* ── Content area ────────────────────────────────────── */
#contentArea {{
    background: {g['BG']};
    border-top-right-radius: 17px;
    border-bottom-right-radius: 17px;
}}

/* ── Cards ───────────────────────────────────────────── */
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

/* ── Buttons ─────────────────────────────────────────── */
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
}}
QPushButton:focus {{
    outline: none;
    border-color: {g['CARD_BORDER']};
}}
QPushButton:pressed {{
    background: {g['PRESSED']};
}}
QPushButton:disabled {{
    color: {g['TEXT_FAINT']};
    border-color: {g['TRACK']};
}}
QPushButton#primary {{
    background: transparent;
    border: 1px solid {g['ACCENT']};
    color: {g['ACCENT']};
    font-weight: 600;
}}
QPushButton#primary:hover {{
    background: {g['HOVER']};
    color: {g['TEXT']};
    border-color: {g['ACCENT_DIM']};
}}

/* ── Checkbox / Switch ───────────────────────────────── */
QCheckBox {{
    spacing: 10px;
    padding: 4px 0;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 0;
    height: 0;
}}

/* ── VPN cards ───────────────────────────────────────── */
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

/* ── Drop zone ───────────────────────────────────────── */
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

/* ── Inputs ──────────────────────────────────────────── */
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

/* ── Progress bar ────────────────────────────────────── */
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

/* ── Log view ────────────────────────────────────────── */
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

/* ── Scroll areas ────────────────────────────────────── */
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

/* ── Context menus ───────────────────────────────────── */
QMenu {{
    background: {g['BG_ELEVATED']};
    border: 1px solid {g['CARD_BORDER']};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 22px 7px 14px;
    border: 1px solid transparent;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: transparent;
    border-color: {g['ACCENT']};
    color: {g['TEXT']};
}}
QMenu::separator {{
    height: 1px;
    background: {g['CARD_BORDER']};
    margin: 5px 8px;
}}
"""


apply(DARK, DEFAULT_ACCENT)


