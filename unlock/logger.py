"""Rotating file + in-memory logger shared by every module."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from collections import deque
from typing import Callable

from .constants import LOG_PATH

_LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)-14s %(message)s"

# Tail buffer feeds the Logs view without re-reading the file on every repaint.
_TAIL: deque[str] = deque(maxlen=2000)
_SUBSCRIBERS: list[Callable[[str], None]] = []


class _TailHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        line = self.format(record)
        _TAIL.append(line)
        for cb in list(_SUBSCRIBERS):
            try:
                cb(line)
            except Exception:  # a broken view must never kill logging
                pass


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(level)

    fmt = logging.Formatter(_LOG_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    tail_handler = _TailHandler()
    tail_handler.setFormatter(fmt)
    root.addHandler(tail_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def tail(limit: int = 500) -> list[str]:
    return list(_TAIL)[-limit:]


def subscribe(callback: Callable[[str], None]) -> None:
    _SUBSCRIBERS.append(callback)


def unsubscribe(callback: Callable[[str], None]) -> None:
    if callback in _SUBSCRIBERS:
        _SUBSCRIBERS.remove(callback)
