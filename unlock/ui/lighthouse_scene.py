"""Asset-backed animated lighthouse scene for the Home page."""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..controller import State


def _asset_path(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / "assets" / name


class LighthouseScene(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Arrow cursor over the sea — the scene is mostly window chrome now
        # (drag zone), so the hand pointer only makes sense over the tower.
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(520, 300)
        self._off = QPixmap(str(_asset_path("lighthouse_off_cropped.png")))
        self._on = QPixmap(str(_asset_path("lighthouse_on_cropped.png")))
        if self._off.isNull() or self._on.isNull():
            raise RuntimeError("Cropped lighthouse assets are missing or unreadable")
        self._mix = 0.0
        self._phase = 0.0
        self._badge: str | None = None
        self._state = State.IDLE
        self._pressed = False
        self._anim = QPropertyAnimation(self, b"mix", self)
        self._anim.setDuration(900)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _get_mix(self):
        return self._mix

    def _set_mix(self, value):
        self._mix = max(0.0, min(1.0, float(value)))
        self.update()

    mix = pyqtProperty(float, fget=_get_mix, fset=_set_mix)

    def set_state(self, state: State) -> None:
        self._state = state
        # Connecting lights up straight away — the lamp easing in is the
        # "working" signal, so a click always gets immediate visual feedback.
        target = 1.0 if state in (State.ACTIVE, State.DISCONNECTING, State.CONNECTING, State.BENCHMARKING) else 0.0
        self._anim.stop()
        self._anim.setStartValue(self._mix)
        self._anim.setEndValue(target)
        self._anim.start()

    def _lamp_alpha(self) -> float:
        """Effective brightness of the "on" layer for the current frame.

        The lamp eases in or out with _mix and holds a steady glow; no
        strobing while connecting — the sweep of the beam already reads as
        activity.
        """
        return self._mix

    def restyle(self) -> None:
        self.update()

    def _tick(self) -> None:
        self._phase += 0.033
        self.update()

    def _target_rect(self) -> QRectF:
        source = self._off.size()
        scale = min(self.width() / source.width(), self.height() / source.height())
        width, height = source.width() * scale, source.height() * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def _scene_clip(self) -> QPainterPath:
        """Widget rect with only the right-hand corners rounded.

        The scene fills the content area edge to edge; the left side butts
        against the sidebar, so rounding every corner would shave pixels off
        that seam. The window's own radius lives on the right.
        """
        w, h = self.width(), self.height()
        r = 17.0
        path = QPainterPath()
        path.moveTo(0, 0)
        path.lineTo(w - r, 0)
        path.arcTo(w - 2 * r, 0, 2 * r, 2 * r, 90, -90)
        path.lineTo(w, h - r)
        path.arcTo(w - 2 * r, h - 2 * r, 2 * r, 2 * r, 0, -90)
        path.lineTo(0, h)
        path.closeSubpath()
        return path

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        target = self._target_rect()
        painter.setClipPath(self._scene_clip())
        painter.fillRect(self.rect(), QColor(2, 8, 15))
        # The lighthouse rides the swell: a slow rock about its waterline,
        # so the tower pitches with the waves instead of sitting on rails.
        # The pixmap is drawn into a slightly inflated rect so the rotation
        # never exposes the rect's edges inside the clip.
        margin = max(target.width(), target.height()) * 0.035
        drawn = target.adjusted(-margin, -margin, margin, margin)
        painter.save()
        pivot = target.center()
        painter.translate(pivot)
        painter.rotate(1.1 * math.sin(self._phase * 0.55) + 0.5 * math.sin(self._phase * 0.9 + 1.4))
        painter.translate(-pivot)
        painter.setOpacity(1.0)
        painter.drawPixmap(drawn, self._off, QRectF(self._off.rect()))
        lamp = self._lamp_alpha()
        if lamp > 0.001:
            painter.setOpacity(lamp)
            painter.drawPixmap(drawn, self._on, QRectF(self._on.rect()))
        painter.setOpacity(1.0)
        painter.restore()
        painter.setOpacity(1.0)
        self._paint_overlays(painter, target)
        self._paint_badge(painter)

    def _paint_overlays(self, painter: QPainter, r: QRectF) -> None:
        painter.save()
        painter.setClipRect(r)
        pulse = 0.82 + 0.18 * math.sin(self._phase * 2.1)
        lamp = QPointF(r.left() + r.width() * 0.505, r.top() + r.height() * 0.315)
        light = self._lamp_alpha()

        if light > 0.01:
            direction = math.sin(self._phase * 0.55)
            end = QPointF(lamp.x() + r.width() * 0.52 * direction, lamp.y() + r.height() * 0.08)
            beam = QPainterPath(lamp)
            beam.lineTo(end.x(), end.y() - r.height() * 0.075)
            beam.lineTo(end.x(), end.y() + r.height() * 0.075)
            beam.closeSubpath()
            gradient = QLinearGradient(lamp, end)
            gradient.setColorAt(0, QColor(255, 239, 174, int(70 * light * pulse)))
            gradient.setColorAt(1, QColor(255, 225, 140, 0))
            painter.fillPath(beam, gradient)
            glow = QRadialGradient(lamp, r.height() * 0.16)
            glow.setColorAt(0, QColor(255, 242, 180, int(105 * light * pulse)))
            glow.setColorAt(1, QColor(255, 225, 140, 0))
            painter.fillRect(r, glow)
        else:
            # Off state: the lamp plays with cool light — a slow sweeping
            # beam and a flickering glow whose position wanders a little.
            sparkle = 0.55 + 0.30 * math.sin(self._phase * 1.6) + 0.15 * math.sin(self._phase * 2.7 + 1.3)
            direction = math.sin(self._phase * 0.35)
            end = QPointF(lamp.x() + r.width() * 0.34 * direction, lamp.y() + r.height() * 0.06)
            beam = QPainterPath(lamp)
            beam.lineTo(end.x(), end.y() - r.height() * 0.045)
            beam.lineTo(end.x(), end.y() + r.height() * 0.045)
            beam.closeSubpath()
            gradient = QLinearGradient(lamp, end)
            gradient.setColorAt(0, QColor(150, 205, 225, int(26 * sparkle)))
            gradient.setColorAt(1, QColor(150, 205, 225, 0))
            painter.fillPath(beam, gradient)
            wander = QPointF(lamp.x() + r.width() * 0.012 * math.sin(self._phase * 0.9),
                             lamp.y() + r.height() * 0.010 * math.cos(self._phase * 1.1))
            glow = QRadialGradient(wander, r.height() * (0.11 + 0.03 * sparkle))
            glow.setColorAt(0, QColor(150, 205, 225, int(40 + 42 * sparkle)))
            glow.setColorAt(1, QColor(150, 205, 225, 0))
            painter.fillRect(r, glow)

        # Wide, rolling waves under the lighthouse: fat semi-transparent
        # bodies of water with a bright crest line, each layer drifting at
        # its own pace and depth so the sea reads as moving masses, not
        # flat stripes.
        for layer in range(3):
            # Near layers (at the lighthouse foot) are taller, slower and
            # heavier; far ones sit lower and slide a little quicker.
            depth = 1.0 - layer * 0.28           # size/weight of the layer
            drift = self._phase * (0.42 + layer * 0.18)
            bob = self._phase * (0.9 + layer * 0.35)
            base = r.top() + r.height() * (0.68 + layer * 0.055)
            amp = r.height() * (0.034 + layer * 0.008) * depth
            swell = r.height() * (0.016 + layer * 0.005)
            path = QPainterPath()
            step = max(4.0, r.width() / 220)
            x = r.left()
            path.moveTo(x, r.bottom())
            path.lineTo(x, base)
            crest = []
            while x <= r.right() + step:
                fx = (x - r.left()) / max(r.width(), 1.0)
                # Two long travelling swells outrunning each other.
                y = base + math.sin(fx * math.tau * (1.3 + layer * 0.35) + drift) * amp
                y += math.sin(fx * math.tau * (2.1 + layer * 0.6) - drift * 1.6 + 1.7) * amp * 0.55
                # Slow heavy heave of the whole layer.
                y += math.sin(bob + fx * math.pi) * swell
                path.lineTo(x, y)
                crest.append(QPointF(x, y))
                x += step
            path.lineTo(r.right(), r.bottom())
            path.closeSubpath()
            # Water body: deeper and brighter toward the crest, fading down.
            water = QLinearGradient(0, base - amp, 0, r.bottom())
            water.setColorAt(0, QColor(70, 140, 160, 26 + layer * 12))
            water.setColorAt(0.35, QColor(30, 80, 105, 20 + layer * 9))
            water.setColorAt(1, QColor(10, 32, 48, 6))
            painter.fillPath(path, water)
            # Glowing foam line along the moving crest.
            painter.setPen(QPen(QColor(170, 225, 235, 34 + layer * 14), max(1.4, r.height() * 0.0035)))
            crest_path = QPainterPath()
            crest_path.moveTo(crest[0])
            for p in crest[1:]:
                crest_path.lineTo(p)
            painter.drawPath(crest_path)

        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(5):
            x = r.left() + r.width() * ((i * 0.23 + self._phase * (0.006 + i * 0.001)) % 1.15 - 0.08)
            y = r.top() + r.height() * (0.58 + i * 0.055)
            fog = QRadialGradient(QPointF(x, y), r.width() * 0.16)
            fog.setColorAt(0, QColor(190, 220, 225, 12))
            fog.setColorAt(1, QColor(190, 220, 225, 0))
            painter.setBrush(fog)
            painter.drawEllipse(QPointF(x, y), r.width() * 0.16, r.height() * 0.045)

        if self._pressed:
            wash = QRadialGradient(lamp, r.width() * 0.18)
            wash.setColorAt(0, QColor(255, 245, 205, 12))
            wash.setColorAt(1, QColor(255, 245, 205, 0))
            painter.fillRect(r, wash)
        painter.restore()

    def set_badge(self, text: str | None) -> None:
        """Paint a small status pill in the scene's bottom-right corner.

        ``None`` hides it. The text is tiny and semi-transparent so it reads
        as instrumentation layered over the picture, not as another card.
        """
        if self._badge != text:
            self._badge = text
            self.update()

    def _paint_badge(self, painter: QPainter) -> None:
        if not self._badge:
            return
        painter.save()
        painter.setClipPath(self._scene_clip())
        font = QFont(painter.font())
        font.setPointSizeF(10.0)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        fm = painter.fontMetrics()
        pad_x, pad_y = 12, 6
        w = fm.horizontalAdvance(self._badge) + pad_x * 2
        h = fm.height() + pad_y * 2
        margin = 14
        box = QRectF(self.width() - w - margin, self.height() - h - margin, w, h)
        pill = QPainterPath()
        pill.addRoundedRect(box, h / 2, h / 2)
        painter.fillPath(pill, QColor(6, 18, 28, 165))
        painter.setPen(QPen(QColor(170, 225, 235, 90), 1.0))
        painter.drawPath(pill)
        painter.setPen(QColor(190, 235, 240, 235))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self._badge)
        painter.restore()

    def _lighthouse_hit(self, pos: QPointF) -> bool:
        """True when the point lands on the lighthouse itself.

        Coordinates are fractions of the drawn target rect (same space the
        overlays use). The tower is a slim vertical silhouette near the
        horizontal center: a lamp head up top and a trunk down to the sea.
        """
        r = self._target_rect()
        if not r.contains(pos):
            return False
        fx = (pos.x() - r.left()) / r.width()
        fy = (pos.y() - r.top()) / r.height()
        # Lantern room / dome at the top of the tower.
        dx = (fx - 0.50) / 0.055
        dy = (fy - 0.265) / 0.085
        if dx * dx + dy * dy <= 1.0:
            return True
        # Tower trunk (slightly tapered, so a rectangle with a small margin).
        return 0.45 <= fx <= 0.55 and 0.27 <= fy <= 0.50

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._lighthouse_hit(event.position()):
            self._pressed = True
        else:
            # Ignoring lets the press climb to the main window, whose top strip
            # is a drag-to-move zone — without this the scene eats every grab.
            event.ignore()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._pressed and event.button() == Qt.MouseButton.LeftButton and self._lighthouse_hit(event.position()):
            self.clicked.emit()
        self._pressed = False
        self.update()
