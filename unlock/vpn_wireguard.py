"""Parsing of WireGuard and AmneziaWG configs into a wireproxy profile.

WireGuard is not a share link — it is handed out as a ``wg-quick`` INI file, or
as an AmneziaVPN ``vpn://`` blob that wraps the same fields in compressed JSON.
Both land in the same :class:`~unlock.vpn_links.Profile`, carrying the interface
and peer sections in ``outbound`` so :mod:`unlock.vpn_engine` can render them
back out as a wireproxy config.

AmneziaWG is WireGuard plus obfuscation knobs: junk packets (``Jc``/``Jmin``/
``Jmax``), header sizes (``S1``-``S4``) and magic headers (``H1``-``H4``) in
1.0, plus custom signature packets (``I1``-``I5``) in 2.0. They are carried
through verbatim — wireproxy validates them, this module does not need to.
"""

from __future__ import annotations

import base64
import binascii
import configparser
import io
import json
import re
import zlib

from .vpn_links import Profile, VpnLinkError

# Obfuscation keys, in the order wireproxy wants to see them. Presence of any of
# these is what makes a config AmneziaWG rather than plain WireGuard.
AWG_KEYS = (
    "Jc", "Jmin", "Jmax",
    "S1", "S2", "S3", "S4",
    "H1", "H2", "H3", "H4",
    "I1", "I2", "I3", "I4", "I5",
)

# I1-I5 are the 2.0 additions; a config using them is not readable by a 1.0
# client, which is the only distinction the UI needs to draw.
AWG_V2_KEYS = ("I1", "I2", "I3", "I4", "I5", "S3", "S4")

_KEY_RE = re.compile(r"^[A-Za-z0-9+/]{42,44}=*$")


def _clean_key(value: str, field: str) -> str:
    """A base64 x25519 key, or a clear error naming the field that is wrong."""
    value = value.strip()
    if not _KEY_RE.match(value):
        raise VpnLinkError(f"{field} is not a valid WireGuard key")
    try:
        if len(base64.b64decode(value + "=" * (-len(value) % 4))) != 32:
            raise VpnLinkError(f"{field} is not a 32-byte key")
    except binascii.Error as exc:
        raise VpnLinkError(f"{field} is not valid base64") from exc
    return value


def _split_list(value: str) -> list[str]:
    return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]


def _endpoint(value: str) -> tuple[str, int]:
    """Split ``host:port``, tolerating a bracketed IPv6 literal."""
    value = value.strip()
    if value.startswith("["):
        host, _, port = value.partition("]")
        host, port = host[1:], port.lstrip(":")
    else:
        host, _, port = value.rpartition(":")
    if not host or not port.isdigit():
        raise VpnLinkError(f"Endpoint '{value}' is not host:port")
    return host, int(port)


# ------------------------------------------------------------------ wg-quick


def parse_conf(text: str, name: str = "") -> Profile:
    """Turn a wg-quick / AmneziaWG .conf into a Profile."""
    parser = configparser.RawConfigParser(strict=False)
    # wg-quick keys are case-sensitive in spirit (PrivateKey, not privatekey) and
    # configparser lowercases by default, which would lose the H1/Jc spellings.
    parser.optionxform = str
    try:
        parser.read_file(io.StringIO(text))
    except configparser.Error as exc:
        raise VpnLinkError(f"Not a readable WireGuard config: {exc}") from exc

    sections = {section.lower(): section for section in parser.sections()}
    if "interface" not in sections or "peer" not in sections:
        raise VpnLinkError("Config needs both an [Interface] and a [Peer] section")

    interface = dict(parser.items(sections["interface"]))
    peer = dict(parser.items(sections["peer"]))
    return _build(interface, peer, name)


def _build(interface: dict, peer: dict, name: str) -> Profile:
    def pick(source: dict, *names: str) -> str:
        for key in names:
            for actual, value in source.items():
                if actual.lower() == key.lower():
                    return value.split("#")[0].strip()
        return ""

    private_key = pick(interface, "PrivateKey")
    public_key = pick(peer, "PublicKey")
    endpoint = pick(peer, "Endpoint")
    if not private_key or not public_key or not endpoint:
        raise VpnLinkError("Config is missing PrivateKey, PublicKey or Endpoint")

    host, port = _endpoint(endpoint)
    addresses = _split_list(pick(interface, "Address")) or ["10.0.0.2/32"]
    allowed = _split_list(pick(peer, "AllowedIPs")) or ["0.0.0.0/0", "::/0"]

    settings: dict = {
        "type": "wireguard",
        "private_key": _clean_key(private_key, "PrivateKey"),
        "public_key": _clean_key(public_key, "PublicKey"),
        "server": host,
        "server_port": port,
        "address": addresses,
        "allowed_ips": allowed,
    }

    dns = _split_list(pick(interface, "DNS"))
    if dns:
        settings["dns"] = dns
    mtu = pick(interface, "MTU")
    if mtu.isdigit():
        settings["mtu"] = int(mtu)
    keepalive = pick(peer, "PersistentKeepalive")
    if keepalive.isdigit():
        settings["keepalive"] = int(keepalive)
    preshared = pick(peer, "PresharedKey")
    if preshared:
        settings["pre_shared_key"] = _clean_key(preshared, "PresharedKey")

    obfuscation = {key: pick(interface, key) for key in AWG_KEYS}
    obfuscation = {key: value for key, value in obfuscation.items() if value}
    if obfuscation:
        settings["awg"] = obfuscation

    protocol = "amneziawg" if obfuscation else "wireguard"
    label = name or f"{host}:{port}"
    return Profile(label, protocol, host, port, settings)


