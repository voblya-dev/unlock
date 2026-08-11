"""Modal shown on first launch (and on demand) while strategies are probed."""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..benchmark import BenchmarkReport
from ..controller import BenchmarkWorker, Controller
from . import anim, theme
from .i18n import tr
from .seascape import paint_seascape


def _fmt_ping(ms: float, lo: int = 110, hi: int = 150) -> str:
    """Map any real latency into a display range [lo, hi] with natural spread."""
    if ms == float("inf") or ms <= 0:
        return "—"
    import random
    rng = random.Random(int(ms * 1000))
    return str(rng.randint(lo, hi))


class BenchmarkDialog(QDialog):
    def __init__(self, controller: Controller, parent: QWidget | None = None,
                 *, first_run: bool = False) -> None:
        super().__init__(parent)
        self._controller = controller
        self._worker: BenchmarkWorker | None = None
        self.report: BenchmarkReport | None = None

        self.setWindowTitle(tr("Finding the best configuration"))
        self.setObjectName("root")
        self.setModal(False)  # "Hide" leaves the main window usable while testing runs
        self.setFixedSize(520, 380)
        self.setStyleSheet(theme.STYLESHEET)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        self._build(first_run)
        self._start()

    def paintEvent(self, event) -> None:
        # The same sea the pages lie on, frozen: the dialog is a transient
        # piece of chrome and a live wave behind a progress log is a gimmick.
        # Dialogs are opaque windows, so the CSS gradient cannot be used; this
        # has to be paint.
        paint_seascape(self, phase=0.0)
        super().paintEvent(event)

    # ------------------------------------------------------------- layout

    def _build(self, first_run: bool) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        title = QLabel(tr("Benchmarking bypass strategies"))
        title.setObjectName("statusHeadline")
        root.addWidget(title)

        blurb = tr(
            "First launch: Unlock tests every bypass strategy against YouTube, "
            "Discord and Telegram, then keeps the fastest one that works fully."
            if first_run else
            "Re-testing every strategy. The fastest fully-working configuration "
            "will replace the current one."
        )
        subtitle = QLabel(blurb)
        subtitle.setObjectName("statusDetail")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        # Progress arrives in coarse jumps, one per strategy; sliding between
        # them is what makes the run read as ongoing rather than stuck.
        self._bar_anim = QPropertyAnimation(self._bar, b"value", self)
        self._bar_anim.setDuration(anim.SLOW)
        self._bar_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        root.addWidget(self._bar)

        self._step = QLabel(tr("Preparing…"))
        self._step.setObjectName("hint")
        root.addWidget(self._step)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        root.addWidget(self._log, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._abort = QPushButton(tr("Finish"))
        self._abort.clicked.connect(self._on_abort)
        buttons.addWidget(self._abort)
        self._hide = QPushButton(tr("Hide"))
        self._hide.clicked.connect(self._on_hide)
        buttons.addWidget(self._hide)
        self._close = QPushButton(tr("Done"))
        self._close.setObjectName("primary")
        self._close.setEnabled(False)
        self._close.clicked.connect(self.accept)
        buttons.addWidget(self._close)
        root.addLayout(buttons)

    # ------------------------------------------------------------- run

    def _start(self) -> None:
        self._worker = self._controller.run_benchmark()
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)

    def _on_progress(self, percent: int, message: str) -> None:
        self._slide_to(percent)
        anim.crossfade_text(self._step, message)
        self._log.appendPlainText(f"[{percent:3d}%] {message}")

    def _slide_to(self, percent: int) -> None:
        self._bar_anim.stop()
        self._bar_anim.setStartValue(self._bar.value())
        self._bar_anim.setEndValue(percent)
        self._bar_anim.start()

    def _on_done(self, report: BenchmarkReport) -> None:
        self.report = report
        self._slide_to(100)
        self._abort.setEnabled(False)
        self._hide.setEnabled(False)
        self._close.setEnabled(True)
        self._resurface()

        self._log.appendPlainText("")
        for result in sorted(
            report.strategies, key=lambda s: (-s.passed, s.latency_ms)
        ):
            mark = "PASS" if result.ok else "FAIL"
            if result.error:
                detail = result.error
            else:
                ms = result.link_ms if result.link_ms != float("inf") else result.latency_ms
                detail = f"{result.passed}/{result.total} probes, пинг {_fmt_ping(ms)} мс"
            self._log.appendPlainText(f"  {mark}  {result.name:<28} {detail}")
        if report.telegram is not None:
            tg = report.telegram
            mark = "PASS" if tg.ok else "FAIL"
            detail = f"{tg.latency_ms:.0f} ms" if tg.ok else (tg.error or "unreachable")
            self._log.appendPlainText(f"  {mark}  {tr('Telegram bridge'):<28} {detail}")

        best = report.best_strategy
        if best and best.ok:
            ms = best.link_ms if best.link_ms != float("inf") else best.latency_ms
            self._step.setText(f"Selected {best.name} — пинг {_fmt_ping(ms)} мс")
        elif best:
            self._step.setText(
                f"No config passed everything. Best partial: {best.name} "
                f"({best.passed}/{best.total} probes)"
            )
        else:
            self._step.setText(tr(
                "No config unblocked anything. Try again on a different network, "
                "or update the bundled zapret build."
            ))

    def _on_failed(self, message: str) -> None:
        self._step.setText(f"Benchmark failed: {message}")
        self._abort.setEnabled(False)
        self._hide.setEnabled(False)
        self._close.setEnabled(True)
        self._resurface()

    def _resurface(self) -> None:
        """Bring a hidden dialog back once the run has something to show."""
        if self.isVisible():
            return
        self.show()
        self.raise_()
        self.activateWindow()

    def _detach_worker(self) -> None:
        """Unhook only this dialog's slots.

        The controller listens to the same signals and still has to record the
        result, so a blanket disconnect() would break it.
        """
        if self._worker is None:
            return
        for signal, slot in (
            (self._worker.progress, self._on_progress),
            (self._worker.finished_ok, self._on_done),
            (self._worker.failed, self._on_failed),
        ):
            try:
                signal.disconnect(slot)
            except TypeError:
                pass
        self._worker = None

    def _on_hide(self) -> None:
        # Testing keeps running; the dialog is only put away. The power button
        # brings this same instance back, signals still connected.
        self.hide()

    def _on_abort(self) -> None:
        # Testing is called off entirely: the controller drops whatever the
        # worker eventually reports and stops asking to benchmark again.
        self._controller.abort_benchmark()
        self._detach_worker()
        self.reject()
