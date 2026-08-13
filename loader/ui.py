"""Animated bootstrap installer window."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtProperty,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .config import APP_NAME, APP_VERSION, DEFAULT_INSTALL_DIR, bundled_asset
from .installer import InstallOptions, InstallerThread


def _shadow(widget: QWidget, blur: int = 32, y: int = 14) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y)
    effect.setColor(QColor(0, 0, 0, 80))
    widget.setGraphicsEffect(effect)


def _card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    _shadow(frame, blur=26, y=10)
    return frame


class AnimatedBackdrop(QWidget):
    """Obsidian installer backdrop: an understated monochrome signal grid."""

    def __init__(self) -> None:
        super().__init__()
        self._phase = 0.0
        self._energy = 0.25
        self._progress = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def sizeHint(self) -> QSize:
        return QSize(380, 680)

    def set_progress(self, value: int) -> None:
        self._progress = max(0.0, min(1.0, value / 100.0))
        self._energy = 0.25 + self._progress * 0.75
        self.update()

    def _tick(self) -> None:
        self._phase += 0.018 + self._energy * 0.01
        self.update()

    def paintEvent(self, _) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        painter.fillRect(rect, QColor("#0a0a0a"))
        painter.setPen(QPen(QColor(255, 255, 255, 14), 1))
        for x in range(0, rect.width(), 24):
            painter.drawLine(x, 0, x, rect.height())
        for y in range(0, rect.height(), 24):
            painter.drawLine(0, y, rect.width(), y)

        for idx, alpha in enumerate((110, 80, 50)):
            radius = 190 + idx * 80 + self._progress * 40
            cx = rect.width() * (0.35 + idx * 0.17)
            cy = rect.height() * (0.20 + idx * 0.19)
            cx += 22 * math.cos(self._phase * (0.9 + idx * 0.2))
            cy += 18 * math.sin(self._phase * (1.2 + idx * 0.3))
            glow = QRadialGradient(cx, cy, radius)
            glow.setColorAt(0.0, QColor(255, 255, 252, alpha // 2))
            glow.setColorAt(0.55, QColor(190, 190, 186, alpha // 5))
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(glow)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        painter.save()
        painter.translate(rect.center())
        scale = min(rect.width(), rect.height()) * 0.62
        ring_pen = QPen(QColor(245, 245, 242, 68), 1.5)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for idx in range(4):
            painter.setPen(ring_pen)
            orbit_w = scale * (0.52 + idx * 0.12)
            orbit_h = scale * (0.18 + idx * 0.09)
            painter.drawEllipse(QRectF(-orbit_w / 2, -orbit_h / 2, orbit_w, orbit_h))

        for idx in range(8):
            angle = self._phase * (0.9 + idx * 0.04) + idx * 0.65
            orbit_w = scale * (0.52 + (idx % 4) * 0.12)
            orbit_h = scale * (0.18 + (idx % 4) * 0.09)
            x = (orbit_w / 2) * math.cos(angle)
            y = (orbit_h / 2) * math.sin(angle)
            dot = 6 + (idx % 3) * 3 + self._progress * 6
            painter.setBrush(QColor("#f5f5f2"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(x - dot / 2, y - dot / 2, dot, dot))
        painter.restore()

        painter.setPen(QColor(255, 255, 255, 22))
        for y in range(0, rect.height(), 9):
            alpha = 8 if (y // 9) % 2 else 16
            painter.setPen(QColor(255, 255, 255, alpha))
            painter.drawLine(0, y, rect.width(), y)


class ShimmerProgressBar(QWidget):
    """Custom progress bar with a moving highlight."""

    def __init__(self) -> None:
        super().__init__()
        self._value = 0.0
        self._shine = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)
        self.setMinimumHeight(18)
        self.setMaximumHeight(18)

    def sizeHint(self) -> QSize:
        return QSize(240, 18)

    def _tick(self) -> None:
        self._shine = (self._shine + 0.022) % 1.0
        self.update()

    def getValue(self) -> float:
        return self._value

    def setValue(self, value: float) -> None:
        self._value = max(0.0, min(100.0, value))
        self.update()

    value = pyqtProperty(float, fget=getValue, fset=setValue)

    def paintEvent(self, _) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        painter.setPen(QPen(QColor("#666662"), 1))
        painter.setBrush(QColor("#101010"))
        painter.drawRoundedRect(rect, 9, 9)

        if self._value <= 0:
            return

        fill = QRectF(rect)
        fill.setWidth(rect.width() * (self._value / 100.0))
        grad = QLinearGradient(fill.left(), fill.top(), fill.right(), fill.bottom())
        grad.setColorAt(0.0, QColor("#92928d"))
        grad.setColorAt(0.5, QColor("#f5f5f2"))
        grad.setColorAt(1.0, QColor("#b9b9b4"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawRoundedRect(fill, 9, 9)

        sweep_x = fill.left() + fill.width() * self._shine
        sweep = QLinearGradient(sweep_x - 90, 0, sweep_x + 40, 0)
        sweep.setColorAt(0.0, QColor(255, 255, 255, 0))
        sweep.setColorAt(0.5, QColor(255, 255, 255, 110))
        sweep.setColorAt(1.0, QColor(255, 255, 255, 0))
        clip = QPainterPath()
        clip.addRoundedRect(fill, 9, 9)
        painter.setClipPath(clip)
        painter.fillRect(fill, sweep)


class StageChip(QFrame):
    """Small badge for a single install stage."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self._state = "pending"
        self.setObjectName("stageChip")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        self.label = QLabel(title)
        self.label.setObjectName("stageLabel")
        layout.addWidget(self.dot)
        layout.addWidget(self.label)
        layout.addStretch(1)
        self.set_state("pending")

    def set_state(self, state: str) -> None:
        self._state = state
        colors = {
            "pending": ("#151515", "#666662", "#a5a5a0"),
            "active": ("#292929", "#f5f5f2", "#f5f5f2"),
            "done": ("#202020", "#d0d0cb", "#ededE8"),
        }
        bg, dot, text = colors[state]
        self.setStyleSheet(
            f"""
            #stageChip {{
                background-color: {bg};
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 14px;
            }}
            QLabel#stageLabel {{
                color: {text};
                font-size: 12px;
                font-weight: 600;
            }}
            QLabel {{
                background-color: transparent;
            }}
            """
        )
        self.dot.setStyleSheet(
            f"background-color: {dot}; border-radius: 5px; "
            "border: 1px solid rgba(255,255,255,0.18);"
        )


