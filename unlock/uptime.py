"""Accumulated protection time, and the human phrasing for it.

Two figures are kept, because they answer different questions and disagree:
``protection_seconds`` is time actually spent protected, summed across sessions,
while ``first_protected_utc`` anchors "you have been protected for N days" —
which is what the user reads as their streak. A machine that is off overnight
should not lose a day from that streak, so the headline counts elapsed days
rather than accumulated seconds.

No Qt and no i18n import here: the ui catalogue lives under ``unlock.ui`` and
importing it from the model layer would invert the dependency. The active
language code is passed in instead.
"""

from __future__ import annotations

from datetime import datetime, timezone

EN = "en"
RU = "ru"

_MINUTE = 60
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR


def _plural_ru(count: int, one: str, few: str, many: str) -> str:
    """Russian numeric agreement: 1 день, 2 дня, 5 дней, 21 день, 22 дня."""
    if count % 100 in range(11, 15):
        return many
    remainder = count % 10
    if remainder == 1:
        return one
    if remainder in (2, 3, 4):
        return few
    return many


def _plural_en(count: int, one: str) -> str:
    return one if count == 1 else f"{one}s"


def format_span(seconds: float, lang: str = EN) -> str:
    """Coarsest sensible unit with its noun: "47 дней", "3 hours", "12 minutes".

    Only one unit is shown. A streak is a number the user glances at, and
    "47 days 6 hours 12 minutes" reads as a stopwatch rather than a milestone.
    """
    total = max(0, int(seconds))
    if total >= _DAY:
        value, forms = total // _DAY, ("день", "дня", "дней", "day")
    elif total >= _HOUR:
        value, forms = total // _HOUR, ("час", "часа", "часов", "hour")
    elif total >= _MINUTE:
        value, forms = total // _MINUTE, ("минуту", "минуты", "минут", "minute")
    else:
        value, forms = total, ("секунду", "секунды", "секунд", "second")
    one, few, many, english = forms
    if lang == RU:
        return f"{value} {_plural_ru(value, one, few, many)}"
    return f"{value} {_plural_en(value, english)}"


def protected_phrase(seconds: float, lang: str = EN) -> str:
    """The full line shown on Home: «Вы защищены уже 47 дней»."""
    span = format_span(seconds, lang)
    if lang == RU:
        return f"Вы защищены уже {span}"
    return f"You have been protected for {span}"


def parse_stamp(value: object) -> datetime | None:
    """Read an ISO timestamp out of the config, tolerating anything else there.

    A naive stamp is read as UTC: that is what :func:`now_stamp` writes, and a
    config hand-edited without the offset should not poison the arithmetic.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=timezone.utc)
    return stamp


def now_stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def elapsed_since(value: object, *, now: datetime | None = None) -> float:
    """Seconds between a stored stamp and now; 0 for an absent or future one.

    A clock that has been moved backwards would otherwise produce a negative
    streak, which reads as a bug rather than as the clock change it is.
    """
    stamp = parse_stamp(value)
    if stamp is None:
        return 0.0
    reference = now or datetime.now(timezone.utc)
    return max(0.0, (reference - stamp).total_seconds())


class UptimeTracker:
    """Adds each protected interval to the running total on the way past.

    The total is written to the config when protection stops, not on a timer: a
    DPAPI encrypt plus an atomic replace every second, for a counter nobody reads
    between sessions, is not a trade worth making. A crash therefore loses the
    current session's contribution, and the streak in ``first_protected_utc``
    survives regardless.
    """

    def __init__(self, config) -> None:
        self._config = config
        self._started: datetime | None = None

    @property
    def running(self) -> bool:
        return self._started is not None

    def start(self) -> None:
        if self._started is not None:
            return
        self._started = datetime.now(timezone.utc)
        if not self._config.get("first_protected_utc"):
            self._config.set("first_protected_utc", now_stamp())

    def stop(self) -> None:
        if self._started is None:
            return
        span = max(0.0, (datetime.now(timezone.utc) - self._started).total_seconds())
        self._started = None
        self._config.set("protection_seconds", self.total_seconds_at_rest + int(span))

    @property
    def total_seconds_at_rest(self) -> int:
        try:
            return max(0, int(self._config.get("protection_seconds") or 0))
        except (TypeError, ValueError):
            return 0

    @property
    def total_seconds(self) -> int:
        """Stored total plus the interval in progress, if any."""
        total = self.total_seconds_at_rest
        if self._started is not None:
            total += int((datetime.now(timezone.utc) - self._started).total_seconds())
        return total

    @property
    def streak_seconds(self) -> float:
        """Time since protection was first ever enabled — the headline figure."""
        return elapsed_since(self._config.get("first_protected_utc"))

    def phrase(self, lang: str = EN) -> str:
        """The Home line, or an empty string before the very first connect."""
        streak = self.streak_seconds
        if streak <= 0 and not self.running:
            return ""
        return protected_phrase(max(streak, 1.0), lang)
