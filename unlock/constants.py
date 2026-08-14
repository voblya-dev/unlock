"""Global paths, constants and default settings for Unlock."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Unlock"
APP_VERSION = "1.1.4"

# ---------------------------------------------------------------- paths


def _base_dir() -> Path:
    """Directory that holds bundled read-only resources.

    PyInstaller unpacks one-file builds into a temp dir exposed as
    ``sys._MEIPASS``; in a source checkout it is the repo root.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()

# Where the running .exe actually lives. Distinct from BASE_DIR: in a one-file
# build BASE_DIR is a temp dir that is wiped on exit, so anything the user is
# meant to drop in by hand has to be looked for here instead.
INSTALL_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)

# Writable per-user location: never write next to the .exe, Program Files is
# read-only for non-elevated writes and roaming profiles need this anyway.
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
LOG_DIR = DATA_DIR / "logs"
CONFIG_PATH = DATA_DIR / "config.json"
LOG_PATH = LOG_DIR / "unlock.log"

BIN_DIR = BASE_DIR / "bin"
ZAPRET_DIR = BIN_DIR / "zapret"
WINWS_EXE = ZAPRET_DIR / "winws.exe"
LISTS_DIR = ZAPRET_DIR / "lists"
CONFIGS_DIR = ZAPRET_DIR / "configs"

# Per-user zapret extensions. ``bin/zapret`` is a bundled, potentially
# read-only PyInstaller resource, so generated runtime lists live in AppData.
# Zapret-GUI rebuilds list-general/ipset-all from the bundled base plus the
# user's rules before launch; Unlock mirrors that without mutating its bundle.
ZAPRET_USER_LISTS_DIR = DATA_DIR / "zapret-lists"
ZAPRET_USER_HOSTLIST_PATH = ZAPRET_USER_LISTS_DIR / "unlock-hostlist.txt"
ZAPRET_USER_IPSET_PATH = ZAPRET_USER_LISTS_DIR / "unlock-ipset.txt"
ZAPRET_RUNTIME_HOSTLIST_PATH = ZAPRET_USER_LISTS_DIR / "list-general.txt"
ZAPRET_RUNTIME_IPSET_PATH = ZAPRET_USER_LISTS_DIR / "ipset-all.txt"
ZAPRET_RUNTIME_EMPTY_HOSTLIST_PATH = ZAPRET_USER_LISTS_DIR / "list-general-user.txt"
SITE_LISTS_PATH = DATA_DIR / "sites.json"
HOSTS_BACKUP_PATH = DATA_DIR / "hosts.unlock.backup"
AI_HOSTS_CACHE_PATH = DATA_DIR / "ai-hosts.txt"

# VPN engines are bundled with the signed application. Do not search a
# per-user writable directory from this elevated process.
SINGBOX_SEARCH_DIRS = (
    BIN_DIR / "sing-box",
)

WIREPROXY_SEARCH_DIRS = (
    BIN_DIR / "wireproxy",
)

XRAY_SEARCH_DIRS = (
    BIN_DIR / "xray",
)

# Amnezia's own Windows client, used headless. Unlike wireproxy it drives a real
# Wintun adapter, so UDP works — Discord voice, games, QUIC. wintun.dll must sit
# next to the exe; amneziawg.exe loads it by name from its own directory.
AMNEZIAWG_SEARCH_DIRS = (
    BIN_DIR / "amneziawg",
)

VPN_CONFIG_PATH = DATA_DIR / "vpn-config.json"
WIREPROXY_CONFIG_PATH = DATA_DIR / "vpn-wg.conf"
XRAY_CONFIG_PATH = DATA_DIR / "vpn-xray.json"

# The tunnel service reads this file, and names its adapter after the stem.
# It must live somewhere SYSTEM can read: the service runs as LocalSystem, so a
# path under the user's roaming profile would be unreadable to it.
AMNEZIAWG_CONFIG_PATH = Path(os.environ.get("PROGRAMDATA", DATA_DIR)) / APP_NAME / "unlock.conf"
AMNEZIAWG_TUNNEL_NAME = "unlock"

for _d in (DATA_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- network

# Local MTProto port Telegram Desktop is pointed at. 1443 is what tg-ws-proxy
# uses, so a user who already has that app is not surprised by a different one.
TELEGRAM_PROXY_PORT = 1443

# SNI the fake-TLS handshake is dressed as, and the site an unrecognised client
# gets reverse proxied to. Only ever dialled if something other than Telegram
# connects to the local port, so it just has to be a real, reachable HTTPS host.
TELEGRAM_FAKE_TLS_DOMAIN = "www.microsoft.com"

# Local listeners for the user's own VPN profile. sing-box binds both: SOCKS is
# what the Windows system proxy is pointed at, HTTP is the fallback for apps
# that ignore a SOCKS setting.
VPN_SOCKS_PORT = 2080
VPN_HTTP_PORT = 2081

# TUN mode: sing-box owns a virtual adapter and forwards everything into the
# proxy above, so apps that ignore the Windows proxy setting — Telegram, games,
# anything on UDP — still follow the tunnel. Addresses are from the 172.19/16
# block sing-box itself defaults to, which nothing else on a home LAN uses.
VPN_TUN_ADDRESS = "172.19.0.1/30"
VPN_TUN_MTU = 1400
VPN_TUN_CONFIG_PATH = DATA_DIR / "vpn-tun.json"

# Endpoints used by the benchmark to score a strategy. Mirrors the target set
# from the zapret pack's own "test zapret.ps1" / utils/targets.txt.
PROBE_TARGETS = {
    "discord": [
        "https://discord.com",
        "https://gateway.discord.gg",
        "https://cdn.discordapp.com",
        "https://updates.discord.com",
    ],
    "youtube": [
        "https://www.youtube.com",
        "https://youtu.be",
        "https://i.ytimg.com",
        "https://redirector.googlevideo.com",
    ],
    "google": [
        "https://www.google.com",
        "https://www.gstatic.com",
    ],
    "cloudflare": [
        "https://www.cloudflare.com",
        "https://cdnjs.cloudflare.com",
    ],
}

# Ping-only targets: latency here is not affected by the hostlist, so it acts as
# a tie-break for "does this strategy slow the whole link down".
PING_TARGETS = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]

