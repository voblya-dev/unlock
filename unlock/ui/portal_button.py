"""Animated server portal used by the VPN switch."""

from __future__ import annotations

import math

from PyQt6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QConicalGradient, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

from ..controller import State
from . import theme

_SIZE = 190
_BUSY = (State.CONNECTING, State.DISCONNECTING)


class PortalButton(QWidget):
    """A tunnel that grows from a local core towards a remote orbital node."""

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, size: int = _SIZE) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent;")
        self._state = State.IDLE; self._hovered = False; self._tunnel = 0.0
        self._pulse = 0.0; self._orbit = 0.0; self._press = 0.0; self._companion = 0.0
        self._colour = QColor(theme.TEXT_FAINT); self._scale = size / _SIZE
        self._animations: dict[QPropertyAnimation, QEasingCurve.Type] = {}
        self._tunnel_a = self._make(b"tunnel", 1100, QEasingCurve.Type.InOutCubic)
        self._pulse_a = self._make(b"pulse", 540, QEasingCurve.Type.OutCubic)
        self._press_a = self._make(b"press", 220, QEasingCurve.Type.OutBack)
        self._tint_a = self._make(b"tint", 420, QEasingCurve.Type.InOutCubic)
        self._companion_a = self._make(b"companion", 600, QEasingCurve.Type.InOutCubic)
        self._orbit_a = self._make(b"orbit", 4200, QEasingCurve.Type.Linear)
        self._orbit_a.setStartValue(0.0); self._orbit_a.setEndValue(1.0); self._orbit_a.setLoopCount(-1); self._orbit_a.start()
        self.restyle()

    def _make(self, prop, duration, curve):
        a = QPropertyAnimation(self, prop, self); a.setDuration(duration); a.setEasingCurve(curve); self._animations[a] = curve; return a

    def _prop(name, default):
        storage = f"_{name}"
        def get(self): return getattr(self, storage)
        def set_(self, value): setattr(self, storage, value); self.update()
        return pyqtProperty(type(default), fget=get, fset=set_)
    tunnel = _prop("tunnel", 0.0); pulse = _prop("pulse", 0.0); orbit = _prop("orbit", 0.0); press = _prop("press", 0.0); companion = _prop("companion", 0.0)
    def _get_tint(self): return self._colour
    def _set_tint(self, value): self._colour = value; self.update()
    tint = pyqtProperty(QColor, fget=_get_tint, fset=_set_tint)

    def _glide(self, anim, start, end, duration=None):
        if anim.state() == QPropertyAnimation.State.Running and anim.endValue() == end: return
        if anim.state() != QPropertyAnimation.State.Running and start == end: return
        anim.stop(); anim.setDuration(duration or anim.duration()); anim.setStartValue(start); anim.setEndValue(end); anim.start()

    def set_state(self, state: State):
        previous, self._state = self._state, state
        target = 1.0 if state is State.ACTIVE else (0.94 if state is State.CONNECTING else 0.0)
        self._glide(self._tunnel_a, self._tunnel, target, max(180, int(abs(target-self._tunnel)*1200)))
        self._glide(self._pulse_a, self._pulse, 1.0 if state in _BUSY else 0.0)
        self._glide(self._tint_a, QColor(self._colour), self._target_colour())
        if state is State.ACTIVE and previous is not State.ACTIVE:
            self._glide(self._pulse_a, self._pulse, 1.0, 400); QTimer.singleShot(500, lambda: self._glide(self._pulse_a, self._pulse, 0.0, 760))

    def set_companion(self, enabled: bool): self._glide(self._companion_a, self._companion, 1.0 if enabled else 0.0)
    def _target_colour(self):
        if self._state is State.ERROR: return QColor(theme.DANGER)
        if self._state is State.ACTIVE or self._state in _BUSY or self._hovered: return QColor(theme.ACCENT)
        return QColor(theme.TEXT_FAINT)
    def restyle(self): self._glide(self._tint_a, QColor(self._colour), self._target_colour())
    def enterEvent(self, e): self._hovered=True; self.restyle(); super().enterEvent(e)
    def leaveEvent(self, e): self._hovered=False; self._glide(self._press_a,self._press,0.0); self.restyle(); super().leaveEvent(e)
    def mousePressEvent(self,e):
        if e.button()==Qt.MouseButton.LeftButton: self._glide(self._press_a,self._press,1.0)
        super().mousePressEvent(e)
    def mouseReleaseEvent(self,e):
        if e.button()==Qt.MouseButton.LeftButton:
            self._glide(self._press_a,self._press,0.0)
            if self.rect().contains(e.pos()): self.clicked.emit()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c=QPointF(self.width()/2,self.height()/2); outer=min(self.width(),self.height())/2-7*self._scale
        p.translate(c); s=1-0.045*self._press; p.scale(s,s); p.translate(-c)
        accent=QColor(self._colour)
        haze=QRadialGradient(c,outer*1.14); h=QColor(accent); h.setAlphaF(0.12+0.20*max(self._tunnel,self._companion)); haze.setColorAt(0.22,h); haze.setColorAt(1.0,QColor(accent.red(),accent.green(),accent.blue(),0)); p.setPen(Qt.PenStyle.NoPen); p.setBrush(haze); p.drawEllipse(c,outer*1.14,outer*1.14)
        p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(QColor(*theme.RING_TRACK),5*self._scale,cap=Qt.PenCapStyle.RoundCap)); p.drawEllipse(c,outer,outer)
        if self._tunnel>0.01:
            start=90-self._orbit*360; grad=QConicalGradient(c,start); dim=QColor(accent); dim.setAlphaF(.26); bright=QColor(accent); bright.setAlphaF(.96); grad.setColorAt(0.0,dim); grad.setColorAt(.72,bright); grad.setColorAt(1.0,bright); p.setPen(QPen(grad,5*self._scale,cap=Qt.PenCapStyle.RoundCap)); p.drawArc(QRectF(c.x()-outer,c.y()-outer,outer*2,outer*2),int(start*16),int(-360*max(.22,self._tunnel)*16))
        self._draw_portal(p,c,outer*.56,accent)
        if self._companion>.01: self._draw_gateway_satellite(p,c,outer,accent)

    def _draw_portal(self,p,c,r,accent):
        left=QPointF(c.x()-r*.48,c.y()+r*.23); right=QPointF(c.x()+r*.48,c.y()-r*.23)
        path=QPainterPath(left); control=QPointF(c.x(),c.y()-r*(.56+.08*math.sin(self._orbit*math.tau))) ; path.quadTo(control,right)
        glow=QColor(accent); glow.setAlphaF(.10+.42*self._tunnel); p.setPen(QPen(glow,13*self._scale,cap=Qt.PenCapStyle.RoundCap)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path)
        edge=QColor(accent); edge.setAlphaF(.42+.55*self._tunnel); p.setPen(QPen(edge,3*self._scale,cap=Qt.PenCapStyle.RoundCap)); p.drawPath(path)
        for point, strength in ((left,.62),(right,1.0)):
            ring=QColor(accent); ring.setAlphaF((.32+.56*self._tunnel)*strength); p.setPen(QPen(ring,3*self._scale)); p.setBrush(QColor(accent.red(),accent.green(),accent.blue(),int(28+56*self._tunnel))); p.drawEllipse(point,r*.22,r*.22)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(255,255,255,int(80+120*self._tunnel))); p.drawEllipse(point,r*.055,r*.055)
        if self._tunnel>.05:
            t=(self._orbit*1.45)%1; x=(1-t)*(1-t)*left.x()+2*(1-t)*t*control.x()+t*t*right.x(); y=(1-t)*(1-t)*left.y()+2*(1-t)*t*control.y()+t*t*right.y(); p.setBrush(QColor(255,255,255,220)); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(QPointF(x,y),3.5*self._scale,3.5*self._scale)

    def _draw_gateway_satellite(self,p,c,outer,accent):
        y=c.y()+outer*.70; w=outer*.42; p.setPen(QPen(QColor(accent.red(),accent.green(),accent.blue(),int(120*self._companion)),1.5*self._scale,cap=Qt.PenCapStyle.RoundCap)); p.drawLine(QPointF(c.x()-w,y),QPointF(c.x()+w,y)); p.setBrush(QColor(accent)); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(QPointF(c.x(),y),4.5*self._scale,4.5*self._scale)
