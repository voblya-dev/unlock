"""Compare the running version against the latest GitHub release tag.

Only the tag is fetched. Unlock never downloads or launches an executable on the
user's behalf — an updater that can replace its own signed binary is a far larger
attack surface than the convenience is worth — so the outcome of a check is a
version string and a link to the release page.

Kept free of Qt so the comparison can be tested without a network or an event
loop; :mod:`unlock.controllers.checks` wraps it in a QThread.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .constants import APP_VERSION, RELEASES_API_URL, RELEASES_PAGE_URL
from .logger import get_logger

log = get_logger("app_update")

_USER_AGENT = "Unlock-DPI-Bridge/2"
_TIMEOUT = 10.0
# Guards against a body that is not the JSON we expect: a captive portal or a
# proxy error page can be arbitrarily large, and it is all read into memory.
_MAX_BODY_BYTES = 256 * 1024
_NUMBER = re.compile(r"\d+")


@dataclass(frozen=True)
class UpdateInfo:
    latest: str
    current: str = APP_VERSION
    page_url: str = RELEASES_PAGE_URL

    @property
    def available(self) -> bool:
        return is_newer(self.latest, self.current)


def parse_version(text: str) -> tuple[int, ...]:
    """Numeric components of a tag, tolerant of the shapes GitHub tags take.

    ``v2.1.1``, ``2.1.1``, ``release-2.1.1`` and ``2.1.1-beta2`` all reduce to
    ``(2, 1, 1)``; a trailing pre-release counter is ignored on purpose so a
    beta tag never presents itself as newer than the release it precedes.
    """
    head = text.strip().split("-", 1)[0]
    return tuple(int(part) for part in _NUMBER.findall(head)[:4])


def is_newer(latest: str, current: str = APP_VERSION) -> bool:
    """True only when ``latest`` parses to a strictly higher version.

    An unparseable or empty tag is never treated as an update: prompting the
    user because a tag was renamed upstream would be worse than staying quiet.
    """
    left, right = parse_version(latest), parse_version(current)
    if not left or not right:
        return False
    width = max(len(left), len(right))
    left += (0,) * (width - len(left))
    right += (0,) * (width - len(right))
    return left > right


def latest_tag(url: str = RELEASES_API_URL, timeout: float = _TIMEOUT) -> str | None:
    """Tag name of the newest published release, or None if it cannot be read."""
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(_MAX_BODY_BYTES + 1)
        if len(payload) > _MAX_BODY_BYTES:
            log.warning("Release feed is implausibly large; ignoring it")
            return None
        release = json.loads(payload.decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, UnicodeDecodeError) as exc:
        log.info("Could not read the release feed: %s", exc)
        return None
    tag = release.get("tag_name") if isinstance(release, dict) else None
    return tag if isinstance(tag, str) and tag.strip() else None


def check(url: str = RELEASES_API_URL, timeout: float = _TIMEOUT) -> UpdateInfo | None:
    """Fetch and compare. None means "could not tell", not "up to date"."""
    tag = latest_tag(url, timeout)
    if tag is None:
        return None
    info = UpdateInfo(tag.strip())
    log.info(
        "Version check: running %s, latest %s%s",
        info.current, info.latest, " (update available)" if info.available else "",
    )
    return info