# Each URL is probed once per protocol; a strategy must pass all of them.
PROBE_PROTOCOLS = ("http1.1", "tls1.2", "tls1.3")

# How many probes run at once. The pack's script uses 8.
PROBE_PARALLEL = 8

PROBE_TIMEOUT = 3.0          # seconds per probe; blocked requests never return
# winws either binds the filter almost at once or dies on a bad argument vector,
# so start() polls for that instead of sleeping out a fixed grace period.
STRATEGY_SETTLE_TIMEOUT = 1.2
STRATEGY_SETTLE_POLL = 0.05
# The benchmark measures throughput, so it gives winws grace to settle before probing.
# Reduced from the pack's 5.0s: most strategies are broken and get rejected on the
# first probe anyway, so full settle is only worth it for the handful that pass triage.
BENCHMARK_SETTLE_DELAY = 2.5
# Quick triage probe uses even less settle — just enough for winws to bind the filter.
BENCHMARK_TRIAGE_SETTLE = 1.5

# ---------------------------------------------------------------- evolution

# The genetic search evaluates hundreds of candidates, and every evaluation
# costs a winws restart plus a full probe sweep. These trade breadth for time.
EVOLUTION_POPULATION = 12
EVOLUTION_GENERATIONS = 8
EVOLUTION_ELITES = 3           # carried to the next generation untouched
EVOLUTION_TOURNAMENT = 3       # entrants per parent selection
EVOLUTION_MUTATION_RATE = 0.25  # share of a genome's genes rewritten per mutation
EVOLUTION_CROSSOVER_CHANCE = 0.7
EVOLUTION_STALL_LIMIT = 3      # generations without improvement before stopping
EVOLUTION_TIME_BUDGET = 45 * 60  # seconds; a whole run must fit a coffee break

# Scoring a candidate uses a reduced target set: one URL per service is enough
# to rank a genome, and it cuts each evaluation to roughly a quarter of a full
# benchmark probe sweep. The winner is re-scored against the full set.
EVOLUTION_PROBE_TARGETS = {
    "discord": ["https://discord.com"],
    "youtube": ["https://www.youtube.com"],
    "google": ["https://www.google.com"],
    "cloudflare": ["https://www.cloudflare.com"],
}
EVOLUTION_PROBE_PROTOCOLS = ("http1.1", "tls1.3")
# winws needs less grace here than in the benchmark: the search only asks
# whether probes pass, not how fast, so it does not wait for throughput to settle.
EVOLUTION_SETTLE_DELAY = 2.5

# ---------------------------------------------------------------- defaults

DEFAULT_CONFIG: dict = {
    "first_run_done": False,
    "benchmark_skipped": False,  # user cancelled testing, picks the strategy manually
    "start_minimized": False,
    "auto_connect_on_launch": False,
    "auto_retest_days": 0,  # 0 = never; the user opts into a schedule
    "last_benchmark_utc": None,
    "dpi_strategy": None,        # name of the winws strategy chosen
    "enable_dpi": True,
    "enable_telegram": True,
    "telegram_auto_proxy": True,  # hand the local proxy to a running Telegram
    # Stable MTProto secret: Telegram recognises the proxy it already has
    # instead of being offered a fresh one after every restart.
    "telegram_secret": None,
    # Dress the local MTProto handshake as TLS (ee-secret). On by default: it is
    # the mode Telegram's own clients treat as ordinary HTTPS, and anything that
    # connects to the port without the right ClientHello sees a real website.
    "telegram_fake_tls": False,
    # Fold the game port range into the winws filter. Off by default: it widens
    # the filter from a handful of web ports to 1024-65535.
    "game_filter": False,
    "benchmark_results": {},
    "evolution_results": {},     # last genetic search summary
    "theme": "system",           # system | dark | light
    "accent": "mono",            # key from ui.theme.ACCENTS (white/black)
    "language": "system",        # system | en | ru
    "sounds": True,              # chime on connect / disconnect
    # --- custom VPN
    "vpn_profiles": [],          # list of vpn.Profile.as_dict()
    "vpn_active": None,          # id of the profile to bring up with the tunnel
    "vpn_tun": True,             # route every app through a TUN adapter
    "enable_vpn": False,
    "vpn_system_proxy": True,    # point Windows at the local SOCKS/HTTP port
    # --- split tunneling
    "split_tunnel_enabled": False,
    "split_tunnel_mode": "blacklist",  # blacklist | whitelist
    "split_tunnel_rules": [],    # apps / domains / IPs picked by the user
}
