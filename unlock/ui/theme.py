"""Obsidian Terminal: the intentionally monochrome design system for Unlock."""

from __future__ import annotations

import re
import sys

DARK = "dark"
LIGHT = "light"
SYSTEM = "system"
# Segoe UI is bundled with Windows. The Variable family falls back differently
# across PyQt backends, which made glyph widths visibly jump during animation.
FONT = "Segoe UI"

# Semantic values remain separate even in a monochrome product: status is
# carried by copy, glyph and shape as well as a slightly different gray.
_PALETTES = {
    DARK: {
        "BG": "#0A0A0A", "BG_ELEVATED": "#101010", "SIDEBAR_ACTIVE": "#242424",
        "CARD": "#121212", "CARD_BORDER": "#303030", "HOVER": "#1C1C1C",
        "PRESSED": "#2B2B2B", "TRACK": "#242424", "SWITCH_OFF": "#333333",
        "SWITCH_KNOB_OFF": "#A6A6A6", "SCROLL": "#484848", "SCROLL_HOVER": "#777777",
        "CONSOLE_BG": "#080808", "TEXT": "#F5F5F2", "TEXT_MUTED": "#AAAAA6",
        "TEXT_FAINT": "#737370", "ON_ACCENT": "#090909", "SUCCESS": "#F5F5F2",
        "DANGER": "#B5B5B1", "WARNING": "#D4D4D0",
        "ORB": ((24, 24, 24), (10, 10, 10), (242, 242, 239), (116, 116, 112)),
        "ORB_EDGE": (245, 245, 242, 34), "RING_TRACK": (245, 245, 242, 28),
    },
    LIGHT: {
        "BG": "#F2F1ED", "BG_ELEVATED": "#FBFAF7", "SIDEBAR_ACTIVE": "#E0DFDB",
        "CARD": "#F9F8F5", "CARD_BORDER": "#CBCAC5", "HOVER": "#E9E8E4",
        "PRESSED": "#DCDAD5", "TRACK": "#E2E1DD", "SWITCH_OFF": "#D2D1CC",
        "SWITCH_KNOB_OFF": "#4A4A48", "SCROLL": "#B3B2AD", "SCROLL_HOVER": "#777773",
        "CONSOLE_BG": "#F5F4F0", "TEXT": "#111111", "TEXT_MUTED": "#5E5E5A",
        "TEXT_FAINT": "#858580", "ON_ACCENT": "#F8F8F4", "SUCCESS": "#111111",
        "DANGER": "#4D4D49", "WARNING": "#2C2C2A",
        "ORB": ((242, 241, 237), (215, 214, 209), (26, 26, 26), (90, 90, 86)),
        "ORB_EDGE": (17, 17, 17, 36), "RING_TRACK": (17, 17, 17, 30),
    },
}

# The settings keep the familiar picker API, but its supplied system choices
# are purposeful grayscale tonalities rather than decorative colour themes.
ACCENTS: dict[str, dict] = {
    "mono": {"dark": ("#F5F5F2", "#BDBDB8"), "light": ("#161616", "#4B4B48")},
    "soft": {"dark": ("#D0D0CB", "#92928D"), "light": ("#383836", "#686865")},
    "ink": {"dark": ("#9D9D99", "#6E6E6A"), "light": ("#080808", "#353533")},
}
DEFAULT_ACCENT = "mono"
_mode = DARK
_accent = DEFAULT_ACCENT


def _darken_hex(hex_str: str, factor: float = 0.76) -> str:
    value = hex_str.lstrip("#")
    return "#%02x%02x%02x" % tuple(round(int(value[i:i + 2], 16) * factor) for i in (0, 2, 4))


def windows_prefers_dark() -> bool:
    if sys.platform != "win32":
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return not winreg.QueryValueEx(key, "AppsUseLightTheme")[0]
    except OSError:
        return True


def resolve_mode(preference: str) -> str:
    return preference if preference in (DARK, LIGHT) else (DARK if windows_prefers_dark() else LIGHT)


def current_mode() -> str:
    return _mode


def current_accent() -> str:
    return _accent


def qcolor(value: str):
    from PyQt6.QtGui import QColor
    value = value.strip()
    if value.lower().startswith(("rgba(", "rgb(")):
        parts = value[value.index("(") + 1:value.rindex(")")].split(",")
        rgb = [int(float(part)) for part in parts[:3]]
        alpha = float(parts[3]) if len(parts) > 3 else 1.0
        return QColor(*rgb, round(alpha * 255 if alpha <= 1 else alpha))
    return QColor(value)


