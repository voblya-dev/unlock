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
    QPlainTextEdit,
    QScrollArea,
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
    """Left hero panel with a soft animated orbital scene."""

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

        base = QLinearGradient(0, 0, rect.width(), rect.height())
        base.setColorAt(0.0, QColor("#06111d"))
        base.setColorAt(0.45, QColor("#0d2434"))
        base.setColorAt(1.0, QColor("#15394d"))
        painter.fillRect(rect, base)

        for idx, alpha in enumerate((110, 80, 50)):
            radius = 190 + idx * 80 + self._progress * 40
            cx = rect.width() * (0.35 + idx * 0.17)
            cy = rect.height() * (0.20 + idx * 0.19)
            cx += 22 * math.cos(self._phase * (0.9 + idx * 0.2))
            cy += 18 * math.sin(self._phase * (1.2 + idx * 0.3))
            glow = QRadialGradient(cx, cy, radius)
            glow.setColorAt(0.0, QColor(130, 222, 255, alpha))
            glow.setColorAt(0.55, QColor(65, 165, 220, alpha // 3))
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(glow)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        painter.save()
        painter.translate(rect.center())
        scale = min(rect.width(), rect.height()) * 0.62
        ring_pen = QPen(QColor(195, 241, 255, 78), 1.5)
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
            painter.setBrush(QColor("#dbf7ff"))
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

        painter.setPen(QPen(QColor("#6ac4dd"), 1))
        painter.setBrush(QColor("#0c1d2a"))
        painter.drawRoundedRect(rect, 9, 9)

        if self._value <= 0:
            return

        fill = QRectF(rect)
        fill.setWidth(rect.width() * (self._value / 100.0))
        grad = QLinearGradient(fill.left(), fill.top(), fill.right(), fill.bottom())
        grad.setColorAt(0.0, QColor("#48bde5"))
        grad.setColorAt(0.5, QColor("#79f0ff"))
        grad.setColorAt(1.0, QColor("#2e7ed9"))
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
            "pending": ("#1a3344", "#4f7e93", "#a7c2cf"),
            "active": ("#143c47", "#6ef3ff", "#ecfcff"),
            "done": ("#0f4434", "#58f1ac", "#ecfff4"),
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
        self.setMinimumSize(1120, 720)
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
        body_layout.setContentsMargins(14, 12, 14, 14)
        body_layout.setSpacing(14)

        body_layout.addWidget(self._build_left_panel(), 9)
        body_layout.addWidget(self._build_right_scroll(), 11)
        shell_layout.addWidget(body, 1)

        outer_layout.addWidget(self.shell)
        self.setCentralWidget(outer)
        self._apply_styles()

    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("heroFrame")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(30, 28, 30, 28)
        layout.setSpacing(18)

        self.hero = AnimatedBackdrop()
        self.hero.setObjectName("hero")

        overlay = QVBoxLayout(self.hero)
        overlay.setContentsMargins(30, 26, 30, 26)
        overlay.setSpacing(14)

        badge = QLabel("FAST DEPLOY")
        badge.setObjectName("heroBadge")
        badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        overlay.addWidget(badge)

        title = QLabel("Install Unlock in one pass")
        title.setWordWrap(True)
        title.setObjectName("heroTitle")
        title.setFont(QFont("Bahnschrift SemiBold", 24))
        overlay.addWidget(title)

        subtitle = QLabel(
            "Download the latest release, verify the package, deploy it into "
            "your local programs folder and keep the post-install choices simple."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("heroSubtitle")
        overlay.addWidget(subtitle)

        chips = QWidget()
        chips_layout = QVBoxLayout(chips)
        chips_layout.setContentsMargins(0, 10, 0, 0)
        chips_layout.setSpacing(10)
        for text in (
            "Streams the release package with live progress",
            "Verifies SHA-256 before touching the install folder",
            "Creates shortcuts and optional Windows logon startup",
        ):
            row = QLabel(f"  {text}")
            row.setObjectName("heroBullet")
            chips_layout.addWidget(row)
        overlay.addWidget(chips)
        overlay.addStretch(1)

        version = QLabel(f"{APP_NAME} {APP_VERSION}")
        version.setObjectName("heroVersion")
        overlay.addWidget(version)

        layout.addWidget(self.hero, 1)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("rightPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        header = _card()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(22, 20, 22, 18)
        header_layout.setSpacing(10)
        kicker = QLabel("Bootstrap the full app")
        kicker.setObjectName("kicker")
        self.status_title = QLabel("Ready to install")
        self.status_title.setObjectName("statusTitle")
        self.status_detail = QLabel(
            "Review the destination and toggle the post-install options before starting."
        )
        self.status_detail.setWordWrap(True)
        self.status_detail.setObjectName("statusDetail")

        stages = QWidget()
        stages_layout = QHBoxLayout(stages)
        stages_layout.setContentsMargins(0, 10, 0, 0)
        stages_layout.setSpacing(8)
        self.stage_chips = [
            StageChip("Download"),
            StageChip("Verify"),
            StageChip("Install"),
            StageChip("Finish"),
        ]
        for chip in self.stage_chips:
            stages_layout.addWidget(chip, 1)
        self.stage_chips[0].set_state("active")

        header_layout.addWidget(kicker)
        header_layout.addWidget(self.status_title)
        header_layout.addWidget(self.status_detail)
        header_layout.addWidget(stages)
        layout.addWidget(header)

        path_card = _card()
        path_layout = QVBoxLayout(path_card)
        path_layout.setContentsMargins(22, 20, 22, 18)
        path_layout.setSpacing(12)
        path_title = QLabel("Destination")
        path_title.setObjectName("sectionTitle")
        path_hint = QLabel("Install per-user into LocalAppData. You can override the path if needed.")
        path_hint.setWordWrap(True)
        path_hint.setObjectName("sectionHint")
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
        path_layout.addWidget(path_title)
        path_layout.addWidget(path_hint)
        path_layout.addWidget(path_row)
        layout.addWidget(path_card)

        options = _card()
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(22, 20, 22, 18)
        options_layout.setSpacing(10)
        options_title = QLabel("Options")
        options_title.setObjectName("sectionTitle")
        options_layout.addWidget(options_title)
        self.desktop_row, self.desktop_box = self._option_box(
            "Create a desktop shortcut",
            "Easy launch point for the first-run flow.",
            checked=True,
        )
        self.start_menu_row, self.start_menu_box = self._option_box(
            "Add a Start Menu shortcut",
            "Pins the app into the standard Programs list.",
            checked=True,
        )
        self.logon_row, self.logon_box = self._option_box(
            "Launch Unlock when you sign in",
            "Registers a scheduled task so the elevated app can auto-start cleanly.",
            checked=False,
        )
        self.run_row, self.run_box = self._option_box(
            "Launch Unlock after install",
            "Open the app immediately once deployment is complete.",
            checked=True,
        )
        for row in (self.desktop_row, self.start_menu_row, self.logon_row, self.run_row):
            options_layout.addWidget(row)
        layout.addWidget(options)

        progress = _card()
        progress_layout = QVBoxLayout(progress)
        progress_layout.setContentsMargins(22, 20, 22, 18)
        progress_layout.setSpacing(12)
        progress_title = QLabel("Transfer")
        progress_title.setObjectName("sectionTitle")
        progress_top = QWidget()
        progress_top_layout = QHBoxLayout(progress_top)
        progress_top_layout.setContentsMargins(0, 0, 0, 0)
        progress_top_layout.setSpacing(10)
        self.progress_bar = ShimmerProgressBar()
        self.progress_label = QLabel("0%")
        self.progress_label.setObjectName("progressValue")
        progress_top_layout.addWidget(self.progress_bar, 1)
        progress_top_layout.addWidget(self.progress_label)
        self.progress_note = QLabel("Waiting for install start")
        self.progress_note.setObjectName("sectionHint")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("logView")
        self.log_view.setMinimumHeight(185)
        progress_layout.addWidget(progress_title)
        progress_layout.addWidget(progress_top)
        progress_layout.addWidget(self.progress_note)
        progress_layout.addWidget(self.log_view, 1)
        layout.addWidget(progress, 1)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(10)
        self.secondary_btn = QPushButton("Close")
        self.secondary_btn.setObjectName("secondaryButton")
        self.secondary_btn.clicked.connect(self._on_secondary_clicked)
        self.primary_btn = QPushButton("Install Unlock")
        self.primary_btn.setObjectName("primaryButton")
        self.primary_btn.clicked.connect(self._start_install)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self.secondary_btn)
        buttons_layout.addWidget(self.primary_btn)
        layout.addWidget(buttons)

        return panel

    def _build_right_scroll(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("rightScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(self._build_right_panel())
        return scroll

    def _wire_intro(self) -> None:
        for index, widget in enumerate((self.shell, self.centralWidget())):
            effect = widget.graphicsEffect()
            if effect is None:
                continue
            effect.setEnabled(index == 0)

    def _option_box(self, title: str, detail: str, *, checked: bool) -> tuple[QWidget, QCheckBox]:
        row = QWidget()
        row.setObjectName("optionRow")
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.setMinimumHeight(72)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        box = QCheckBox(title)
        box.setChecked(checked)
        box.setObjectName("optionBox")
        detail_label = QLabel(detail)
        detail_label.setWordWrap(True)
        detail_label.setObjectName("optionHint")
        layout.addWidget(box)
        layout.addWidget(detail_label)
        return row, box

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                color: #eff8ff;
                font-family: "Segoe UI";
                font-size: 13px;
            }
            QMainWindow {
                background: transparent;
            }
            #shell {
                background: #091722;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 30px;
            }
            #heroFrame {
                background: transparent;
            }
            #hero {
                border-radius: 26px;
                border: 1px solid rgba(255,255,255,0.08);
            }
            #heroBadge {
                color: #9deeff;
                background: rgba(12, 35, 50, 0.72);
                border: 1px solid rgba(157, 238, 255, 0.24);
                border-radius: 12px;
                font-size: 11px;
                font-weight: 700;
                padding: 6px 10px;
            }
            #heroTitle {
                color: white;
                font-size: 28px;
                font-weight: 700;
            }
            #heroSubtitle {
                color: rgba(236, 248, 255, 0.80);
                font-size: 14px;
            }
            #heroBullet {
                color: rgba(242, 252, 255, 0.88);
                background: rgba(7, 20, 30, 0.18);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 14px;
                padding: 10px 12px;
                font-size: 13px;
            }
            #heroVersion {
                color: rgba(255,255,255,0.56);
                font-size: 12px;
            }
            #card {
                background: rgba(13, 31, 44, 0.92);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 22px;
            }
            #titleBarText {
                color: rgba(240, 248, 255, 0.84);
                font-size: 12px;
                font-weight: 600;
            }
            #titleButton {
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 10px;
                color: rgba(255,255,255,0.75);
                font-size: 14px;
                font-weight: 600;
            }
            #titleButton:hover {
                background: rgba(255,255,255,0.10);
            }
            #closeButton:hover {
                background: rgba(255, 74, 74, 0.90);
                color: white;
            }
            #kicker {
                color: #7ae8ff;
                font-size: 11px;
                font-weight: 700;
            }
            #statusTitle {
                color: white;
                font-family: "Bahnschrift SemiBold";
                font-size: 25px;
            }
            #statusDetail, #sectionHint, #optionHint {
                color: rgba(235, 247, 255, 0.68);
            }
            #sectionTitle {
                color: white;
                font-size: 14px;
                font-weight: 700;
            }
            #pathEdit {
                background: rgba(5, 15, 24, 0.76);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 14px;
                padding: 0 14px;
                min-height: 46px;
                color: white;
                selection-background-color: #4bc6ee;
            }
            #pathEdit:focus {
                border-color: rgba(122, 232, 255, 0.54);
            }
            QPushButton {
                background: rgba(12, 29, 41, 0.95);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 14px;
                color: white;
                min-height: 46px;
                padding: 0 18px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(22, 49, 67, 0.95);
            }
            QPushButton:disabled {
                color: rgba(255,255,255,0.40);
                border-color: rgba(255,255,255,0.04);
                background: rgba(11, 22, 30, 0.88);
            }
            #primaryButton {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #4cd8ff,
                    stop:0.55 #58b6ff,
                    stop:1 #2f74ff
                );
                color: #031018;
                border: none;
                padding: 13px 22px;
                font-weight: 800;
            }
            #primaryButton:hover {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #79e8ff,
                    stop:0.55 #7bc8ff,
                    stop:1 #4e8cff
                );
            }
            #secondaryButton {
                min-width: 110px;
            }
            #rightScroll {
                background: transparent;
            }
            #rightScroll > QWidget > QWidget {
                background: transparent;
            }
            #optionRow {
                background: rgba(8, 20, 29, 0.72);
                border: 1px solid rgba(255,255,255,0.05);
                border-radius: 16px;
            }
            QCheckBox {
                spacing: 10px;
                color: white;
                font-size: 13px;
                font-weight: 600;
                min-height: 24px;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
            }
            QCheckBox::indicator:unchecked {
                border-radius: 6px;
                border: 1px solid rgba(255,255,255,0.18);
                background: rgba(255,255,255,0.04);
            }
            QCheckBox::indicator:checked {
                border-radius: 6px;
                border: 1px solid rgba(255,255,255,0.12);
                background: #5fe5ff;
            }
            #progressValue {
                color: #9deeff;
                font-size: 15px;
                font-weight: 800;
            }
            #logView {
                background: rgba(4, 12, 19, 0.88);
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 16px;
                padding: 12px;
                color: #98b7c8;
                font-family: "Cascadia Mono";
                font-size: 11px;
            }
            QScrollBar:vertical {
                width: 10px;
                margin: 8px 3px 8px 0;
                background: transparent;
            }
            QScrollBar::handle:vertical {
                background: rgba(116, 196, 226, 0.28);
                border-radius: 5px;
                min-height: 28px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                height: 0px;
                background: transparent;
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
        self.log_view.appendPlainText(text)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def _set_stage(self, index: int, title: str, detail: str) -> None:
        for idx, chip in enumerate(self.stage_chips):
            chip.set_state("done" if idx < index else "pending")
        self.stage_chips[index].set_state("active")
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
            self.primary_btn.setText("Installing...")
        else:
            self.secondary_btn.setText("Close")
            self.primary_btn.setText("Install Unlock")

    def _start_install(self) -> None:
        install_dir = self.path_edit.text().strip()
        if not install_dir:
            QMessageBox.warning(self, "Missing folder", "Select an install folder first.")
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
        for chip in self.stage_chips:
            chip.set_state("done")
        self.status_title.setText("Unlock is installed")
        self.status_detail.setText(f"Installed executable: {exe_path}")
        self.progress_note.setText("Deployment finished")
        self.primary_btn.setEnabled(False)
        self.secondary_btn.setText("Close")
        self._log(f"Installer: complete -> {exe_path}")

    def _install_failed(self, message: str) -> None:
        self._state.done = False
        self._set_running(False)
        self.status_title.setText("Installation failed")
        self.status_detail.setText(message)
        self.progress_note.setText("Fix the issue and run again")
        self._log(f"Installer: failed -> {message}")
        QMessageBox.critical(self, "Install failed", message)

    def _install_cancelled(self) -> None:
        self._state.done = False
        self._set_running(False)
        self.status_title.setText("Installation cancelled")
        self.status_detail.setText("No further changes were made after the cancel request.")
        self.progress_note.setText("Cancelled")
        self._log("Installer: cancelled")

    def _on_secondary_clicked(self) -> None:
        if self._state.running and self._thread is not None:
            self._thread.cancel()
            self.secondary_btn.setEnabled(False)
            self.secondary_btn.setText("Cancelling...")
            self._log("Installer: cancel requested")
            return
        self.close()

    def closeEvent(self, event) -> None:
        if self._state.running:
            QMessageBox.information(
                self,
                "Install in progress",
                "Cancel the install first or wait for it to finish.",
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
