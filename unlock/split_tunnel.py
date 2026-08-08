"""Split tunneling — rule storage and sing-box route rule generation.

Two modes:
  Blacklist — all traffic goes through the VPN; matched rules are sent direct.
  Whitelist — only matched rules go through the VPN; everything else is direct.

Rules carry a type (app / domain / ip), the value itself, a display label and
an enabled flag so the user can temporarily disable without losing the entry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config


class RuleMode(str, Enum):
    BLACKLIST = "blacklist"
    WHITELIST = "whitelist"


class RuleType(str, Enum):
    APP    = "app"
    DOMAIN = "domain"
    IP     = "ip"


_DOMAIN_RE = re.compile(
    r"^(\*\.)?(?=.{1,253}$)([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}$"
)


def normalize_domain_input(text: str) -> str:
    """Turn any user-typed site reference into a canonical domain mask.

    Accepts all the shapes people actually paste into the field:
      https://www.ozon.ru/path?q=1   -> ozon.ru
      www.ozon.ru                    -> ozon.ru
      WWW.OZON.RU                    -> ozon.ru
      *.ozon.ru                      -> ozon.ru   (domain_suffix already covers subs)
      ozon.ru/                       -> ozon.ru
      https://static.ozon.ru         -> static.ozon.ru
    Returns the cleaned string as-is when it does not look like a domain, so
    the caller can decide whether to keep or reject it.
    """
    v = text.strip().lower()
    if not v:
        return ""
    # Strip scheme and anything after the host.
    if "://" in v:
        v = v.split("://", 1)[1]
    # Strip userinfo (user:pass@host).
    if "@" in v:
        v = v.split("@", 1)[1]
    # Strip path, query, fragment, port.
    v = re.split(r"[/:?#]", v, 1)[0]
    # Strip wildcard prefix — domain_suffix matching already includes subdomains.
    if v.startswith("*."):
        v = v[2:]
    # A leading "www." is redundant for the same reason.
    if v.startswith("www."):
        v = v[4:]
    v = v.rstrip(".")
    if not v:
        return text.strip().lower()
    return v if _DOMAIN_RE.match(v) else text.strip().lower()


@dataclass
class SplitTunnelRule:
    type:    RuleType
    value:   str           # exe path / domain mask / CIDR
    label:   str   = ""    # human-readable name shown in the list
    enabled: bool  = True


class SplitTunnelingManager:
    """Persists split-tunnel rules and converts them to sing-box route dicts."""

    def __init__(self, config: "Config") -> None:
        self._cfg = config

    # ── persistence ──────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(self._cfg.get("split_tunnel_enabled", False))

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._cfg.set("split_tunnel_enabled", value)

    @property
    def mode(self) -> RuleMode:
        raw = self._cfg.get("split_tunnel_mode", RuleMode.BLACKLIST.value)
        try:
            return RuleMode(raw)
        except ValueError:
            return RuleMode.BLACKLIST

    @mode.setter
    def mode(self, value: RuleMode) -> None:
        self._cfg.set("split_tunnel_mode", value.value)

    def rules(self) -> list[SplitTunnelRule]:
        raw = self._cfg.get("split_tunnel_rules") or []
        out: list[SplitTunnelRule] = []
        for item in raw:
            try:
                out.append(SplitTunnelRule(
                    type=RuleType(item["type"]),
                    value=item["value"],
                    label=item.get("label", ""),
                    enabled=bool(item.get("enabled", True)),
                ))
            except (KeyError, ValueError):
                pass
        return out

    def save_rules(self, rules: list[SplitTunnelRule]) -> None:
        self._cfg.set("split_tunnel_rules", [
            {"type": r.type.value, "value": r.value,
             "label": r.label, "enabled": r.enabled}
            for r in rules
        ])

    def add_rule(self, rule: SplitTunnelRule) -> None:
        current = self.rules()
        if rule.type is RuleType.DOMAIN:
            norm = normalize_domain_input(rule.value)
            rule = SplitTunnelRule(
                type=rule.type, value=norm, label=norm, enabled=rule.enabled
            )
            if not norm:
                return
        # Avoid exact duplicates (same type + value).
        if any(r.type == rule.type and r.value == rule.value for r in current):
            return
        self.save_rules([*current, rule])

    def remove_rule(self, index: int) -> None:
        current = self.rules()
        if 0 <= index < len(current):
            del current[index]
            self.save_rules(current)

    def set_rule_enabled(self, index: int, enabled: bool) -> None:
        current = self.rules()
        if 0 <= index < len(current):
            current[index].enabled = enabled
            self.save_rules(current)

    def rules_of(self, rule_type: RuleType) -> list[tuple[int, SplitTunnelRule]]:
        """Return (global_index, rule) pairs for one RuleType."""
        return [
            (i, r) for i, r in enumerate(self.rules())
            if r.type == rule_type
        ]

    # ── sing-box rule generation ──────────────────────────────────────────────

    def singbox_route_rules(self) -> list[dict]:
        """Return sing-box route rule dicts to inject into build_tun_config().

        Blacklist mode: active rules route to "direct" (bypass the VPN).
        Whitelist mode: active rules route to "proxy" (force through the VPN).
        The caller must also change the route's "final" outbound when in
        whitelist mode — see whitelist_final_outbound().
        """
        if not self.enabled:
            return []

        active = [r for r in self.rules() if r.enabled]
        if not active:
            return []

        target = "direct" if self.mode is RuleMode.BLACKLIST else "proxy"

        apps    = [r.value for r in active if r.type is RuleType.APP]
        domains = [r.value for r in active if r.type is RuleType.DOMAIN]
        ips     = [r.value for r in active if r.type is RuleType.IP]

        rules: list[dict] = []
        if apps:
            rules.append({"process_name": apps, "outbound": target})
        if domains:
            # domain_suffix covers *.example.com automatically in sing-box.
            rules.append({"domain_suffix": domains, "outbound": target})
        if ips:
            rules.append({"ip_cidr": ips, "outbound": target})

        return rules

    def whitelist_final_outbound(self) -> str | None:
        """Whitelist mode needs "direct" as the catch-all instead of "proxy".

        Returns "direct" when whitelist is active, None otherwise so the caller
        keeps its normal "proxy" final outbound unchanged.
        """
        if self.enabled and self.mode is RuleMode.WHITELIST:
            return "direct"
        return None
