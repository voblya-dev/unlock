"""The "Add servers" dialog behind the VPN tab's single Add button.

Everything that used to sit on the tab lives here: a multi-line box that takes
any number of links at once, a drop zone for config files and QR screenshots,
and the file picker. All of it funnels into :mod:`unlock.vpn_import`, so a mixed
batch — three pasted links plus two dropped .conf files — is one import run.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from .. import vpn_import
from ..vpn_links import Profile, VpnLinkError
from . import theme
from .i18n import tr
from .seascape import paint_seascape

_ACCEPTED = vpn_import.IMAGE_SUFFIXES + vpn_import.CONFIG_SUFFIXES


class ImportWorker(QThread):
    """Runs a whole batch off the UI thread.

    Subscription fetches and QR decodes both block, and a batch can hold several
    of each, so partial failure is normal: the worker reports what it managed to
    parse alongside the per-source errors.
    """

    done = pyqtSignal(object, object)      # list[Profile], list[str] errors

    def __init__(self, texts: list[str], files: list[str]) -> None:
        super().__init__()
        self._texts = texts
        self._files = files

    def run(self) -> None:
        profiles: list[Profile] = []
        errors: list[str] = []

        for source, is_file in [(t, False) for t in self._texts] + [
            (f, True) for f in self._files
        ]:
            try:
                profiles.extend(
                    vpn_import.from_file(source) if is_file
                    else vpn_import.from_text(source)
                )
            except VpnLinkError as exc:
                errors.append(f"{Path(source).name if is_file else source[:40]}: {exc}")
            except Exception as exc:               # noqa: BLE001 - surface anything
                errors.append(f"{Path(source).name if is_file else source[:40]}: {exc}")

        self.done.emit(profiles, errors)


class DropZone(QFrame):
    """Drop target for config files and QR images; also clickable."""

    dropped = pyqtSignal(object)           # list[str] paths
    clicked = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(88)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(2)

        title = QLabel(tr("Drop config files or QR images here"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)

        hint = QLabel(tr("…or click to browse. Several files at once are fine."))
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

    @staticmethod
    def _paths(event) -> list[str]:
        return [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in _ACCEPTED
        ]

    def _set_active(self, active: bool) -> None:
        self.setObjectName("dropZoneActive" if active else "dropZone")
        # Qt matches the object name at style time, so the widget has to be
        # re-polished before the new rule is picked up.
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and self._paths(event):
            event.acceptProposedAction()
            self._set_active(True)
        elif event.mimeData().hasText():
            event.acceptProposedAction()
            self._set_active(True)

    def dragLeaveEvent(self, event) -> None:
        self._set_active(False)

    def dropEvent(self, event) -> None:
        self._set_active(False)
        paths = self._paths(event) if event.mimeData().hasUrls() else []
        if paths:
            self.dropped.emit(paths)
            event.acceptProposedAction()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class AddServersDialog(QDialog):
    """Collects links and files, imports the batch, returns the new profiles."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker: ImportWorker | None = None
        self._files: list[str] = []
        self.profiles: list[Profile] = []

        self.setWindowTitle(tr("Add servers"))
        self.setModal(True)
        self.setMinimumSize(520, 520)
        # The palette only paints #root; without the name the dialog falls back
        # to the platform's white window background.
        self.setObjectName("root")
        self.setStyleSheet(theme.STYLESHEET)
        self.setAcceptDrops(True)

        self._build()

    def paintEvent(self, event) -> None:
        # Same sea paint as the pages; fixed phase, no per-frame drift for a
        # dialog that lives for seconds.
        paint_seascape(self, phase=0.0)
        super().paintEvent(event)

    # ------------------------------------------------------------- layout

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel(tr("Add servers"))
        title.setObjectName("statusHeadline")
        root.addWidget(title)

        blurb = QLabel(tr(
            "Paste one link per line — vless, vmess, trojan, ss, hysteria2, "
            "an Amnezia vpn:// link, or a subscription URL. Everything you paste "
            "and drop is imported together."
        ))
        blurb.setObjectName("hint")
        blurb.setWordWrap(True)
        root.addWidget(blurb)

        self._input = QPlainTextEdit()
        self._input.setPlaceholderText(
            "vless://…\nvmess://…\nhttps://example.com/subscription"
        )
        self._input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._input, 1)

        self._zone = DropZone()
        self._zone.dropped.connect(self._add_files)
        self._zone.clicked.connect(self._browse)
        root.addWidget(self._zone)

        self._files_label = QLabel("")
        self._files_label.setObjectName("hint")
        self._files_label.setWordWrap(True)
        self._files_label.setVisible(False)
        root.addWidget(self._files_label)

        self._status = QLabel("")
        self._status.setObjectName("hint")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._browse_button = QPushButton(tr("Browse…"))
        self._browse_button.clicked.connect(self._browse)
        buttons.addWidget(self._browse_button)
        buttons.addStretch(1)
        cancel = QPushButton(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self._import = QPushButton(tr("Import"))
        self._import.setObjectName("primary")
        self._import.setDefault(True)
        self._import.clicked.connect(self._on_import)
        buttons.addWidget(self._import)
        root.addLayout(buttons)

    # ------------------------------------------------------------- sources

    def dragEnterEvent(self, event) -> None:
        # Dropping anywhere in the dialog works, not only on the zone: a user
        # aiming at a 500-px panel should not have to hit an 88-px strip.
        if event.mimeData().hasUrls() and DropZone._paths(event):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = DropZone._paths(event)
        if paths:
            self._add_files(paths)
            event.acceptProposedAction()

    def _browse(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr("Import a VPN config"),
            "",
            tr("Configs and QR images (*.conf *.txt *.json *.yaml *.yml *.png *.jpg *.jpeg);;All files (*)"),
        )
        if paths:
            self._add_files(paths)

    @pyqtSlot(object)
    def _add_files(self, paths: list) -> None:
        for path in paths:
            if path not in self._files:
                self._files.append(path)
        self._files_label.setVisible(bool(self._files))
        self._files_label.setText(
            tr("Queued files: %s") % ", ".join(Path(p).name for p in self._files)
        )

    # ------------------------------------------------------------- import

    def _on_import(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        # One link per line, but a wg-quick .conf pasted whole is multi-line and
        # must not be split, so the whole box goes through as one source unless
        # every non-empty line looks like a link.
        raw = self._input.toPlainText().strip()
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if lines and all("://" in line for line in lines):
            texts = lines
        elif raw:
            texts = [raw]
        else:
            texts = []

        if not texts and not self._files:
            self._set_status(tr("Paste a link or add a file first."), theme.WARNING)
            return

        self._set_busy(True)
        self._set_status(tr("Importing…"), theme.TEXT_MUTED)
        worker = ImportWorker(texts, list(self._files))
        worker.done.connect(self._on_done)
        worker.finished.connect(lambda: self._set_busy(False))
        self._worker = worker
        worker.start()

    @pyqtSlot(object, object)
    def _on_done(self, profiles: list, errors: list) -> None:
        if not profiles:
            self._set_status(
                "\n".join(errors) or tr("Nothing importable was found."), theme.DANGER
            )
            return
        self.profiles = profiles
        if errors:
            # Some sources worked: keep them rather than throwing the batch away,
            # but say what was dropped so a typo is not silently swallowed.
            self._set_status(
                tr("Imported %d, skipped %d:") % (len(profiles), len(errors))
                + "\n" + "\n".join(errors),
                theme.WARNING,
            )
            self._import.setText(tr("Close"))
            self._import.clicked.disconnect()
            self._import.clicked.connect(self.accept)
            return
        self.accept()

    def _set_busy(self, busy: bool) -> None:
        for widget in (self._import, self._browse_button, self._input, self._zone):
            widget.setEnabled(not busy)

    def _set_status(self, text: str, colour: str) -> None:
        self._status.setStyleSheet(f"color: {colour}; font-size: 11px;")
        self._status.setText(text)
