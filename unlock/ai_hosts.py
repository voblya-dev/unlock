"""The complete hosts bundle used by Zapret-GUI 2.1.1 AI mode.

The upstream feature does not use a small hand-maintained AI allowlist.  It
downloads the full dns.malw.link hosts file, appends the Goida-AI-Unlocker
supplement, removes entries that could prevent future GitHub updates, and
caches the validated result.  Unlock deliberately mirrors that behaviour so
the one-click mode has the same coverage as the known-working implementation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import requests

from .constants import AI_HOSTS_CACHE_PATH
from .site_lists import normalize_domain


AI_HOSTS_URL = "https://raw.githubusercontent.com/ImMALWARE/dns.malw.link/master/hosts"
AI_HOSTS_ADDITIONAL_URL = (
    "https://raw.githubusercontent.com/AvenCores/Goida-AI-Unlocker/main/additional_hosts.py"
)
AI_PROTECTED_HOSTS = frozenset({
    "api.github.com",
    "github.com",
    "www.github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "codeload.github.com",
})
# Earlier Unlock versions cached only a few dozen AI rows.  Zapret-GUI's
# mechanism is the complete dns.malw.link bundle, which is thousands of rows;
# this threshold makes an enabled mode migrate instead of silently reusing the
# incompatible old cache after an application update.
MIN_COMPLETE_BUNDLE_ROWS = 1000

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

_ADDITIONAL_VERSION_RE = re.compile(r'version_add\s*=\s*["\']([^"\']+)["\']')
_ADDITIONAL_HOSTS_RE = re.compile(
    r"hosts_add\s*=\s*(?:r|R)?(?P<quote>\"\"\"|''')(?P<body>.*?)(?P=quote)", re.S,
)


class AiHostsError(RuntimeError):
    """No usable AI hosts source or cache was available."""


@dataclass(frozen=True)
class AiHostsBundle:
    hosts_text: str
    ai_domains: tuple[str, ...]
    source: str  # network or cache
    additional_version: str = ""


def is_ai_domain(domain: str) -> bool:
    domain = domain.lower().rstrip(".")
    return domain in AI_EXACT_DOMAINS or any(
        domain == suffix or domain.endswith(f".{suffix}")
        for suffix in AI_DOMAIN_SUFFIXES
    )


def _line_hostnames(line: str) -> tuple[str, ...]:
    fields = line.split("#", 1)[0].split()
    if len(fields) < 2:
        return ()
    domains = []
    for candidate in fields[1:]:
        domain = normalize_domain(candidate)
        if domain and not domain.startswith("*."):
            domains.append(domain)
    return tuple(domains)


def _filter_hosts_bundle(text: str) -> str:
    """Keep the upstream bundle intact except update-critical GitHub rows."""
    kept = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        if any(host in AI_PROTECTED_HOSTS for host in _line_hostnames(line)):
            continue
        kept.append(line.rstrip())
    result = "\n".join(kept).strip()
    return result + ("\n" if result else "")


def _bundle_looks_useful(text: str) -> bool:
    rows = [
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    haystack = text.casefold()
    return len(rows) >= 3 and any(
        token in haystack for token in ("openai", "chatgpt", "claude", "gemini", "anthropic")
    )


def _ai_domains_from_bundle(text: str) -> tuple[str, ...]:
    domains: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        for domain in _line_hostnames(line):
            if is_ai_domain(domain) and domain not in seen:
                seen.add(domain)
                domains.append(domain)
    return tuple(domains)


def load_cached_ai_hosts(path: Path = AI_HOSTS_CACHE_PATH) -> str:
    try:
        text = _filter_hosts_bundle(path.read_text(encoding="utf-8"))
    except OSError:
        return ""
    return text if _bundle_looks_useful(text) else ""


def cached_complete_ai_bundle(path: Path = AI_HOSTS_CACHE_PATH) -> AiHostsBundle | None:
    """Return a modern full cache, never the short pre-1.1.4 mapping cache."""
    text = load_cached_ai_hosts(path)
    rows = sum(
        1 for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    if rows < MIN_COMPLETE_BUNDLE_ROWS:
        return None
    return AiHostsBundle(text, _ai_domains_from_bundle(text), "cache", "cached")


def _download_text(url: str, timeout: float) -> str:
    response = requests.get(
        url, headers={"User-Agent": "ZapretGUI-AiDNS"}, timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def _write_cache(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def refresh_ai_mappings(
    *, cache_path: Path = AI_HOSTS_CACHE_PATH, timeout: float = 25.0,
) -> AiHostsBundle:
    """Download and cache the same complete bundle as Zapret-GUI 2.1.1."""
    try:
        main_hosts = _download_text(AI_HOSTS_URL, timeout).strip()
        additional_hosts = ""
        additional_version = ""
        try:
            additional = _download_text(AI_HOSTS_ADDITIONAL_URL, min(timeout, 20.0))
            version_match = _ADDITIONAL_VERSION_RE.search(additional)
            hosts_match = _ADDITIONAL_HOSTS_RE.search(additional)
            if version_match:
                additional_version = version_match.group(1).strip()
            if hosts_match:
                additional_hosts = hosts_match.group("body").strip()
        except requests.RequestException:
            pass

        pieces = [main_hosts]
        if additional_hosts:
            header = "# Goida-AI-Unlocker additional hosts"
            if additional_version:
                header += f" ({additional_version})"
            pieces.extend((header, additional_hosts))
        hosts_text = _filter_hosts_bundle("\n\n".join(p for p in pieces if p))
        if not _bundle_looks_useful(hosts_text):
            raise AiHostsError("downloaded hosts bundle failed validation")
        _write_cache(cache_path, hosts_text)
        return AiHostsBundle(
            hosts_text, _ai_domains_from_bundle(hosts_text), "network", additional_version,
        )
    except (OSError, requests.RequestException, AiHostsError) as exc:
        cached = load_cached_ai_hosts(cache_path)
        if cached:
            return AiHostsBundle(cached, _ai_domains_from_bundle(cached), "cache", "cached")
        raise AiHostsError(f"Could not obtain AI hosts bundle: {exc}") from exc
