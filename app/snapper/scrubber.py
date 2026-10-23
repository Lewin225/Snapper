"""A time value that is adjusted by dragging left or right (like a DAW's number field)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QLineEdit, QWidget

from .drag import RelativeDrag

SECONDS_PER_PIXEL = 0.010   # drag sensitivity: 10 ms per pixel...
FINE = 0.001                # ...Ctrl: 1 ms per pixel
COARSE = 0.100              # ...Shift: 100 ms per pixel


def format_time(t: Optional[float]) -> str:
    return "--" if t is None else f"{int(t // 60)}:{t % 60:06.3f}"


def parse_time(text: str) -> Optional[float]:
    """Accepts seconds ('620.4') or minutes:seconds ('10:20.4'); None if it is not a time."""
    text = text.strip()
    try:
        if ":" in text:
            m, s = text.rsplit(":", 1)
            return int(m) * 60 + float(s)
        return float(text)
    except ValueError:
        return None


class _InlineEdit(QLineEdit):
    """Typed entry shown over the scrubber on double-click. Esc cancels, Enter/click-away applies."""

    def __init__(self, parent):
        super().__init__(parent)
        self.cancelled = False

    def cancel_edit(self):  # called by the window's key filter before it takes focus away on Esc
        self.cancelled = True


class TimeScrubber(QWidget):
    changed = Signal(float)   # the user changed the value (dragging or typing)
    dragging = Signal(bool)

    def __init__(self, caption: str):
        super().__init__()
        self.caption = caption
        self._value: Optional[float] = None
        self._lo, self._hi = 0.0, 1e9
        self._drag_x: Optional[float] = None
        self._acc = 0.0
        self.relative = RelativeDrag(self)   # endless dragging: the pointer is held in place while dragging
        self._hover = False
        self._edit: Optional[_InlineEdit] = None
        self.setFixedSize(132, 54)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)
        self.setToolTip(f"{caption}: drag left/right to adjust (Shift = coarse, Ctrl = 1 ms steps). "
                        f"Double-click to type a time.")

    # --- value
    def value(self) -> Optional[float]:
        return self._value

    def set_value(self, v: Optional[float]):
        self._value = v
        self.setEnabled(v is not None)
        self.update()

    def set_limits(self, lo: float, hi: float):
        self._lo, self._hi = lo, hi

    def _apply(self, v: float):
        v = min(max(v, self._lo), self._hi)
        if self._value is None or abs(v - self._value) >= 0.0005:
            self._value = v
            self.update()
            self.changed.emit(v)

    # --- painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isEnabled()
        pal = self.palette()
        dim = QColor(pal.color(pal.ColorRole.WindowText))
        dim.setAlpha(150)
        p.setPen(dim)
        small = QFont(self.font())
        small.setPointSizeF(self.font().pointSizeF() * 0.85)
        p.setFont(small)
        p.drawText(QRectF(2, 0, self.width() - 4, 16), Qt.AlignLeft | Qt.AlignVCenter, self.caption)
        box = QRectF(0.5, 18.5, self.width() - 1, self.height() - 19)
        border = pal.color(pal.ColorRole.Highlight) if (self._hover or self._drag_x is not None) and on \
            else pal.color(pal.ColorRole.Mid)
        p.setPen(QPen(border, 1))
        p.setBrush(pal.color(pal.ColorRole.Base) if on else pal.color(pal.ColorRole.Window))
        p.drawRoundedRect(box, 4, 4)
        big = QFont("monospace")
        big.setStyleHint(QFont.Monospace)
        big.setPointSizeF(self.font().pointSizeF() * 1.2)
        p.setFont(big)
        p.setPen(pal.color(pal.ColorRole.Text) if on else pal.color(pal.ColorGroup.Disabled, pal.ColorRole.Text))
        p.drawText(box, Qt.AlignCenter, format_time(self._value))
        if on:  # drag hints
            p.setPen(dim)
            p.drawText(box.adjusted(6, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, "◂")
            p.drawText(box.adjusted(0, 0, -6, 0), Qt.AlignRight | Qt.AlignVCenter, "▸")

    def enterEvent(self, _):
        self._hover = True
        self.update()

    def leaveEvent(self, _):
        self._hover = False
        self.update()

    # --- dragging
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._value is not None and self._edit is None:
            self._drag_x = e.position().x()
            self._acc = 0.0
            self.relative.start(e.globalPosition())   # the pointer is hidden and held in place: drag as far as you like
            self.dragging.emit(True)
            self.update()

    def mouseMoveEvent(self, e):
        if not self.relative.active:
            self.setCursor(Qt.SizeHorCursor if self._value is not None else Qt.ArrowCursor)
        if self._drag_x is None or self._value is None:
            return
        dx = self.relative.step(e.globalPosition())[0]
        mods = e.modifiers()
        rate = COARSE if mods & Qt.ShiftModifier else FINE if mods & Qt.ControlModifier else SECONDS_PER_PIXEL
        self._acc += dx * rate
        step = round(self._acc, 6)
        if abs(step) >= 0.0005:   # keep sub-millisecond remainders so slow drags are not lost
            self._acc -= step
            self._apply(self._value + step)

    def mouseReleaseEvent(self, _):
        self.relative.finish()
        if self._drag_x is not None:
            self._drag_x = None
            self.dragging.emit(False)
            self.update()

    # --- typing
    def mouseDoubleClickEvent(self, _):
        if self._value is None or self._edit is not None:
            return
        self.relative.finish()
        self._drag_x = None
        ed = _InlineEdit(self)
        self._edit = ed
        ed.setText(format_time(self._value))
        ed.setGeometry(0, 18, self.width(), self.height() - 18)
        ed.setAlignment(Qt.AlignCenter)
        ed.editingFinished.connect(lambda ed=ed: self._finish_edit(ed))
        ed.show()
        ed.setFocus()
        ed.selectAll()

    def _finish_edit(self, ed: _InlineEdit):
        if ed is not self._edit:  # a stale editor losing focus must not close the current one
            return
        self._edit = None
        v = None if ed.cancelled else parse_time(ed.text())
        ed.deleteLater()
        if v is not None:
            self._apply(v)
