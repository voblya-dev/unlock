"""The Logs page: a batched view onto the application log.

Kept apart from the window mainly because of its lifecycle — it subscribes to the
logger and owns a repeating timer, both of which have to be torn down again when
the page is discarded on a language change.  ``close_page()`` is that teardown,
and it is safe to call twice.
"""

from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from ... import logger
from ..canvas import TerminalPage
from ..i18n import tr

# A chatty engine can emit hundreds of lines a second. Appending each one
# repaints the view and stutters the UI, so lines are collected and flushed
# together on this interval.
_FLUSH_MS = 400
_MAX_BLOCKS = 2000


class LogsPage(TerminalPage):
    """Live log tail with a clear button, painted on the shared canvas."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pending: list[str] = []
        self._closed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(_MAX_BLOCKS)
        self._view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._view.setPlainText("\n".join(logger.tail()))
        layout.addWidget(self._view, 1)

        buttons = QHBoxLayout()
        clear = QPushButton(tr("Clear view"))
        clear.clicked.connect(self._view.clear)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        logger.subscribe(self._pending.append)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._flush)
        self._timer.start(_FLUSH_MS)

    # ------------------------------------------------------------------ text

    def history(self) -> str:
        """Everything currently on screen, so a rebuilt page can inherit it."""
        return self._view.toPlainText()

    def set_history(self, text: str) -> None:
        self._view.setPlainText(text)

    def _flush(self) -> None:
        if not self._pending:
            return
        chunk, self._pending[:] = "\n".join(self._pending), []
        self._view.appendPlainText(chunk)

    # ------------------------------------------------------------- lifecycle

    def close_page(self) -> None:
        """Stop the timer and unsubscribe. Idempotent: the window calls this both
        when rebuilding the tabs and when the application is quitting."""
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        logger.unsubscribe(self._pending.append)