class TitleBar(QWidget):
    """Frameless title bar with drag support."""

    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self._window = window
        self._drag_pos = QPoint()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 0)
        layout.setSpacing(8)

        icon = QLabel()
        icon_path = bundled_asset("unlock-white.ico")
        if icon_path.exists():
            icon.setPixmap(QIcon(str(icon_path)).pixmap(18, 18))
        title = QLabel(f"{APP_NAME} bootstrap installer")
        title.setObjectName("titleBarText")
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addStretch(1)

        self.min_btn = QPushButton("-")
        self.close_btn = QPushButton("x")
        for button in (self.min_btn, self.close_btn):
            button.setObjectName("titleButton")
            button.setFixedSize(34, 28)
        self.close_btn.setObjectName("closeButton")
        self.min_btn.clicked.connect(window.showMinimized)
        self.close_btn.clicked.connect(window.close)
        layout.addWidget(self.min_btn)
        layout.addWidget(self.close_btn)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()


@dataclass(slots=True)
class InstallState:
    running: bool = False
    done: bool = False
    progress: int = 0


class InstallerWindow(QMainWindow):
    """Main loader window."""

    def __init__(self) -> None:
        super().__init__()
        self._thread: InstallerThread | None = None
        self._state = InstallState()
        self._progress_anim: QPropertyAnimation | None = None
        self._build_window()
        self._wire_intro()

    def _build_window(self) -> None:
        self.setWindowTitle(f"{APP_NAME} installer")
        icon_path = bundled_asset("unlock-white.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumSize(920, 600)
        self.resize(960, 620)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(18, 18, 18, 18)

        self.shell = QFrame()
        self.shell.setObjectName("shell")
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        _shadow(self.shell, blur=48, y=18)

        self.title_bar = TitleBar(self)
        shell_layout.addWidget(self.title_bar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(12, 10, 12, 12)
        body_layout.setSpacing(12)

        body_layout.addWidget(self._build_left_panel(), 7)
        body_layout.addWidget(self._build_right_panel(), 10)
        shell_layout.addWidget(body, 1)

        outer_layout.addWidget(self.shell)
        self.setCentralWidget(outer)
        self._apply_styles()

    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("heroFrame")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        self.hero = AnimatedBackdrop()
        self.hero.setObjectName("hero")

        overlay = QVBoxLayout(self.hero)
        overlay.setContentsMargins(28, 26, 28, 26)
        overlay.setSpacing(12)

        badge = QLabel("UNLOCK")
        badge.setObjectName("heroBadge")
        badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        overlay.addWidget(badge)

        title = QLabel("Install\nUnlock")
        title.setWordWrap(True)
        title.setObjectName("heroTitle")
        title.setFont(QFont("Bahnschrift SemiBold", 24))
        overlay.addWidget(title)

        subtitle = QLabel("Quick, secure installation for Windows.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("heroSubtitle")
        overlay.addWidget(subtitle)

        overlay.addStretch(1)

        version = QLabel(f"{APP_NAME} {APP_VERSION}")
        version.setObjectName("heroVersion")
        overlay.addWidget(version)

        layout.addWidget(self.hero, 1)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("rightPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(32, 32, 32, 28)
        layout.setSpacing(18)

        self.status_title = QLabel("Install Unlock")
        self.status_title.setObjectName("statusTitle")
        self.status_detail = QLabel(f"Version {APP_VERSION}")
        self.status_detail.setWordWrap(True)
        self.status_detail.setObjectName("statusDetail")
        layout.addWidget(self.status_title)
        layout.addWidget(self.status_detail)
        layout.addSpacing(8)

        path_title = QLabel("Install location")
        path_title.setObjectName("sectionTitle")
        path_row = QWidget()
        path_row_layout = QHBoxLayout(path_row)
        path_row_layout.setContentsMargins(0, 0, 0, 0)
        path_row_layout.setSpacing(10)
        self.path_edit = QLineEdit(str(DEFAULT_INSTALL_DIR))
        self.path_edit.setObjectName("pathEdit")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_install_dir)
        path_row_layout.addWidget(self.path_edit, 1)
        path_row_layout.addWidget(browse)
        layout.addWidget(path_title)
        layout.addWidget(path_row)

        options = QWidget()
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(4)
        options_title = QLabel("Options")
        options_title.setObjectName("sectionTitle")
        options_layout.addWidget(options_title)
        self.desktop_row, self.desktop_box = self._option_box(
            "Create a desktop shortcut",
            checked=True,
        )
        self.start_menu_row, self.start_menu_box = self._option_box(
            "Add a Start Menu shortcut",
            checked=True,
        )
        self.logon_row, self.logon_box = self._option_box(
            "Launch Unlock when you sign in",
            checked=False,
        )
        self.run_row, self.run_box = self._option_box(
            "Launch Unlock after install",
            checked=True,
        )
        for row in (self.desktop_row, self.start_menu_row, self.logon_row, self.run_row):
            options_layout.addWidget(row)
        layout.addWidget(options)
        layout.addStretch(1)

        progress = QWidget()
        progress_layout = QVBoxLayout(progress)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(8)
        progress_top = QWidget()
        progress_top_layout = QHBoxLayout(progress_top)
        progress_top_layout.setContentsMargins(0, 0, 0, 0)
        progress_top_layout.setSpacing(10)
        self.progress_bar = ShimmerProgressBar()
        self.progress_label = QLabel("0%")
        self.progress_label.setObjectName("progressValue")
        progress_top_layout.addWidget(self.progress_bar, 1)
        progress_top_layout.addWidget(self.progress_label)
        self.progress_note = QLabel("Ready to install")
        self.progress_note.setObjectName("sectionHint")
        progress_layout.addWidget(progress_top)
        progress_layout.addWidget(self.progress_note)
        layout.addWidget(progress)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(10)
        self.secondary_btn = QPushButton("Cancel")
        self.secondary_btn.setObjectName("secondaryButton")
        self.secondary_btn.clicked.connect(self._on_secondary_clicked)
        self.primary_btn = QPushButton("Install")
        self.primary_btn.setObjectName("primaryButton")
        self.primary_btn.clicked.connect(self._start_install)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self.secondary_btn)
        buttons_layout.addWidget(self.primary_btn)
        layout.addWidget(buttons)

        return panel

    def _wire_intro(self) -> None:
        for index, widget in enumerate((self.shell, self.centralWidget())):
            effect = widget.graphicsEffect()
            if effect is None:
                continue
            effect.setEnabled(index == 0)

    def _option_box(self, title: str, *, checked: bool) -> tuple[QWidget, QCheckBox]:
        row = QWidget()
        row.setObjectName("optionRow")
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.setMinimumHeight(38)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        box = QCheckBox(title)
        box.setChecked(checked)
        box.setObjectName("optionBox")
        layout.addWidget(box)
        layout.addStretch(1)
        return row, box

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                color: #f5f5f2;
                font-family: "Segoe UI Variable", "Segoe UI";
                font-size: 13px;
            }
            QMainWindow {
                background: transparent;
            }
            #shell {
                background: #0a0a0a;
                border: 1px solid #303030;
                border-radius: 16px;
            }
            #heroFrame {
                background: transparent;
            }
            #hero {
                border-radius: 12px;
                border: none;
            }
            #heroBadge {
                color: #f5f5f2;
                background: #181818;
                border: 1px solid #555550;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 700;
                padding: 6px 10px;
            }
            #heroTitle {
                color: white;
                font-size: 30px;
                font-weight: 700;
            }
            #heroSubtitle {
                color: #b3b3ae;
                font-size: 14px;
            }
            #heroBullet {
                color: #d0d0cb;
                background: #151515;
                border: 1px solid #303030;
                border-radius: 4px;
                padding: 10px 12px;
                font-size: 13px;
            }
            #heroVersion {
                color: #7b7b77;
                font-size: 12px;
            }
            #rightPanel {
                background: transparent;
            }
            #titleBarText {
                color: #b9b9b4;
                font-size: 12px;
                font-weight: 600;
            }
            #titleButton {
                background: transparent;
                border: none;
                border-radius: 4px;
                color: rgba(255,255,255,0.75);
                font-size: 14px;
                font-weight: 600;
            }
            #titleButton:hover {
                background: rgba(255,255,255,0.10);
            }
            #closeButton:hover {
                background: #f5f5f2;
                color: #0a0a0a;
            }
            #kicker {
                color: #bdbdb8;
                font-size: 11px;
                font-weight: 700;
            }
            #statusTitle {
                color: white;
                font-family: "Bahnschrift SemiBold";
                font-size: 28px;
            }
            #statusDetail, #sectionHint {
                color: #a5a5a0;
            }
            #sectionTitle {
                color: white;
                font-size: 14px;
                font-weight: 700;
            }
            #pathEdit {
                background: #0a0a0a;
                border: 1px solid #3a3a38;
                border-radius: 4px;
                padding: 0 14px;
                min-height: 46px;
                color: white;
                selection-background-color: #f5f5f2;
            }
            #pathEdit:focus {
                border-color: #f5f5f2;
            }
            QPushButton {
                background: #161616;
                border: 1px solid #393939;
                border-radius: 4px;
                color: white;
                min-height: 46px;
                padding: 0 18px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #242424;
            }
            QPushButton:disabled {
                color: #747470;
                border-color: #282828;
                background: #101010;
            }
            #primaryButton {
                background: #f5f5f2;
                color: #0a0a0a;
                border: 1px solid #f5f5f2;
                padding: 13px 22px;
                font-weight: 800;
            }
            #primaryButton:hover {
                background: white;
            }
            #secondaryButton {
                min-width: 110px;
            }
            #optionRow {
                background: transparent;
                border: none;
            }
            QCheckBox {
                spacing: 10px;
                color: #d0d0cb;
                font-size: 12px;
                font-weight: 500;
                min-height: 24px;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
            }
            QCheckBox::indicator:unchecked {
                border-radius: 3px;
                border: 1px solid #5b5b57;
                background: #111111;
            }
            QCheckBox::indicator:checked {
                border-radius: 3px;
                border: 1px solid #f5f5f2;
                background: #f5f5f2;
            }
            #progressValue {
                color: #f5f5f2;
                font-size: 15px;
                font-weight: 800;
            }
            """
        )

    def _browse_install_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select install folder",
            self.path_edit.text() or str(DEFAULT_INSTALL_DIR),
        )
        if selected:
            self.path_edit.setText(selected)

    def _log(self, text: str) -> None:
        # Keep the primary flow quiet like a standard Windows installer. Errors
        # are surfaced in a dialog; this short in-memory trace is only useful
        # while the process is alive for debugging from a parent launcher.
        self._last_log = text

    def _set_stage(self, index: int, title: str, detail: str) -> None:
        self.status_title.setText(title)
        self.status_detail.setText(detail)

    def _set_progress(self, value: int, note: str) -> None:
        self._state.progress = value
        self.progress_label.setText(f"{value}%")
        self.progress_note.setText(note)
        self.hero.set_progress(value)

        animation = QPropertyAnimation(self.progress_bar, b"value", self)
        animation.setDuration(240)
        animation.setStartValue(self.progress_bar.getValue())
        animation.setEndValue(float(value))
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start()
        self._progress_anim = animation

    def _collect_options(self) -> InstallOptions:
        return InstallOptions(
            install_dir=Path(self.path_edit.text()).expanduser(),
            desktop_shortcut=self.desktop_box.isChecked(),
            start_menu_shortcut=self.start_menu_box.isChecked(),
            launch_on_login=self.logon_box.isChecked(),
            launch_after_install=self.run_box.isChecked(),
        )

    def _set_running(self, running: bool) -> None:
        self._state.running = running
        widgets = [
            self.path_edit,
            self.desktop_box,
            self.start_menu_box,
            self.logon_box,
            self.run_box,
            self.primary_btn,
        ]
        for widget in widgets:
            widget.setEnabled(not running)
        self.secondary_btn.setEnabled(True)
        if running:
            self.secondary_btn.setText("Cancel")
            self.primary_btn.setText("Installing…")
        else:
            self.secondary_btn.setText("Cancel")
            self.primary_btn.setText("Install")

    def _start_install(self) -> None:
        install_dir = self.path_edit.text().strip()
        if not install_dir:
            QMessageBox.warning(self, "Choose a folder", "Choose an install folder first.")
            return
        options = self._collect_options()
        self._thread = InstallerThread(options)
        self._thread.stage_changed.connect(self._set_stage)
        self._thread.progress_changed.connect(self._set_progress)
        self._thread.log_message.connect(self._log)
        self._thread.install_succeeded.connect(self._install_succeeded)
        self._thread.install_failed.connect(self._install_failed)
        self._thread.install_cancelled.connect(self._install_cancelled)
        self._log("Installer: starting")
        self._set_running(True)
        self._thread.start()

    def _install_succeeded(self, exe_path: str) -> None:
        self._state.done = True
        self._set_running(False)
        self.status_title.setText("Unlock is installed")
        self.status_detail.setText("You can close the installer.")
        self.progress_note.setText("Installation complete")
        self.primary_btn.setEnabled(False)
        self.secondary_btn.setText("Close")
        self._log(f"Installer: complete -> {exe_path}")

    def _install_failed(self, message: str) -> None:
        self._state.done = False
        self._set_running(False)
        self.status_title.setText("Installation failed")
        self.status_detail.setText(message)
        self.progress_note.setText("Fix the problem and try again")
        self._log(f"Installer: failed -> {message}")
        QMessageBox.critical(self, "Installation failed", message)

    def _install_cancelled(self) -> None:
        self._state.done = False
        self._set_running(False)
        self.status_title.setText("Installation cancelled")
        self.status_detail.setText("Change the options and start again when ready.")
        self.progress_note.setText("Cancelled")
        self._log("Installer: cancelled")

    def _on_secondary_clicked(self) -> None:
        if self._state.running and self._thread is not None:
            self._thread.cancel()
            self.secondary_btn.setEnabled(False)
            self.secondary_btn.setText("Cancelling…")
            self._log("Installer: cancel requested")
            return
        self.close()

    def closeEvent(self, event) -> None:
        if self._state.running:
            QMessageBox.information(
                self,
                "Installation in progress",
                "Cancel the installation first or wait for it to finish.",
            )
            event.ignore()
            return
        super().closeEvent(event)


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(True)
    window = InstallerWindow()
    window.show()
    return app.exec()