def is_custom_hex(value: str) -> bool:
    return bool(re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", value.strip()))


def contrast_color(value: str) -> str:
    colour = qcolor(value)
    return "#111111" if colour.lightnessF() > 0.48 else "#F5F5F2"


def apply(preference: str = SYSTEM, accent: str = DEFAULT_ACCENT) -> str:
    global _mode, _accent
    _mode = resolve_mode(preference)
    values = dict(_PALETTES[_mode])
    _accent = accent if accent in ACCENTS else DEFAULT_ACCENT
    main, dim = ACCENTS[_accent][_mode]
    values["ACCENT"], values["ACCENT_DIM"] = main, dim
    globals().update(values)
    globals()["STYLESHEET"] = _build_stylesheet()
    return _mode


def _build_stylesheet() -> str:
    g = globals()
    return f"""
QWidget {{ background: transparent; color: {g['TEXT']}; font-family: \"{FONT}\", \"Segoe UI\"; font-size: 13px; }}
#root {{ background: {g['BG']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 16px; }}
#sidebar {{ background: {g['BG_ELEVATED']}; border-right: 1px solid {g['CARD_BORDER']}; border-top-left-radius: 15px; border-bottom-left-radius: 15px; }}
#contentArea {{ background: transparent; border-top-right-radius: 15px; border-bottom-right-radius: 15px; }}
/* The rounded frame is painted by #root.  Keeping the right-hand descendants
   transparent is important: Qt stylesheets do not clip child backgrounds to a
   parent's border radius, so an opaque page would square off the outer edge. */
#terminalBar {{ background: transparent; border-bottom: 1px solid {g['CARD_BORDER']}; }}
#terminalTitle {{ color: {g['TEXT']}; font-size: 10px; font-weight: 700; letter-spacing: 1.25px; }}
#terminalDot {{ color: {g['TEXT_FAINT']}; font-size: 8px; }}
QPushButton#terminalWindowButton {{ background: transparent; border: none; border-radius: 0; color: {g['TEXT_MUTED']}; padding: 0; font-size: 15px; }}
QPushButton#terminalWindowButton:hover {{ background: {g['HOVER']}; color: {g['TEXT']}; }}
#appTitle {{ font-size: 14px; font-weight: 700; letter-spacing: 1.4px; }}
#searchBar {{ background: {g['BG']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 9px; }}
#searchField {{ background: transparent; border: none; color: {g['TEXT_MUTED']}; padding: 0; }}
#searchField:focus {{ color: {g['TEXT']}; }}
#navItem, #navItemActive {{ background: transparent; border: none; border-radius: 8px; text-align: left; padding: 9px 12px; color: {g['TEXT_MUTED']}; font-weight: 550; }}
#navItem:hover {{ background: {g['HOVER']}; color: {g['TEXT']}; }}
#navItemActive {{ background: {g['SIDEBAR_ACTIVE']}; color: {g['TEXT']}; border-left: 2px solid {g['ACCENT']}; padding-left: 10px; }}
#sidebarWordmark {{ color: {g['TEXT']}; font-size: 11px; font-weight: 800; letter-spacing: 1.6px; }}
#windowButton, #closeButton {{ background: transparent; border: none; color: {g['TEXT_FAINT']}; font-size: 13px; padding: 0; }}
#windowButton:hover {{ background: {g['HOVER']}; color: {g['TEXT']}; }}
#closeButton:hover {{ background: {g['TEXT']}; color: {g['BG']}; }}

/* Obsidian Terminal home */
#commandHome {{ background: transparent; }}
#heroCard {{ background: {g['BG']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 12px; }}
#commandPanel {{ background: {g['BG_ELEVATED']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 12px; }}
#heroKicker, #metricLabel {{ color: {g['TEXT_FAINT']}; font-size: 10px; font-weight: 700; letter-spacing: 1.35px; }}
#commandHeadline {{ color: {g['TEXT']}; font-size: 22px; font-weight: 650; letter-spacing: .2px; }}
#commandDetail {{ color: {g['TEXT_MUTED']}; font-size: 11px; }}
QPushButton#heroPrimary {{ background: {g['ACCENT']}; border: 1px solid {g['ACCENT']}; border-radius: 9px; color: {g['ON_ACCENT']}; font-weight: 750; padding: 9px 14px; }}
QPushButton#heroPrimary:hover {{ background: {g['TEXT']}; border-color: {g['TEXT']}; }}
QPushButton#heroPrimary[active=\"true\"] {{ background: transparent; border-color: {g['TEXT']}; color: {g['TEXT']}; }}
QPushButton#heroPrimary:disabled {{ background: {g['TRACK']}; border-color: {g['CARD_BORDER']}; color: {g['TEXT_MUTED']}; }}
QPushButton#heroSecondary {{ background: transparent; border: 1px solid {g['CARD_BORDER']}; border-radius: 9px; color: {g['TEXT_MUTED']}; font-size: 11px; padding: 6px 12px; }}
QPushButton#heroSecondary:hover {{ background: {g['HOVER']}; border-color: {g['TEXT_MUTED']}; color: {g['TEXT']}; }}
#commandMetric {{ background: {g['CARD']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 10px; }}
#commandMetricValue {{ color: {g['TEXT']}; font-size: 12px; font-weight: 650; }}
#referenceMetric {{ background: {g['CARD']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 10px; }}
#referenceMetricGlyph {{ color: {g['TEXT']}; font-size: 26px; padding-right: 5px; }}
#referenceMetricValue {{ color: {g['TEXT']}; font-size: 12px; font-weight: 650; }}

/* Shared terminal surfaces */
#card, #vpnControlCard {{ background: {g['CARD']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 12px; }}
#vpnMissionCard {{ background: {g['CARD']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 12px; }}
#vpnMissionCard:hover {{ border-color: {g['TEXT_MUTED']}; }}
#vpnMissionKicker, #vpnMissionHint {{ color: {g['TEXT_FAINT']}; font-size: 10px; font-weight: 700; letter-spacing: 1.2px; }}
#vpnMissionHeadline {{ color: {g['TEXT']}; font-size: 26px; font-weight: 700; }}
#vpnMissionDetail, #statusDetail, #hint {{ color: {g['TEXT_MUTED']}; font-size: 11px; }}
/* A button that reads as part of the text row it sits in: same muted tone and
   size as #hint, no card fill or border, and only the cursor says clickable. */
QPushButton#ghostButton {{ background: transparent; border: none; border-radius: 6px; color: {g['TEXT_MUTED']}; font-size: 11px; font-weight: 600; padding: 2px 6px; }}
QPushButton#ghostButton:hover {{ color: {g['TEXT']}; }}
QPushButton#ghostButton:disabled {{ color: {g['TEXT_FAINT']}; }}
#vpnStateRail {{ min-width: 170px; max-width: 220px; background: {g['BG']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 10px; }}
#vpnRouteValue {{ color: {g['TEXT']}; font-size: 13px; font-weight: 650; }}
#vpnRouteState {{ color: {g['TEXT_FAINT']}; font-size: 10px; font-weight: 700; letter-spacing: 1px; }}
#vpnControlHeadline {{ color: {g['TEXT']}; font-size: 22px; font-weight: 650; }}
#vpnControlDetail {{ color: {g['TEXT_MUTED']}; font-size: 11px; }}
#statusHeadline {{ font-size: 17px; font-weight: 650; }}
#metricValue {{ font-size: 20px; font-weight: 650; }}
#sectionTitle {{ color: {g['TEXT']}; font-size: 12px; font-weight: 700; letter-spacing: .3px; }}
#statFigure {{ color: {g['TEXT']}; font-size: 14px; font-weight: 650; }}
#statCaption, #statRow {{ color: {g['TEXT_FAINT']}; font-size: 10px; }}
#statClock {{ font-size: 17px; font-weight: 650; }}
#statRule {{ background: {g['CARD_BORDER']}; border: none; }}

/* Site/IP manager */
#sitesTitle {{ color: {g['TEXT']}; font-size: 25px; font-weight: 700; letter-spacing: .15px; }}
#aiSwitchBox {{ background: {g['CARD']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 10px; color: {g['TEXT_MUTED']}; font-size: 11px; font-weight: 650; }}
#siteRuleCard {{ background: {g['BG_ELEVATED']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 10px; }}
#siteRuleCard:hover {{ background: {g['HOVER']}; border-color: {g['TEXT_MUTED']}; }}
QPushButton#siteSelect {{ background: transparent; border: 1px solid {g['TEXT_FAINT']}; border-radius: 7px; color: transparent; padding: 0; font-size: 13px; }}
QPushButton#siteSelect:hover {{ background: {g['HOVER']}; border-color: {g['TEXT_MUTED']}; }}
QPushButton#siteSelect:checked {{ background: {g['ACCENT']}; border-color: {g['ACCENT']}; color: {g['ON_ACCENT']}; }}
#siteTypeIcon {{ background: {g['CARD']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 9px; color: {g['ACCENT']}; font-size: 17px; }}
#siteValue {{ color: {g['TEXT']}; font-size: 14px; font-weight: 650; }}
#siteBadge {{ background: {g['TRACK']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 6px; color: {g['TEXT_MUTED']}; font-size: 9px; font-weight: 700; padding: 2px 6px; }}
#siteState {{ color: {g['TEXT_FAINT']}; font-size: 10px; font-weight: 650; }}
QPushButton#siteMenu {{ background: transparent; border: none; color: {g['TEXT_MUTED']}; padding: 0; font-size: 14px; }}
QPushButton#siteMenu:hover {{ background: {g['HOVER']}; color: {g['TEXT']}; }}
#siteEmpty {{ background: {g['BG_ELEVATED']}; border: 1px dashed {g['CARD_BORDER']}; border-radius: 10px; }}
#siteEmptyTitle {{ color: {g['TEXT']}; font-size: 15px; font-weight: 700; }}
#hostMappingRow {{ background: {g['BG_ELEVATED']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 8px; }}
#hostAddress {{ color: {g['TEXT_MUTED']}; font-family: "Cascadia Mono", "Consolas"; font-size: 12px; }}
#hostsWarning {{ color: {g['WARNING']}; background: {g['BG_ELEVATED']}; border-left: 2px solid {g['WARNING']}; border-radius: 5px; padding: 8px 10px; font-size: 11px; }}
#dialogTitle {{ color: {g['TEXT']}; font-size: 18px; font-weight: 700; }}
#sitesNotice {{ color: {g['TEXT']}; background: {g['BG_ELEVATED']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 8px; padding: 8px 11px; font-size: 11px; }}

QPushButton {{ background: {g['CARD']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 9px; padding: 8px 14px; color: {g['TEXT']}; font-weight: 600; }}
QPushButton:hover {{ background: {g['HOVER']}; border-color: {g['TEXT_MUTED']}; }}
QPushButton:pressed {{ background: {g['PRESSED']}; }}
QPushButton:disabled {{ color: {g['TEXT_FAINT']}; border-color: {g['TRACK']}; }}
QPushButton#primary {{ background: {g['ACCENT']}; border-color: {g['ACCENT']}; color: {g['ON_ACCENT']}; font-weight: 700; }}
QPushButton#primary:hover {{ background: {g['TEXT']}; border-color: {g['TEXT']}; }}
QCheckBox {{ spacing: 10px; padding: 4px 0; background: transparent; }} QCheckBox::indicator {{ width: 0; height: 0; }}
#vpnCard, #vpnCardActive {{ background: {g['CARD']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 10px; }}
#vpnCard:hover {{ background: {g['HOVER']}; }} #vpnCardActive {{ border-color: {g['TEXT']}; background: {g['HOVER']}; }}
#dropZone, #dropZoneActive {{ border: 1px dashed {g['TEXT_FAINT']}; border-radius: 10px; background: {g['CARD']}; }}
#dropZone:hover, #dropZoneActive {{ border-color: {g['TEXT']}; background: {g['HOVER']}; }}
QComboBox, QLineEdit {{ background: {g['CARD']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 9px; padding: 7px 10px; min-width: 150px; }}
QComboBox:hover, QLineEdit:hover, QLineEdit:focus {{ border-color: {g['TEXT_MUTED']}; }} QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {g['BG_ELEVATED']}; border: 1px solid {g['CARD_BORDER']}; selection-background-color: {g['TEXT']}; selection-color: {g['BG']}; padding: 4px; outline: none; }}
QProgressBar {{ background: {g['TRACK']}; border: none; border-radius: 2px; height: 6px; text-align: center; color: transparent; }} QProgressBar::chunk {{ background: {g['ACCENT']}; border-radius: 2px; }}
QPlainTextEdit {{ background: {g['CONSOLE_BG']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 10px; padding: 10px; font-family: \"Cascadia Mono\", \"Consolas\"; font-size: 11px; color: {g['TEXT_MUTED']}; selection-background-color: {g['TEXT']}; selection-color: {g['BG']}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }} QScrollBar:vertical {{ background: transparent; width: 7px; margin: 2px; }} QScrollBar::handle:vertical {{ background: {g['SCROLL']}; border-radius: 0; min-height: 30px; }} QScrollBar::handle:vertical:hover {{ background: {g['SCROLL_HOVER']}; }} QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ height: 0; background: transparent; }}
QMenu {{ background: {g['BG_ELEVATED']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 10px; padding: 5px; }} QMenu::item {{ padding: 7px 22px 7px 14px; border: 1px solid transparent; border-radius: 6px; }} QMenu::item:selected {{ background: {g['HOVER']}; border-color: {g['CARD_BORDER']}; }} QMenu::separator {{ height: 1px; background: {g['CARD_BORDER']}; margin: 5px 8px; }}
#dialogShell {{ background: {g['BG']}; border: 1px solid {g['CARD_BORDER']}; border-radius: 16px; }}
"""


apply(DARK, DEFAULT_ACCENT)
