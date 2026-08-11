"""Modal shown while the genetic search hunts for a link-specific strategy."""

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

from ..controller import Controller, EvolutionWorker
from ..evolution import EvolutionReport
from . import anim, theme
from .benchmark_dialog import _fmt_ping
from .i18n import tr
from .seascape import paint_seascape


class EvolutionDialog(QDialog):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._worker: EvolutionWorker | None = None
        self.report: EvolutionReport | None = None

        self.setWindowTitle(tr("Evolving a strategy"))
        self.setObjectName("root")
        self.setModal(False)  # "Hide" leaves the main window usable while it runs
        self.setFixedSize(560, 420)
        self.setStyleSheet(theme.STYLESHEET)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)

        self._build()
        self._start()

    def paintEvent(self, event) -> None:
        # Same fixed sea paint as BenchmarkDialog: chrome, not a living page.
        paint_seascape(self, phase=0.0)
        super().paintEvent(event)

    # ------------------------------------------------------------- layout

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        title = QLabel(tr("Evolving a strategy for your provider"))
        title.setObjectName("statusHeadline")
        root.addWidget(title)

        subtitle = QLabel(tr(
            "Instead of picking the best of the bundled configs, Unlock breeds new "
            "ones: it starts from those configs, keeps whatever works best against "
            "your connection and recombines them. This takes a while — the app "
            "cannot protect you until it finishes."
        ))
        subtitle.setObjectName("statusDetail")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
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
        self._stop = QPushButton(tr("Stop and keep best"))
        self._stop.setToolTip(tr(
            "Ends the search after the running test. Whatever it has already "
            "found is kept — it is never worse than the bundled configs."
        ))
        self._stop.clicked.connect(self._on_stop)
        buttons.addWidget(self._stop)
        self._hide = QPushButton(tr("Hide"))
        self._hide.clicked.connect(self.hide)
        buttons.addWidget(self._hide)
        self._close = QPushButton(tr("Done"))
        self._close.setObjectName("primary")
        self._close.setEnabled(False)
        self._close.clicked.connect(self.accept)
        buttons.addWidget(self._close)
        root.addLayout(buttons)

    # ------------------------------------------------------------- run

    def _start(self) -> None:
        self._worker = self._controller.run_evolution()
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)

    def _on_progress(self, percent: int, message: str) -> None:
        self._slide_to(percent)
        human = self._humanise(percent, message)
        anim.crossfade_text(self._step, human)
        self._log.appendPlainText(human)

    @staticmethod
    def _humanise(percent: int, raw: str) -> str:
        r = raw.lower()
        if "gen 0" in r and "testing" in r:
            try:
                idx = raw.split(":")[1].strip().split()[1].split("/")[0]
                tot = raw.split(":")[1].strip().split()[1].split("/")[1]
                return f"Сканирование встроенных конфигураций… ({idx} из {tot})"
            except (IndexError, ValueError):
                return "Сканирование встроенных конфигураций…"
        if "gen 0" in r and "best" in r:
            return "Лучшая встроенная конфигурация найдена — начинаю улучшать"
        if "gen " in r and "testing" in r:
            try:
                num = raw.split()[1].rstrip(":")
                return f"Поколение {num}: проверяю новую комбинацию…"
            except IndexError:
                return "Проверяю новую комбинацию…"
        if "gen " in r and "best" in r:
            if "probes" in r:
                try:
                    score = raw.split("probes")[0].strip().split()[-1]
                    return f"Поколение завершено — лучший результат: {score} проб ✓"
                except IndexError:
                    pass
            return "Поколение завершено, результаты обновлены"
        if "confirming" in r:
            return "Финальная проверка победителя на всех сервисах…"
        if "complete" in r:
            return "Готово!"
        if "finishing" in r:
            return "Завершаю текущий тест…"
        return raw

    def _slide_to(self, percent: int) -> None:
        self._bar_anim.stop()
        self._bar_anim.setStartValue(self._bar.value())
        self._bar_anim.setEndValue(percent)
        self._bar_anim.start()

    def _on_done(self, report: EvolutionReport) -> None:
        self.report = report
        self._slide_to(100)
        self._stop.setEnabled(False)
        self._hide.setEnabled(False)
        self._close.setEnabled(True)
        self._resurface()

        best = report.best
        if best is None or not report.saved_name:
            self._step.setText(tr(
                "Nothing worked on this connection. Try again on a different "
                "network, or update the bundled zapret build."
            ))
            self._log.appendPlainText("")
            self._log.appendPlainText("К сожалению, ни одна конфигурация не сработала.")
            self._log.appendPlainText("Попробуйте другую сеть или обновите zapret.")
            return

        # Human-readable summary
        self._log.appendPlainText("")
        self._log.appendPlainText("─" * 46)

        tested = report.evaluated
        gens = report.generations
        self._log.appendPlainText(
            f"  Проверено конфигураций: {tested}  |  поколений: {gens}"
        )

        passed_pct = int(best.passed / best.total * 100) if best.total else 0
        ms = best.link_ms if best.link_ms != float("inf") else best.latency_ms
        ping_str = f"{_fmt_ping(ms, 80, 100)} мс"
        self._log.appendPlainText(
            f"  Результат победителя: {best.passed}/{best.total} сервисов "
            f"({passed_pct}%)  ·  пинг {ping_str}"
        )

        if report.baseline is not None and report.baseline.total:
            base_pct = int(report.baseline.passed / report.baseline.total * 100)
            if report.improved:
                diff = passed_pct - base_pct
                self._log.appendPlainText(
                    f"  Лучше любого встроенного пресета на {diff}%  🎯"
                )
            else:
                self._log.appendPlainText(
                    "  Результат на уровне лучшего встроенного пресета"
                )

        self._log.appendPlainText(f"  Сохранено как: {report.saved_name}")
        self._log.appendPlainText("─" * 46)

        if report.improved:
            self._step.setText(
                f"Найдена стратегия специально под ваш провайдер — "
                f"{best.passed}/{best.total} сервисов, пинг {ping_str}. Уже установлена."
            )
        else:
            self._step.setText(
                f"Лучший доступный вариант: {best.passed}/{best.total} сервисов, "
                f"пинг {ping_str}. Установлен."
            )

    def _on_failed(self, message: str) -> None:
        self._step.setText(f"Search failed: {message}")
        self._stop.setEnabled(False)
        self._hide.setEnabled(False)
        self._close.setEnabled(True)
        self._resurface()

    def _resurface(self) -> None:
        if self.isVisible():
            return
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_stop(self) -> None:
        # The worker cannot be interrupted mid-probe, so the search is asked to
        # stop and still reports through _on_done with whatever it confirmed.
        self._stop.setEnabled(False)
        self._step.setText(tr("Finishing the current test…"))
        self._controller.abort_evolution()
