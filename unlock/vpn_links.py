"""Parsing of user-supplied VPN share links into sing-box outbounds.

Handles the five link formats people actually paste around: ``vless://``,
``vmess://``, ``trojan://``, ``ss://`` and ``hysteria2://``. A subscription is
just a newline list of those, usually base64-wrapped once more.

Nothing here talks to the network or the filesystem — it is pure text in,
outbound dict out, so it can be unit-tested and reused by the QR/file importers.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, unquote, urlsplit

SCHEMES = ("vless", "vmess", "trojan", "ss", "hysteria2", "hy2")


class VpnLinkError(ValueError):
    """The pasted text is not a share link this app understands."""


def _b64(text: str) -> str:
    """Decode base64 that may be URL-safe and is usually missing its padding."""
    cleaned = re.sub(r"\s+", "", text).replace("-", "+").replace("_", "/")
    padded = cleaned + "=" * (-len(cleaned) % 4)
    try:
        return base64.b64decode(padded).decode("utf-8", "replace")
    except (binascii.Error, ValueError) as exc:
        raise VpnLinkError("Malformed base64 payload") from exc


def _truthy(value: str | None) -> bool:
    return str(value).lower() in ("1", "true", "yes")


# ------------------------------------------------------------------ profile


@dataclass
class Profile:
    """One importable server, plus the sing-box outbound it expands to."""

    name: str
    protocol: str
    server: str
    port: int
    outbound: dict = field(default_factory=dict)
    link: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def endpoint(self) -> str:
        return f"{self.server}:{self.port}"

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "protocol": self.protocol,
            "server": self.server,
            "port": self.port,
            "outbound": self.outbound,
            "link": self.link,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        profile = cls(
            name=str(data.get("name") or "Server"),
            protocol=str(data.get("protocol") or "vless"),
            server=str(data.get("server") or ""),
            port=int(data.get("port") or 443),
            outbound=dict(data.get("outbound") or {}),
            link=str(data.get("link") or ""),
        )
        stored_id = data.get("id")
        if isinstance(stored_id, str) and stored_id:
            profile.id = stored_id
        # Older releases saved the raw share link but discarded transports that
        # sing-box does not implement (notably mKCP and XHTTP). Reparse it on
        # load so saved profiles gain the Xray settings without making people
        # delete and import their subscription again.
        if profile.protocol == "vless" and profile.link and "_xray" not in profile.outbound:
            try:
                refreshed = parse_link(profile.link)
            except (VpnLinkError, ValueError, KeyError):
                pass
            else:
                profile.outbound = refreshed.outbound
        return profile


# ------------------------------------------------------------------ transports


def _tls_block(query: dict, default_sni: str) -> dict | None:
    security = (query.get("security") or "").lower()
    if security not in ("tls", "reality", "xtls"):
        return None

    tls: dict = {
        "enabled": True,
        "server_name": query.get("sni") or query.get("peer") or default_sni,
        "insecure": _truthy(query.get("allowInsecure")) or _truthy(query.get("insecure")),
    }
    fingerprint = query.get("fp")
    if security == "reality":
        # REALITY hides behind a real TLS handshake, so it needs the site's
        # public key and the short id issued with it.
        tls["reality"] = {
            "enabled": True,
            "public_key": query.get("pbk", ""),
            "short_id": query.get("sid", ""),
        }
        # utls is mandatory for REALITY: the server checks the ClientHello shape.
        tls["utls"] = {"enabled": True, "fingerprint": fingerprint or "chrome"}
    elif fingerprint:
        tls["utls"] = {"enabled": True, "fingerprint": fingerprint}

    alpn = query.get("alpn")
    if alpn:
        tls["alpn"] = [part for part in unquote(alpn).split(",") if part]
    return tls


def _transport_block(query: dict) -> dict | None:
    kind = (query.get("type") or query.get("net") or "tcp").lower()
    host = unquote(query.get("host") or "")
    path = unquote(query.get("path") or "")

    if kind in ("ws", "websocket"):
        transport: dict = {"type": "ws", "path": path or "/"}
        if host:
            transport["headers"] = {"Host": host}
        # v2ray packs the real early-data length into the path as ?ed=2048.
        if "ed=" in path:
            base, _, tail = path.partition("?ed=")
            transport["path"] = base or "/"
            transport["max_early_data"] = int(re.sub(r"\D", "", tail) or 2048)
            transport["early_data_header_name"] = "Sec-WebSocket-Protocol"
        return transport
    if kind in ("grpc", "gun"):
        return {"type": "grpc", "service_name": query.get("serviceName") or path.strip("/")}
    if kind in ("http", "h2"):
        block: dict = {"type": "http", "path": path or "/"}
        if host:
            block["host"] = host.split(",")
        return block
    if kind == "httpupgrade":
        block = {"type": "httpupgrade", "path": path or "/"}
        if host:
            block["host"] = host
        return block
    return None


def _apply_stream(outbound: dict, query: dict, default_sni: str) -> None:
    tls = _tls_block(query, default_sni)
    if tls:
        outbound["tls"] = tls
    transport = _transport_block(query)
    if transport:
        outbound["transport"] = transport


def _int_param(query: dict, name: str) -> int | None:
    try:
        return int(query[name]) if query.get(name) else None
    except (TypeError, ValueError):
        return None


def _xray_stream(query: dict, default_sni: str) -> dict | None:
    """Translate VLESS transports implemented by Xray but not sing-box.

    sing-box deliberately has no mKCP transport. XHTTP is likewise an Xray
    transport.  Keep the original link parameters in a compact Xray-specific
    block so the normal sing-box outbound never sees unknown fields.
    """
    kind = (query.get("type") or query.get("net") or "tcp").lower()
    if kind not in ("kcp", "mkcp", "xhttp", "splithttp"):
        return None

    security = (query.get("security") or "none").lower()
    stream: dict = {
        "network": "kcp" if kind in ("kcp", "mkcp") else "xhttp",
        "security": security,
    }
    server_name = query.get("sni") or query.get("peer") or default_sni
    if security == "reality":
        stream["realitySettings"] = {
            "serverName": server_name,
            "fingerprint": query.get("fp") or "chrome",
            "publicKey": query.get("pbk", ""),
            "shortId": query.get("sid", ""),
            "spiderX": query.get("spx") or "/",
        }
    elif security in ("tls", "xtls"):
        tls = {
            "serverName": server_name,
            "allowInsecure": _truthy(query.get("allowInsecure")) or _truthy(query.get("insecure")),
        }
        if query.get("fp"):
            tls["fingerprint"] = query["fp"]
        if query.get("alpn"):
            tls["alpn"] = [part for part in unquote(query["alpn"]).split(",") if part]
        stream["tlsSettings"] = tls

    if kind in ("kcp", "mkcp"):
        kcp = {key: value for key, value in (
            ("mtu", _int_param(query, "mtu")),
            ("tti", _int_param(query, "tti")),
        ) if value is not None}
        if kcp:
            stream["kcpSettings"] = kcp
        # V2RayTun exports its mKCP disguise as ``mkcp-legacy``. Current Xray
        # renamed these masks: the traditional headers are ``header-*`` and
        # the bare/encrypted variants are ``mkcp-original`` /
        # ``mkcp-aes128gcm``.
        if query.get("fm"):
            try:
                finalmask = json.loads(query["fm"])
            except (TypeError, ValueError):
                finalmask = None
            masks = finalmask.get("udp") if isinstance(finalmask, dict) else None
            if isinstance(masks, list):
                translated: list[dict] = []
                for item in masks:
                    if not isinstance(item, dict) or item.get("type") != "mkcp-legacy":
                        continue
                    options = item.get("settings")
                    options = options if isinstance(options, dict) else {}
                    header = str(options.get("header") or "")
                    value = str(options.get("value") or "")
                    if header:
                        translated.append({"type": f"header-{header}", "settings": {}})
                    else:
                        translated.append({
                            "type": "mkcp-aes128gcm" if value else "mkcp-original",
                            "settings": {"password": value} if value else {},
                        })
                if translated:
                    stream["finalmask"] = {"udp": translated}
    else:
        stream["xhttpSettings"] = {
            "path": unquote(query.get("path") or "/"),
            "mode": query.get("mode") or "auto",
        }
        host = unquote(query.get("host") or "")
        if host:
            stream["xhttpSettings"]["host"] = host
    return stream


# ------------------------------------------------------------------ per-scheme


def _parse_vless(url, query: dict, tag: str) -> Profile:
    outbound = {
        "type": "vless",
        "tag": tag,
        "server": url.hostname,
        "server_port": url.port or 443,
        "uuid": unquote(url.username or ""),
    }
    flow = query.get("flow")
    if flow:
        outbound["flow"] = flow
    if (query.get("encryption") or "none") != "none":
        outbound["packet_encoding"] = query["encryption"]
    xray_stream = _xray_stream(query, url.hostname or "")
    if xray_stream:
        outbound["_xray"] = {
            "stream": xray_stream,
            "encryption": query.get("encryption") or "none",
        }
    else:
        _apply_stream(outbound, query, url.hostname or "")
    return Profile(tag, "vless", url.hostname or "", url.port or 443, outbound)


def _parse_trojan(url, query: dict, tag: str) -> Profile:
    outbound = {
        "type": "trojan",
        "tag": tag,
        "server": url.hostname,
        "server_port": url.port or 443,
        "password": unquote(url.username or ""),
    }
    # Trojan is TLS-only, so a link that omits security= still means TLS.
    _apply_stream(outbound, {**query, "security": query.get("security") or "tls"},
                  url.hostname or "")
    return Profile(tag, "trojan", url.hostname or "", url.port or 443, outbound)


def _parse_hysteria2(url, query: dict, tag: str) -> Profile:
    outbound = {
        "type": "hysteria2",
        "tag": tag,
        "server": url.hostname,
        "server_port": url.port or 443,
        "password": unquote(url.username or ""),
        "tls": {
            "enabled": True,
            "server_name": query.get("sni") or url.hostname,
            "insecure": _truthy(query.get("insecure")),
        },
    }
    obfs_password = query.get("obfs-password")
    if query.get("obfs") and obfs_password:
        outbound["obfs"] = {"type": query["obfs"], "password": obfs_password}
    return Profile(tag, "hysteria2", url.hostname or "", url.port or 443, outbound)


def _parse_shadowsocks(raw: str, tag: str) -> Profile:
    body = raw[len("ss://"):]
    fragment = ""
    if "#" in body:
        body, fragment = body.split("#", 1)
    body = body.split("?", 1)[0]

    if "@" in body:
        userinfo, endpoint = body.rsplit("@", 1)
        # SIP002 base64-encodes only the method:password half.
        if ":" not in userinfo:
            userinfo = _b64(userinfo)
    else:
        decoded = _b64(body)
        if "@" not in decoded:
            raise VpnLinkError("Shadowsocks link is missing its server address")
        userinfo, endpoint = decoded.rsplit("@", 1)

    method, _, password = userinfo.partition(":")
    host, _, port = endpoint.rpartition(":")
    name = unquote(fragment) or f"{host}:{port}"
    outbound = {
        "type": "shadowsocks",
        "tag": name,
        "server": host,
        "server_port": int(port or 443),
        "method": method,
        "password": unquote(password),
    }
    return Profile(name, "shadowsocks", host, int(port or 443), outbound)


def _parse_vmess(raw: str) -> Profile:
    """vmess:// is a base64 blob of JSON rather than a real URL."""
    payload = json.loads(_b64(raw[len("vmess://"):]))
    host = str(payload.get("add") or "")
    port = int(payload.get("port") or 443)
    name = str(payload.get("ps") or f"{host}:{port}")

    outbound = {
        "type": "vmess",
        "tag": name,
        "server": host,
        "server_port": port,
        "uuid": str(payload.get("id") or ""),
        "security": str(payload.get("scy") or "auto"),
        "alter_id": int(payload.get("aid") or 0),
    }
    query = {
        "security": str(payload.get("tls") or ""),
        "sni": str(payload.get("sni") or payload.get("host") or ""),
        "type": str(payload.get("net") or "tcp"),
        "host": str(payload.get("host") or ""),
        "path": str(payload.get("path") or ""),
        "serviceName": str(payload.get("path") or ""),
        "fp": str(payload.get("fp") or ""),
        "alpn": str(payload.get("alpn") or ""),
    }
    _apply_stream(outbound, {k: v for k, v in query.items() if v}, host)
    return Profile(name, "vmess", host, port, outbound)


