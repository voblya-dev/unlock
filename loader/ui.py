"""Animated bootstrap installer window."""

from __future__ import annotations

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
    QPixmap,
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
from .installer import InstallOptions, InstallerThread, UninstallerThread


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


class MinimalBackdrop(QFrame):
    """Static brand panel with a large, low-contrast mask watermark."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("hero")
        self._mask = QPixmap(str(bundled_asset("unlock-readme.png")))

    def sizeHint(self) -> QSize:
        return QSize(300, 560)

    def set_progress(self, value: int) -> None:
        """Preserve the existing install callback without visual side effects."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._mask.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setOpacity(0.16)
        side = max(int(self.width() * 0.96), int(self.height() * 0.80))
        target = QRectF(
            (self.width() - side) / 2,
            (self.height() - side) / 2,
            side,
            side,
        )
        painter.drawPixmap(target.toRect(), self._mask)


class OptionCheckBox(QCheckBox):
    """A compact checkbox with an explicit, high-contrast tick mark."""

    def __init__(self, title: str) -> None:
        super().__init__(title)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = 18
        box = QRectF(10, (self.height() - side) / 2, side, side)
        checked = self.isChecked()
        painter.setPen(QPen(QColor("#f5f5f2") if checked else QColor("#686864"), 1.2))
        painter.setBrush(QColor("#f5f5f2") if checked else QColor("#0a0a0a"))
        painter.drawRoundedRect(box, 4, 4)
        if checked:
            tick = QPainterPath()
            tick.moveTo(box.left() + 4, box.center().y())
            tick.lineTo(box.left() + 7.5, box.bottom() - 4.5)
            tick.lineTo(box.right() - 3.5, box.top() + 4.5)
            painter.setPen(QPen(QColor("#0a0a0a"), 2.0, cap=Qt.PenCapStyle.RoundCap))
            painter.drawPath(tick)
        painter.setPen(QColor("#f1f1ed") if self.isEnabled() else QColor("#747470"))
        painter.setFont(self.font())
        painter.drawText(
            self.rect().adjusted(40, 0, -10, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )


class WindowControlButton(QPushButton):
    """Font-independent minimize and close controls for the frameless window."""

    def __init__(self, kind: str) -> None:
        super().__init__()
        self._kind = kind
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover = self.underMouse()
        if hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#f5f5f2") if self._kind == "close" else QColor("#242424"))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        color = QColor("#0a0a0a") if hover and self._kind == "close" else QColor("#d6d6d1")
        painter.setPen(QPen(color, 1.6, cap=Qt.PenCapStyle.RoundCap))
        cx, cy = self.width() / 2, self.height() / 2
        if self._kind == "minimize":
            painter.drawLine(QPoint(int(cx - 5), int(cy + 3)), QPoint(int(cx + 5), int(cy + 3)))
        else:
            painter.drawLine(QPoint(int(cx - 4), int(cy - 4)), QPoint(int(cx + 4), int(cy + 4)))
            painter.drawLine(QPoint(int(cx + 4), int(cy - 4)), QPoint(int(cx - 4), int(cy + 4)))


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
        icon_path = bundled_asset("unlock-mask.ico")
        if icon_path.exists():
            icon.setPixmap(QIcon(str(icon_path)).pixmap(18, 18))
        title = QLabel(f"{APP_NAME} bootstrap installer")
        title.setObjectName("titleBarText")
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addStretch(1)

        self.min_btn = WindowControlButton("minimize")
        self.close_btn = WindowControlButton("close")
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
        self._thread: InstallerThread | UninstallerThread | None = None
        self._operation: str | None = None
        self._state = InstallState()
        self._progress_anim: QPropertyAnimation | None = None
        self._build_window()
        self._wire_intro()

    def _build_window(self) -> None:
        self.setWindowTitle(f"{APP_NAME} installer")
        icon_path = bundled_asset("unlock-mask.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        # The option rows keep their full hit area instead of being compressed
        # into each other on a short window.
        self.setMinimumSize(850, 670)
        self.resize(920, 690)
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
        self._refresh_install_actions()

    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("heroFrame")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        self.hero = MinimalBackdrop()

        overlay = QVBoxLayout(self.hero)
        overlay.setContentsMargins(28, 26, 28, 26)
        overlay.setSpacing(12)
        overlay.addStretch(1)

        badge = QLabel("UNLOCK FOR WINDOWS")
        badge.setObjectName("heroBadge")
        badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        overlay.addWidget(badge)

        title = QLabel("Install\nUnlock")
        title.setWordWrap(True)
        title.setObjectName("heroTitle")
        title.setFont(QFont("Bahnschrift SemiBold", 24))
        overlay.addWidget(title)

        subtitle = QLabel("A simple setup for your network tools.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("heroSubtitle")
        overlay.addWidget(subtitle)

        overlay.addStretch(2)

        version = QLabel(f"{APP_NAME} {APP_VERSION}")
        version.setObjectName("heroVersion")
        overlay.addWidget(version)

        layout.addWidget(self.hero, 1)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("rightPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 24, 22)
        layout.setSpacing(10)

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
        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self._browse_install_dir)
        path_row_layout.addWidget(self.path_edit, 1)
        path_row_layout.addWidget(self.browse_btn)
        self.path_edit.textChanged.connect(self._refresh_install_actions)
        layout.addWidget(path_title)
        layout.addWidget(path_row)

        options = QWidget()
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(8)
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
        buttons.setObjectName("buttonRow")
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(10)
        self.secondary_btn = QPushButton("Cancel")
        self.secondary_btn.setObjectName("secondaryButton")
        self.secondary_btn.clicked.connect(self._on_secondary_clicked)
        self.primary_btn = QPushButton("Install")
        self.primary_btn.setObjectName("primaryButton")
        self.primary_btn.clicked.connect(self._start_install)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setObjectName("dangerButton")
        self.remove_btn.clicked.connect(self._start_remove)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self.remove_btn)
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
        row.setFixedHeight(40)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        box = OptionCheckBox(title)
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
                border: 1px solid #242424;
                background: #0d0d0d;
            }
            #heroBadge {
                color: #f5f5f2;
                background: transparent;
                border: none;
                border-radius: 0;
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
                border-radius: 8px;
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
                border-radius: 8px;
                padding: 0 14px;
                min-height: 46px;
                color: white;
                selection-background-color: #f5f5f2;
            }
            #pathEdit:focus {
                border-color: #f5f5f2;
            }
            QPushButton {
                background: #171717;
                border: 1px solid #363636;
                border-radius: 8px;
                color: white;
                min-height: 46px;
                padding: 0 18px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #232323;
                border-color: #575757;
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
                background: #ffffff;
                border-color: #ffffff;
            }
            #buttonRow QPushButton {
                min-width: 118px;
            }
            #optionRow {
                background: #111111;
                border: 1px solid #292929;
                border-radius: 8px;
            }
            QCheckBox {
                background: transparent;
                border: none;
                font-size: 13px;
                font-weight: 500;
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

    def _install_dir(self) -> Path:
        return Path(self.path_edit.text().strip()).expanduser()

    def _has_existing_install(self) -> bool:
        return (self._install_dir() / f"{APP_NAME}.exe").is_file()

    def _refresh_install_actions(self) -> None:
        if self._state.running:
            return
        installed = self._has_existing_install()
        self.primary_btn.setText("Reinstall latest" if installed else "Install")
        self.remove_btn.setEnabled(installed)

    def _set_running(self, running: bool) -> None:
        self._state.running = running
        widgets = [
            self.path_edit,
            self.browse_btn,
            self.desktop_box,
            self.start_menu_box,
            self.logon_box,
            self.run_box,
            self.primary_btn,
            self.remove_btn,
        ]
        for widget in widgets:
            widget.setEnabled(not running)
        self.secondary_btn.setEnabled(True)
        if running:
            self.secondary_btn.setText("Cancel")
            self.primary_btn.setText("Removing…" if self._operation == "remove" else "Installing…")
            if self._operation == "remove":
                self.secondary_btn.setEnabled(False)
        else:
            self.secondary_btn.setText("Cancel")
            self._refresh_install_actions()

    def _start_install(self) -> None:
        install_dir = self.path_edit.text().strip()
        if not install_dir:
            QMessageBox.warning(self, "Choose a folder", "Choose an install folder first.")
            return
        if self._has_existing_install():
            reply = QMessageBox.question(
                self,
                "Reinstall latest Unlock",
                "The latest available release will replace the current app files. "
                "Your settings and VPN profiles will be kept. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        options = self._collect_options()
        self._thread = InstallerThread(options)
        self._operation = "install"
        self._thread.stage_changed.connect(self._set_stage)
        self._thread.progress_changed.connect(self._set_progress)
        self._thread.log_message.connect(self._log)
        self._thread.install_succeeded.connect(self._install_succeeded)
        self._thread.install_failed.connect(self._install_failed)
        self._thread.install_cancelled.connect(self._install_cancelled)
        self._log("Installer: starting")
        self._set_running(True)
        self._thread.start()

    def _start_remove(self) -> None:
        install_dir = self.path_edit.text().strip()
        if not install_dir or not self._has_existing_install():
            QMessageBox.information(self, "Unlock is not installed", "No Unlock installation was found in this folder.")
            self._refresh_install_actions()
            return
        reply = QMessageBox.warning(
            self,
            "Remove Unlock",
            "Remove Unlock, its shortcuts and its startup entry?\n\n"
            "Your settings, VPN profiles and logs will be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._thread = UninstallerThread(self._install_dir())
        self._operation = "remove"
        self._thread.stage_changed.connect(self._set_stage)
        self._thread.progress_changed.connect(self._set_progress)
        self._thread.log_message.connect(self._log)
        self._thread.uninstall_succeeded.connect(self._uninstall_succeeded)
        self._thread.uninstall_failed.connect(self._uninstall_failed)
        self._set_running(True)
        self._thread.start()

    def _install_succeeded(self, exe_path: str) -> None:
        self._state.done = True
        self._operation = None
        self._set_running(False)
        self.status_title.setText("Unlock is installed")
        self.status_detail.setText("You can close the installer.")
        self.progress_note.setText("Installation complete")
        self.primary_btn.setEnabled(False)
        self.secondary_btn.setText("Close")
        self._log(f"Installer: complete -> {exe_path}")

    def _install_failed(self, message: str) -> None:
        self._state.done = False
        self._operation = None
        self._set_running(False)
        self.status_title.setText("Installation failed")
        self.status_detail.setText(message)
        self.progress_note.setText("Fix the problem and try again")
        self._log(f"Installer: failed -> {message}")
        QMessageBox.critical(self, "Installation failed", message)

    def _install_cancelled(self) -> None:
        self._state.done = False
        self._operation = None
        self._set_running(False)
        self.status_title.setText("Installation cancelled")
        self.status_detail.setText("Change the options and start again when ready.")
        self.progress_note.setText("Cancelled")
        self._log("Installer: cancelled")

    def _uninstall_succeeded(self, install_dir: str) -> None:
        self._state.done = True
        self._operation = None
        self._set_running(False)
        self.status_title.setText("Unlock was removed")
        self.status_detail.setText("Your settings and VPN profiles were kept.")
        self.progress_note.setText("Removal complete")
        self._log(f"Uninstaller: complete -> {install_dir}")

    def _uninstall_failed(self, message: str) -> None:
        self._state.done = False
        self._operation = None
        self._set_running(False)
        self.status_title.setText("Removal failed")
        self.status_detail.setText(message)
        self.progress_note.setText("Close Unlock and try again")
        self._log(f"Uninstaller: failed -> {message}")
        QMessageBox.critical(self, "Removal failed", message)

    def _on_secondary_clicked(self) -> None:
        if self._state.running and isinstance(self._thread, InstallerThread):
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
