"""Validated AI-service host mappings used by the one-click AI mode.

Zapret-GUI keeps the current mappings in a remote ``hosts`` file. That file
also contains unrelated websites and ad-block entries, so Unlock downloads only
the AI-related entries and accepts them only for an explicit set of AI service
domains. The filtered result is cached locally for a temporary source outage.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from .constants import AI_HOSTS_CACHE_PATH
from .site_lists import HostMapping, normalize_domain


AI_HOSTS_URL = "https://raw.githubusercontent.com/ImMALWARE/dns.malw.link/master/hosts"
AI_HOSTS_ADDITIONAL_URL = (
    "https://raw.githubusercontent.com/AvenCores/Goida-AI-Unlocker/main/additional_hosts.py"
)

# Services whose complete domain trees are AI-specific. Broad domains such as
# google.com and microsoft.com are handled below with exact hosts so an AI
# button cannot accidentally redirect normal Google or Microsoft services.
AI_DOMAIN_SUFFIXES: tuple[str, ...] = (
    "openai.com", "chatgpt.com", "oaistatic.com", "oaiusercontent.com",
    "anthropic.com", "claude.ai", "perplexity.ai", "grok.com", "x.ai",
    "mistral.ai", "cohere.com", "deepseek.com", "huggingface.co", "poe.com",
    "you.com", "pi.ai", "character.ai", "meta.ai", "elevenlabs.io",
    "stability.ai", "midjourney.com", "runwayml.com", "leonardo.ai",
    "ideogram.ai", "luma.ai", "fal.ai", "replicate.com", "groq.com",
    "together.ai", "cerebras.ai", "qwen.ai", "kimi.com", "z.ai", "manus.im",
    "lovable.dev", "v0.dev", "bolt.new", "cursor.com", "codeium.com",
    "windsurf.com", "trae.ai", "githubcopilot.com",
)

AI_EXACT_DOMAINS: frozenset[str] = frozenset({
    "gemini.google.com", "aistudio.google.com", "notebooklm.google.com",
    "jules.google.com", "generativelanguage.googleapis.com",
    "aisandbox-pa.googleapis.com", "webchannel-alkalimakersuite-pa.clients6.google.com",
    "alkalimakersuite-pa.clients6.google.com", "assistant-s3-pa.googleapis.com",
    "proactivebackend-pa.googleapis.com", "robinfrontend-pa.googleapis.com",
    "aitestkitchen.withgoogle.com", "copilot.microsoft.com", "sydney.bing.com",
    "edgeservices.bing.com",
})

_ADDITIONAL_HOSTS_RE = re.compile(
    r"hosts_add\s*=\s*(?:r|R)?(?P<quote>\"\"\"|''')(?P<body>.*?)(?P=quote)", re.S,
)


class AiHostsError(RuntimeError):
    """No usable AI mapping source or cache was available."""


@dataclass(frozen=True)
class AiHostsBundle:
    mappings: tuple[HostMapping, ...]
    source: str  # network or cache


def is_ai_domain(domain: str) -> bool:
    """Whether a normalized hostname is intentionally covered by AI mode."""
    domain = domain.lower().rstrip(".")
    return domain in AI_EXACT_DOMAINS or any(
        domain == suffix or domain.endswith(f".{suffix}")
        for suffix in AI_DOMAIN_SUFFIXES
    )


def _parse_mapping_lines(text: str) -> tuple[HostMapping, ...]:
    """Read valid public ``IP hostname`` rows, retaining AI hosts only."""
    mappings: list[HostMapping] = []
    seen: set[str] = set()
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        fields = raw_line.split("#", 1)[0].split()
        if len(fields) < 2:
            continue
        try:
            address = ipaddress.ip_address(fields[0])
        except ValueError:
            continue
        # Never accept local, unspecified, multicast or documentation ranges
        # from a remote feed.
        if not address.is_global:
            continue
        for candidate in fields[1:]:
            domain = normalize_domain(candidate)
            if domain is None or domain.startswith("*.") or not is_ai_domain(domain):
                continue
            if domain not in seen:
                mappings.append(HostMapping(domain, str(address)))
                seen.add(domain)
    return tuple(mappings)


def _render_cache(mappings: tuple[HostMapping, ...]) -> str:
    return "\n".join(f"{item.address}\t{item.domain}" for item in mappings) + (
        "\n" if mappings else ""
    )


def load_cached_ai_mappings(path: Path = AI_HOSTS_CACHE_PATH) -> tuple[HostMapping, ...]:
    try:
        return _parse_mapping_lines(path.read_text(encoding="utf-8"))
    except OSError:
        return ()


def _download_text(url: str, timeout: float) -> str:
    response = requests.get(
        url, headers={"User-Agent": "Unlock-AI-Hosts/1.0"}, timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def refresh_ai_mappings(
    *, cache_path: Path = AI_HOSTS_CACHE_PATH, timeout: float = 20.0,
) -> AiHostsBundle:
    """Fetch, validate and cache the AI-only subset of Zapret-GUI's feed."""
    try:
        text = _download_text(AI_HOSTS_URL, timeout)
        try:
            additional = _download_text(AI_HOSTS_ADDITIONAL_URL, timeout)
            match = _ADDITIONAL_HOSTS_RE.search(additional)
            if match:
                text += "\n" + match.group("body")
        except requests.RequestException:
            pass
        mappings = _parse_mapping_lines(text)
        if len(mappings) < 3:
            raise AiHostsError("AI host feed contained too few valid mappings")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
        temporary.write_text(_render_cache(mappings), encoding="utf-8", newline="\n")
        temporary.replace(cache_path)
        return AiHostsBundle(mappings, "network")
    except (OSError, requests.RequestException, AiHostsError) as exc:
        cached = load_cached_ai_mappings(cache_path)
        if cached:
            return AiHostsBundle(cached, "cache")
        raise AiHostsError(f"Could not obtain AI host mappings: {exc}") from exc