_PARSERS = {
    "vless": _parse_vless,
    "trojan": _parse_trojan,
    "hysteria2": _parse_hysteria2,
    "hy2": _parse_hysteria2,
}


def parse_link(raw: str) -> Profile:
    """Turn one share link into a Profile. Raises VpnLinkError on anything else."""
    raw = raw.strip()
    scheme = raw.split("://", 1)[0].lower() if "://" in raw else ""
    if scheme not in SCHEMES:
        raise VpnLinkError(f"Unsupported link type: {scheme or raw[:24]}")

    if scheme == "vmess":
        profile = _parse_vmess(raw)
    elif scheme == "ss":
        profile = _parse_shadowsocks(raw, "")
    else:
        url = urlsplit(raw)
        if not url.hostname:
            raise VpnLinkError("Link is missing a server address")
        query = dict(parse_qsl(url.query, keep_blank_values=True))
        tag = unquote(url.fragment) or f"{url.hostname}:{url.port or 443}"
        profile = _PARSERS[scheme](url, query, tag)

    if not profile.server:
        raise VpnLinkError("Link is missing a server address")
    profile.link = raw
    return profile


def parse_many(text: str) -> list[Profile]:
    """Parse a subscription body: plain lines, or one base64 blob of them."""
    text = text.strip()
    if not text:
        return []
    if "://" not in text:
        # A subscription URL's body is base64 over the whole newline list.
        text = _b64(text)

    profiles: list[Profile] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "//")):
            continue
        try:
            profiles.append(parse_link(line))
        except (VpnLinkError, ValueError, KeyError):
            continue
    if not profiles:
        raise VpnLinkError("No usable servers found")
    return profiles
