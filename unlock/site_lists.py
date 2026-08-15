"""Per-user site rules and the zapret lists generated from them.

The zapret pack is shipped as an application resource and is deliberately
treated as immutable.  This module owns the small, versioned document under
``%APPDATA%\\Unlock`` and derives two plain-text files which winws can consume.
Keeping the editable records separate from the generated files makes updates
safe. AI-service mappings are deliberately separate: like current Zapret-GUI
they live in a managed Windows ``hosts`` block and never enter a winws list.
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from .constants import (
    LISTS_DIR,
    SITE_LISTS_PATH,
    ZAPRET_RUNTIME_EMPTY_HOSTLIST_PATH,
    ZAPRET_RUNTIME_HOSTLIST_PATH,
    ZAPRET_RUNTIME_IPSET_PATH,
    ZAPRET_USER_HOSTLIST_PATH,
    ZAPRET_USER_IPSET_PATH,
)
from .logger import get_logger

log = get_logger("site_lists")


class SiteRuleType(str, Enum):
    DOMAIN = "domain"
    IP = "ip"
    SUBNET = "subnet"


_DOMAIN_RE = re.compile(
    r"^(?:\*\.)?(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)

@dataclass(frozen=True)
class SiteRule:
    type: SiteRuleType
    value: str
    enabled: bool = True

    def as_dict(self) -> dict:
        return {
            "type": self.type.value,
            "value": self.value,
            "enabled": self.enabled,
        }


@dataclass(frozen=True)
class HostMapping:
    domain: str
    address: str

    def as_dict(self) -> dict:
        return {"domain": self.domain, "address": self.address}


@dataclass(frozen=True)
class ListUpdateResult:
    """What a list update did, suitable for concise UI feedback."""

    added: int = 0
    removed: int = 0
    changed: int = 0
    duplicates: int = 0
    invalid: tuple[str, ...] = ()

    @property
    def touched(self) -> bool:
        return bool(self.added or self.removed or self.changed)


def normalize_domain(value: str) -> str | None:
    """Return a canonical ASCII host mask, or ``None`` when it is invalid.

    The list editor accepts a full web address too. People normally copy the
    address-bar value, whereas winws needs only its hostname.
    """
    value = value.strip().lower()
    if "://" in value:
        try:
            value = urlsplit(value).hostname or ""
        except ValueError:
            return None
    else:
        value = value.split("/", 1)[0].split("?", 1)[0]
        # Strip the common ``host:443`` spelling but leave IPv6 alone: the
        # caller classifies a genuine IPv6 value before it reaches this path.
        if value.count(":") == 1:
            host, port = value.rsplit(":", 1)
            if port.isdigit():
                value = host
    value = value.rstrip(".")
    wildcard = value.startswith("*.")
    bare = value[2:] if wildcard else value
    if not bare or "/" in bare or any(ch.isspace() for ch in bare):
        return None
    try:
        # IDNA gives a stable representation for a pasted international name.
        bare = bare.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    normal = f"*.{bare}" if wildcard else bare
    return normal if _DOMAIN_RE.fullmatch(normal) else None


def parse_rule(value: str) -> SiteRule | None:
    """Classify and normalise one domain, IP address or CIDR value."""
    value = value.strip()
    if not value:
        return None
    # A slash normally denotes CIDR, except in a copied web address such as
    # ``https://example.com/path`` which is normalized below as a hostname.
    if "/" in value and "://" not in value:
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError:
            return None
        return SiteRule(SiteRuleType.SUBNET, str(network))
    try:
        return SiteRule(SiteRuleType.IP, str(ipaddress.ip_address(value)))
    except ValueError:
        # Four numeric labels look like a malformed IPv4 address, not a DNS
        # name.  Rejecting them prevents a typo such as 300.1.1.1 from being
        # silently written to a hostlist.
        if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", value):
            return None
    domain = normalize_domain(value)
    return SiteRule(SiteRuleType.DOMAIN, domain) if domain else None


def parse_import_lines(text: str) -> list[str]:
    """Return candidate lines, ignoring blank and comment-containing lines."""
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and "#" not in line
    ]


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


class SiteListManager:
    """Persistent site-record manager with atomic zapret-list generation."""

    def __init__(
        self,
        path: Path = SITE_LISTS_PATH,
        hostlist_path: Path = ZAPRET_USER_HOSTLIST_PATH,
        ipset_path: Path = ZAPRET_USER_IPSET_PATH,
        runtime_hostlist_path: Path | None = None,
        runtime_ipset_path: Path | None = None,
        runtime_empty_hostlist_path: Path | None = None,
        base_hostlist_path: Path = LISTS_DIR / "list-general.txt",
        base_ipset_path: Path = LISTS_DIR / "ipset-all.txt",
    ) -> None:
        self.path = path
        self.hostlist_path = hostlist_path
        self.ipset_path = ipset_path
        self.runtime_hostlist_path = (
            runtime_hostlist_path
            if runtime_hostlist_path is not None
            else hostlist_path.parent / ZAPRET_RUNTIME_HOSTLIST_PATH.name
        )
        self.runtime_ipset_path = (
            runtime_ipset_path
            if runtime_ipset_path is not None
            else ipset_path.parent / ZAPRET_RUNTIME_IPSET_PATH.name
        )
        self.runtime_empty_hostlist_path = (
            runtime_empty_hostlist_path
            if runtime_empty_hostlist_path is not None
            else hostlist_path.parent / ZAPRET_RUNTIME_EMPTY_HOSTLIST_PATH.name
        )
        self.base_hostlist_path = base_hostlist_path
        self.base_ipset_path = base_ipset_path
        self._rules: list[SiteRule] = []
        self._host_mappings: list[HostMapping] = []
        self._hosts_enabled = False
        self._ai_sites_enabled = False
        self._loaded_legacy_ai_rules = False
        self.load()
        if self._loaded_legacy_ai_rules:
            self.save()
        # A generated file can be lost independently (for example after manual
        # cleanup). Rebuild it when the application opens without touching the
        # packaged zapret lists.
        self.write_zapret_lists()

    # ------------------------------------------------------------- persistence

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            raw_rules = document.get("rules", [])
            raw_hosts = document.get("hosts", [])
        except (OSError, ValueError, AttributeError) as exc:
            log.warning("Site-list store unreadable (%s), ignoring it", exc)
            return

        rules: list[SiteRule] = []
        seen: set[tuple[SiteRuleType, str]] = set()
        for item in raw_rules if isinstance(raw_rules, list) else []:
            if not isinstance(item, dict):
                continue
            # Up to 1.1.5 AI mappings were also sent through winws. Current
            # Zapret-GUI uses only its hosts block, so migrate generated rows
            # out while keeping any same-named rule added by the user.
            if item.get("source") == "ai":
                self._loaded_legacy_ai_rules = True
                continue
            parsed = parse_rule(str(item.get("value", "")))
            if parsed is None or (parsed.type, parsed.value) in seen:
                continue
            seen.add((parsed.type, parsed.value))
            rules.append(SiteRule(parsed.type, parsed.value, bool(item.get("enabled", True))))
        self._rules = rules

        mappings: list[HostMapping] = []
        seen_hosts: set[str] = set()
        for item in raw_hosts if isinstance(raw_hosts, list) else []:
            if not isinstance(item, dict):
                continue
            mapping = validate_host_mapping(str(item.get("domain", "")), str(item.get("address", "")))
            if mapping is not None and mapping.domain not in seen_hosts:
                mappings.append(mapping)
                seen_hosts.add(mapping.domain)
        self._host_mappings = mappings
        self._hosts_enabled = bool(document.get("hosts_enabled", False))
        self._ai_sites_enabled = bool(document.get("ai_sites_enabled", False))

    def save(self) -> None:
        document = {
            "version": 1,
            "rules": [rule.as_dict() for rule in self._rules],
            "hosts": [mapping.as_dict() for mapping in self._host_mappings],
            "hosts_enabled": self._hosts_enabled,
            "ai_sites_enabled": self._ai_sites_enabled,
        }
        _atomic_write(self.path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")

    # ------------------------------------------------------------- records

    def rules(self) -> tuple[SiteRule, ...]:
        return tuple(self._rules)

    def add_values(self, values: Iterable[str]) -> ListUpdateResult:
        current = {(rule.type, rule.value) for rule in self._rules}
        added, duplicates, invalid = 0, 0, []
        for value in values:
            parsed = parse_rule(value)
            if parsed is None:
                invalid.append(value.strip())
                continue
            key = (parsed.type, parsed.value)
            if key in current:
                duplicates += 1
                continue
            self._rules.append(SiteRule(parsed.type, parsed.value, True))
            current.add(key)
            added += 1
        result = ListUpdateResult(added=added, duplicates=duplicates, invalid=tuple(invalid))
        if result.touched:
            self._persist_rules()
        return result

    def add_text(self, text: str) -> ListUpdateResult:
        return self.add_values(parse_import_lines(text))

    def remove_values(self, values: Iterable[str]) -> ListUpdateResult:
        wanted = set(values)
        old = len(self._rules)
        self._rules = [rule for rule in self._rules if rule.value not in wanted]
        result = ListUpdateResult(removed=old - len(self._rules))
        if result.touched:
            self._persist_rules()
        return result

    def set_enabled(self, values: Iterable[str], enabled: bool) -> ListUpdateResult:
        wanted = set(values)
        changed = 0
        updated = []
        for rule in self._rules:
            if rule.value in wanted and rule.enabled != enabled:
                rule = SiteRule(rule.type, rule.value, enabled)
                changed += 1
            updated.append(rule)
        self._rules = updated
        result = ListUpdateResult(changed=changed)
        if result.touched:
            self._persist_rules()
        return result

    def set_all_enabled(self, enabled: bool) -> ListUpdateResult:
        return self.set_enabled((rule.value for rule in self._rules), enabled)

    def set_ai_sites_enabled(self, enabled: bool) -> ListUpdateResult:
        """Persist the independent AI-hosts mode without changing zapret lists."""
        mode_changed = self._ai_sites_enabled != enabled
        self._ai_sites_enabled = enabled
        if mode_changed:
            self.save()
        return ListUpdateResult(changed=1 if mode_changed else 0)

    @property
    def ai_sites_enabled(self) -> bool:
        return self._ai_sites_enabled

    def _persist_rules(self) -> None:
        self.save()
        self.write_zapret_lists()

    # ------------------------------------------------------------- zapret

    def zapret_lists(self) -> tuple[list[str], list[str]]:
        # winws hostlists already match subdomains of a listed domain. Its file
        # grammar expects the bare domain, not a shell-style ``*.`` prefix.
        domains = sorted({
            rule.value.removeprefix("*.") for rule in self._rules
            if rule.enabled and rule.type is SiteRuleType.DOMAIN
        })
        addresses = sorted(
            rule.value for rule in self._rules
            if rule.enabled and rule.type in (SiteRuleType.IP, SiteRuleType.SUBNET)
        )
        return domains, addresses

    def write_zapret_lists(self) -> None:
        domains, addresses = self.zapret_lists()
        _atomic_write(self.hostlist_path, "\n".join(domains) + ("\n" if domains else ""))
        _atomic_write(self.ipset_path, "\n".join(addresses) + ("\n" if addresses else ""))
        _atomic_write(
            self.runtime_hostlist_path,
            self._merge_base(self.base_hostlist_path, domains),
        )
        _atomic_write(
            self.runtime_ipset_path,
            self._merge_base(self.base_ipset_path, addresses),
        )
        # Current general configs still mention list-general-user.txt. The
        # actual user rules are already merged above, like Zapret-GUI's runtime
        # rebuild, so this companion file is intentionally empty.
        _atomic_write(self.runtime_empty_hostlist_path, "")
        log.info(
            "Rebuilt zapret runtime lists: %s custom domains, %s custom IP entries",
            len(domains),
            len(addresses),
        )

    @staticmethod
    def _merge_base(base_path: Path, additions: Iterable[str]) -> str:
        try:
            base_lines = base_path.read_text(
                encoding="utf-8-sig", errors="replace",
            ).splitlines()
        except OSError:
            base_lines = []
        merged: list[str] = []
        seen: set[str] = set()
        for raw in (*base_lines, *additions):
            value = raw.strip()
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(value)
        return "\n".join(merged) + ("\n" if merged else "")

    # ------------------------------------------------------------- hosts

    @property
    def hosts_enabled(self) -> bool:
        return self._hosts_enabled

    def set_hosts_enabled(self, enabled: bool) -> None:
        self._hosts_enabled = enabled
        self.save()

    def host_mappings(self) -> tuple[HostMapping, ...]:
        return tuple(self._host_mappings)

    def add_host_mapping(self, domain: str, address: str) -> bool:
        mapping = validate_host_mapping(domain, address)
        if mapping is None or any(item.domain == mapping.domain for item in self._host_mappings):
            return False
        self._host_mappings.append(mapping)
        self.save()
        return True

    def remove_host_mapping(self, domain: str) -> bool:
        old = len(self._host_mappings)
        self._host_mappings = [item for item in self._host_mappings if item.domain != domain]
        if len(self._host_mappings) == old:
            return False
        self.save()
        return True


def validate_host_mapping(domain: str, address: str) -> HostMapping | None:
    """Validate a concrete hosts entry (wildcards and CIDRs are not hosts)."""
    normal = normalize_domain(domain)
    if normal is None or normal.startswith("*."):
        return None
    try:
        ip = str(ipaddress.ip_address(address.strip()))
    except ValueError:
        return None
    return HostMapping(normal, ip)
