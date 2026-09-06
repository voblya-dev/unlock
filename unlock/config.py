"""JSON config persistence with schema-tolerant merge.

Reads never pass a fallback: :data:`~unlock.constants.DEFAULT_CONFIG` is the
single source of truth for what a key means when it is absent, so a default can
never disagree with itself between two call sites.
"""

from __future__ import annotations

import json
import base64
from copy import deepcopy
from typing import Any

from .constants import CONFIG_PATH, DEFAULT_CONFIG
from .logger import get_logger

from .secure_storage import SecureStorageError, protect, unprotect
log = get_logger("config")


class _Unset:
    """Sentinel: ``None`` is a legitimate value for several keys."""


_UNSET = _Unset()


class Config:
    def __init__(self) -> None:
        self._data: dict[str, Any] = deepcopy(DEFAULT_CONFIG)
        self.load()

    def load(self) -> None:
        if not CONFIG_PATH.exists():
            log.info("No config found, using defaults")
            return
        legacy = False
        try:
            document = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(document, dict) and "dpapi" in document:
                encrypted = base64.b64decode(document["dpapi"], validate=True)
                raw = json.loads(unprotect(encrypted).decode("utf-8"))
            else:
                # Existing plaintext configurations are upgraded on next save.
                raw = document
                legacy = True
                log.warning("Legacy plaintext config loaded; it will be encrypted on next save")
            if not isinstance(raw, dict):
                raise ValueError("configuration root is not an object")
        except (OSError, ValueError, KeyError, TypeError, SecureStorageError) as exc:
            log.warning("Config unreadable (%s), falling back to defaults", exc)
            return
        # Merge so keys added by a newer app version keep their defaults.
        merged = deepcopy(DEFAULT_CONFIG)
        merged.update({k: v for k, v in raw.items() if k in merged})
        self._data = merged
        log.info("Config loaded from %s", CONFIG_PATH)
        if legacy:
            self.save()

    def save(self) -> None:
        tmp = CONFIG_PATH.with_suffix(".tmp")
        try:
            plaintext = json.dumps(self._data, separators=(",", ":")).encode("utf-8")
            document = {"version": 1, "dpapi": base64.b64encode(protect(plaintext)).decode("ascii")}
        except (TypeError, SecureStorageError) as exc:
            raise RuntimeError(f"Could not protect configuration: {exc}") from exc
        tmp.write_text(json.dumps(document, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)  # atomic: never leave a half-written config
        log.info("Config saved")

    def get(self, key: str, default: Any = _UNSET) -> Any:
        """Value for ``key``, falling back to the shipped default.

        Callers should not pass ``default``; it exists only for keys that are
        deliberately absent from ``DEFAULT_CONFIG``.
        """
        if key in self._data:
            return self._data[key]
        if not isinstance(default, _Unset):
            return default
        return deepcopy(DEFAULT_CONFIG.get(key))

    def flag(self, key: str) -> bool:
        """Boolean read that tolerates a config hand-edited to 0/1/"true"."""
        value = self.get(key)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    def number(self, key: str) -> int:
        """Integer read that survives a malformed value instead of raising."""
        try:
            return int(self.get(key) or 0)
        except (TypeError, ValueError):
            fallback = DEFAULT_CONFIG.get(key)
            return int(fallback) if isinstance(fallback, (int, float)) else 0

    def text(self, key: str) -> str:
        value = self.get(key)
        return value if isinstance(value, str) else ""

    def set(self, key: str, value: Any, *, save: bool = True) -> None:
        self._data[key] = value
        if save:
            self.save()

    def update(self, values: dict[str, Any], *, save: bool = True) -> None:
        self._data.update(values)
        if save:
            self.save()

    @property
    def data(self) -> dict[str, Any]:
        return self._data
