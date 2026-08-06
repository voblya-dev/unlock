"""Bringing VPN profiles in from a link, a file, a subscription URL or a QR code.

Every entry point funnels into :mod:`unlock.vpn_links`; this module only deals
with getting the text out of whatever the user handed over.

QR decoding needs OpenCV, which is a large optional dependency. When it is not
installed the rest of the importers keep working and the caller gets a clear
message instead of an ImportError.
"""

from __future__ import annotations

from pathlib import Path

from .logger import get_logger
from . import vpn_wireguard
from .vpn_links import Profile, VpnLinkError, parse_link, parse_many

log = get_logger("vpnimport")

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif")
CONFIG_SUFFIXES = (".conf", ".txt", ".json", ".yaml", ".yml", ".ini")

_FETCH_TIMEOUT = 15
_MAX_SUBSCRIPTION_BYTES = 4 * 1024 * 1024


def from_text(text: str, name: str = "") -> list[Profile]:
    """A pasted link, a pile of links, a subscription body, or a wg-quick file."""
    text = text.strip()
    if not text:
        raise VpnLinkError("Nothing to import")
    if text.lower().startswith("vpn://"):
        return [vpn_wireguard.parse_amnezia_link(text)]
    if vpn_wireguard.looks_like_conf(text):
        return [vpn_wireguard.parse_conf(text, name)]
    if text.lower().startswith(("http://", "https://")):
        return from_subscription(text)
    if "\n" in text or text.count("://") > 1 or "://" not in text:
        return parse_many(text)
    return [parse_link(text)]


def from_subscription(url: str) -> list[Profile]:
    """Fetch a subscription URL and parse whatever it serves."""
    import requests

    try:
        response = requests.get(
            url, timeout=_FETCH_TIMEOUT, headers={"User-Agent": "unlock"}
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise VpnLinkError(f"Could not fetch the subscription: {exc}") from exc

    if len(response.content) > _MAX_SUBSCRIPTION_BYTES:
        raise VpnLinkError("Subscription response is too large")
    return parse_many(response.text)


def from_file(path: str | Path) -> list[Profile]:
    """Import from a saved image (QR) or any text file holding links."""
    path = Path(path)
    if path.suffix.lower() in IMAGE_SUFFIXES:
        return from_image(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise VpnLinkError(f"Could not read {path.name}: {exc}") from exc
    # A wg-quick file carries no name of its own, so the filename is the only
    # label the user will recognise it by.
    return from_text(text, name=path.stem)


# ------------------------------------------------------------------ QR


def qr_available() -> bool:
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False
    return True


def decode_qr(path: str | Path) -> str:
    """Text carried by the QR code in an image file."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise VpnLinkError(
            "QR import needs OpenCV. Install it with: pip install opencv-python-headless"
        ) from exc

    path = Path(path)
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError as exc:
        raise VpnLinkError(f"Could not read {path.name}: {exc}") from exc

    # imdecode rather than imread: imread cannot open a non-ASCII path on Windows.
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise VpnLinkError(f"{path.name} is not an image this app can read")

    detector = cv2.QRCodeDetector()
    text, _points, _straight = detector.detectAndDecode(image)
    if not text:
        # Screenshots of a phone screen are often too small for the detector at
        # native size; one upscale pass recovers most of them.
        bigger = cv2.resize(image, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        text, _points, _straight = detector.detectAndDecode(bigger)
    if not text:
        raise VpnLinkError("No QR code found in that image")
    return text


def from_image(path: str | Path) -> list[Profile]:
    return from_text(decode_qr(path))
