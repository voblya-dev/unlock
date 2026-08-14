"""Per-user site rules and the zapret lists generated from them.

The zapret pack is shipped as an application resource and is deliberately
treated as immutable.  This module owns the small, versioned document under
``%APPDATA%\\Unlock`` and derives two plain-text files which winws can consume.
Keeping the editable records separate from the generated files makes updates
safe and gives the UI enough metadata to distinguish user rules from the
built-in AI-sites collection.
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

from .constants import (
    SITE_LISTS_PATH,
    ZAPRET_USER_HOSTLIST_PATH,
    ZAPRET_USER_IPSET_PATH,
)
from .logger import get_logger

log = get_logger("site_lists")


class SiteRuleType(str, Enum):
    DOMAIN = "domain"
    IP = "ip"
    SUBNET = "subnet"


class SiteRuleSource(str, Enum):
    USER = "user"
    AI = "ai"


_DOMAIN_RE = re.compile(
    r"^(?:\*\.)?(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)

# Kept local and versionable: a future signed HTTPS feed can replace this
# tuple without changing the UI or list persistence format.
AI_SITES: tuple[str, ...] = (
    "chatgpt.com",
    "openai.com",
    "auth.openai.com",
    "claude.ai",
    "anthropic.com",
    "gemini.google.com",
    "aistudio.google.com",
    "copilot.microsoft.com",
    "perplexity.ai",
)


@dataclass(frozen=True)
class SiteRule:
    type: SiteRuleType
    value: str
    source: SiteRuleSource = SiteRuleSource.USER
    enabled: bool = True

    def as_dict(self) -> dict:
        return {
            "type": self.type.value,
            "value": self.value,
            "source": self.source.value,
            "enabled": self.enabled,
        }


@dataclass(frozen=True)
class HostMapping:
    domain: str
    address: str

    def as_dict(self) -> dict:
        return {"domain": self.domain, "address": self.address}


@dataclass(frozen=True)
class MutationResult:
    """What a mutation did, suitable for concise UI feedback."""

    added: int = 0
    removed: int = 0
    changed: int = 0
    duplicates: int = 0
    invalid: tuple[str, ...] = ()

    @property
    def touched(self) -> bool:
        return bool(self.added or self.removed or self.changed)


def normalize_domain(value: str) -> str | None:
    """Return a canonical ASCII host mask, or ``None`` when it is invalid."""
    value = value.strip().lower().rstrip(".")
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
    if "/" in value:
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
    ) -> None:
        self.path = path
        self.hostlist_path = hostlist_path
        self.ipset_path = ipset_path
        self._rules: list[SiteRule] = []
        self._host_mappings: list[HostMapping] = []
        self._hosts_enabled = False
        self._ai_sites_enabled = False
        self.load()
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
            parsed = parse_rule(str(item.get("value", "")))
            try:
                source = SiteRuleSource(item.get("source", SiteRuleSource.USER.value))
            except ValueError:
                source = SiteRuleSource.USER
            if parsed is None or (parsed.type, parsed.value) in seen:
                continue
            seen.add((parsed.type, parsed.value))
            rules.append(SiteRule(parsed.type, parsed.value, source, bool(item.get("enabled", True))))
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

    def add_values(
        self, values: Iterable[str], *, source: SiteRuleSource = SiteRuleSource.USER
    ) -> MutationResult:
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
            self._rules.append(SiteRule(parsed.type, parsed.value, source, True))
            current.add(key)
            added += 1
        result = MutationResult(added=added, duplicates=duplicates, invalid=tuple(invalid))
        if result.touched:
            self._persist_rules()
        return result

    def add_text(self, text: str) -> MutationResult:
        return self.add_values(parse_import_lines(text))

    def remove_values(self, values: Iterable[str], *, ai_only: bool = False) -> MutationResult:
        wanted = set(values)
        old = len(self._rules)
        self._rules = [
            rule for rule in self._rules
            if rule.value not in wanted or (ai_only and rule.source is not SiteRuleSource.AI)
        ]
        result = MutationResult(removed=old - len(self._rules))
        if result.touched:
            self._persist_rules()
        return result

    def remove_ai_sites(self) -> MutationResult:
        old = len(self._rules)
        self._rules = [rule for rule in self._rules if rule.source is not SiteRuleSource.AI]
        result = MutationResult(removed=old - len(self._rules))
        if result.touched:
            self._persist_rules()
        return result

    def set_enabled(self, values: Iterable[str], enabled: bool) -> MutationResult:
        wanted = set(values)
        changed = 0
        updated = []
        for rule in self._rules:
            if rule.value in wanted and rule.enabled != enabled:
                rule = SiteRule(rule.type, rule.value, rule.source, enabled)
                changed += 1
            updated.append(rule)
        self._rules = updated
        result = MutationResult(changed=changed)
        if result.touched:
            self._persist_rules()
        return result

    def set_all_enabled(self, enabled: bool) -> MutationResult:
        return self.set_enabled((rule.value for rule in self._rules), enabled)

    def set_ai_sites_enabled(self, enabled: bool) -> MutationResult:
        """Enable the built-in AI collection or remove only its own records."""
        mode_changed = self._ai_sites_enabled != enabled
        self._ai_sites_enabled = enabled
        if not enabled:
            result = self.remove_ai_sites()
        else:
            result = self.add_values(AI_SITES, source=SiteRuleSource.AI)
        if mode_changed and not result.touched:
            self.save()
            result = MutationResult(changed=1)
        return result

    def refresh_ai_sites(self, values: Iterable[str] = AI_SITES) -> MutationResult:
        """Refresh the source-owned collection; extension point for signed feeds."""
        if not self._ai_sites_enabled:
            return MutationResult()
        canonical = []
        for value in values:
            parsed = parse_rule(value)
            if parsed is not None and parsed.type is SiteRuleType.DOMAIN:
                canonical.append(parsed.value)
        available = set(canonical)
        old_ai = {rule.value for rule in self._rules if rule.source is SiteRuleSource.AI}
        removed = self.remove_values(old_ai - available, ai_only=True).removed
        result = self.add_values(canonical, source=SiteRuleSource.AI)
        return MutationResult(
            added=result.added,
            removed=removed,
            duplicates=result.duplicates,
            invalid=result.invalid,
        )

    @property
    def ai_sites_enabled(self) -> bool:
        return self._ai_sites_enabled

    def _persist_rules(self) -> None:
        self.save()
        self.write_zapret_lists()

    # ------------------------------------------------------------- zapret

    def zapret_lists(self) -> tuple[list[str], list[str]]:
        domains = sorted(
            rule.value for rule in self._rules
            if rule.enabled and rule.type is SiteRuleType.DOMAIN
        )
        addresses = sorted(
            rule.value for rule in self._rules
            if rule.enabled and rule.type in (SiteRuleType.IP, SiteRuleType.SUBNET)
        )
        return domains, addresses

    def write_zapret_lists(self) -> None:
        domains, addresses = self.zapret_lists()
        _atomic_write(self.hostlist_path, "\n".join(domains) + ("\n" if domains else ""))
        _atomic_write(self.ipset_path, "\n".join(addresses) + ("\n" if addresses else ""))

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