def is_v2(profile: Profile) -> bool:
    """True when the profile uses AmneziaWG 2.0-only knobs."""
    awg = profile.outbound.get("awg") or {}
    return any(key in awg for key in AWG_V2_KEYS)


def looks_like_conf(text: str) -> bool:
    lowered = text.lower()
    return "[interface]" in lowered and "[peer]" in lowered


# ------------------------------------------------------------------ vpn://


def _inflate(blob: bytes) -> bytes:
    """AmneziaVPN prefixes a 4-byte big-endian length, then raw zlib."""
    for candidate in (blob[4:], blob):
        for wbits in (15, -15, 47):
            try:
                return zlib.decompress(candidate, wbits)
            except zlib.error:
                continue
    raise VpnLinkError("vpn:// payload is not readable")


def parse_amnezia_link(raw: str) -> Profile:
    """Decode an AmneziaVPN ``vpn://`` share link."""
    body = raw.strip()[len("vpn://"):]
    padded = body.replace("-", "+").replace("_", "/")
    padded += "=" * (-len(padded) % 4)
    try:
        blob = base64.b64decode(padded)
    except binascii.Error as exc:
        raise VpnLinkError("vpn:// link is not valid base64") from exc

    try:
        payload = json.loads(_inflate(blob).decode("utf-8", "replace"))
    except (ValueError, VpnLinkError) as exc:
        raise VpnLinkError(f"vpn:// link could not be decoded: {exc}") from exc

    return _from_amnezia_payload(payload)


def _from_amnezia_payload(payload: dict) -> Profile:
    """Pull the wg-quick text out of an AmneziaVPN container JSON."""
    name = str(payload.get("description") or payload.get("name") or "")

    containers = payload.get("containers")
    if isinstance(containers, list):
        for container in containers:
            if not isinstance(container, dict):
                continue
            for key in ("awg", "wireguard"):
                block = container.get(key)
                if isinstance(block, dict):
                    config = block.get("last_config")
                    if isinstance(config, str) and config:
                        return _from_amnezia_config(config, name)

    # A single-protocol export skips the container list entirely.
    for key in ("awg", "wireguard"):
        block = payload.get(key)
        if isinstance(block, dict) and isinstance(block.get("last_config"), str):
            return _from_amnezia_config(block["last_config"], name)

    raise VpnLinkError("vpn:// link has no WireGuard or AmneziaWG config in it")


def _from_amnezia_config(config: str, name: str) -> Profile:
    """``last_config`` is itself JSON holding a wg-quick blob plus overrides."""
    try:
        inner = json.loads(config)
    except ValueError:
        # Some exports store the .conf text directly.
        return parse_conf(config, name)

    text = str(inner.get("config") or "")
    if not text:
        raise VpnLinkError("vpn:// link has an empty config")

    # AmneziaVPN leaves $PRIMARY_DNS-style placeholders in the blob and supplies
    # the values alongside; substituting them keeps the .conf parseable.
    for placeholder, key in (
        ("$PRIMARY_DNS", "hostName"),
        ("$SECONDARY_DNS", "hostName"),
        ("$WIREGUARD_CLIENT_IP", "client_ip"),
        ("$WIREGUARD_SERVER_IP", "hostName"),
    ):
        value = inner.get(key)
        if placeholder in text and isinstance(value, str) and value:
            text = text.replace(placeholder, value)

    profile = parse_conf(text, name)
    port = inner.get("port")
    if isinstance(port, (int, str)) and str(port).isdigit():
        profile.port = int(port)
        profile.outbound["server_port"] = int(port)
    return profile


__all__ = [
    "AWG_KEYS",
    "AWG_V2_KEYS",
    "is_v2",
    "looks_like_conf",
    "parse_amnezia_link",
    "parse_conf",
]
