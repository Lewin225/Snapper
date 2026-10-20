"""Fine-adjust waveform: shows the selection plus a margin, with draggable in/out handles."""
from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .media import RATE

WORD_BAND = 18  # px at the top reserved for word labels
SNAP_PX = 8


class WaveformWidget(QWidget):
    selection_edited = Signal(object, object)  # (in, out) after the user dragged a handle or clicked a word
    seek_requested = Signal(float)

    def __init__(self):
        super().__init__()
        self.samples: Optional[np.ndarray] = None
        self.dur = 0.0
        self.sel_in: Optional[float] = None
        self.sel_out: Optional[float] = None
        self.playhead = 0.0
        self.margin = 3.0
        self.word_source = lambda a, b: []  # (start, end) -> words overlapping that span
        self.snap = True
        self._drag: Optional[str] = None
        self._frozen: Optional[tuple[float, float]] = None
        self._key = None
        self._pm: Optional[QPixmap] = None
        self.gain = 1.0
        self.setMinimumHeight(130)
        self.setMouseTracking(True)

    def set_audio(self, samples: Optional[np.ndarray]):
        self.samples = samples
        self.dur = len(samples) / RATE if samples is not None else 0.0
        self._key = None
        self.update()

    def set_selection(self, a: Optional[float], b: Optional[float]):
        self.sel_in, self.sel_out = a, b
        self.update()

    # --- geometry
    def view(self) -> tuple[float, float]:
        if self._frozen:  # while a handle is dragged the view must not move under the cursor
            return self._frozen
        if self.sel_in is None:
            a, b = self.playhead - self.margin, self.playhead + self.margin
        else:
            a, b = self.sel_in - self.margin, (self.sel_out if self.sel_out is not None else self.sel_in) + self.margin
        a = max(0.0, a)
        return a, min(self.dur, max(b, a + 0.5))

    def _x(self, t, a, b):
        return (t - a) / (b - a) * self.width()

    def _t(self, x, a, b):
        return a + x / max(self.width(), 1) * (b - a)

    # --- painting
    def _render_peaks(self, a, b, w, h):
        pm = QPixmap(w, h)
        pm.fill(QColor(24, 26, 30))
        seg = np.asarray(self.samples[int(a * RATE):int(b * RATE)], dtype=np.float32) / 32768.0
        if len(seg) and w:
            n = min(w, len(seg))
            edges = np.linspace(0, len(seg), n + 1).astype(int)
            mn, mx = np.minimum.reduceat(seg, edges[:-1]), np.maximum.reduceat(seg, edges[:-1])
            self.gain = 0.95 / max(float(np.percentile(np.maximum(-mn, mx), 99.5)), 0.02)  # auto-gain
            mid = (h + WORD_BAND) / 2
            half = (h - WORD_BAND) / 2
            xs = np.arange(n) * w / n
            y0 = mid - np.clip(mx * self.gain, -1, 1) * half
            y1 = mid - np.clip(mn * self.gain, -1, 1) * half
            p = QPainter(pm)
            p.setPen(QPen(QColor(90, 170, 255), 1))
            p.drawLines([QLineF(x, ya, x, yb) for x, ya, yb in zip(xs, y0, y1)])
            p.end()
        return pm

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        if self.samples is None:
            p.fillRect(self.rect(), QColor(24, 26, 30))
            p.setPen(QColor(160, 160, 160))
            p.drawText(self.rect(), Qt.AlignCenter, "Decoding audio…")
            return
        a, b = self.view()
        key = (round(a, 4), round(b, 4), w, h)
        if key != self._key:
            self._pm, self._key = self._render_peaks(a, b, w, h), key
        p.drawPixmap(0, 0, self._pm)

        fm = QFontMetrics(p.font())
        p.setPen(QColor(200, 200, 140))
        for wd in self.word_source(a, b):
            x0, x1 = self._x(wd["start"], a, b), self._x(wd["end"], a, b)
            p.drawLine(QPointF(x0, 0), QPointF(x0, WORD_BAND))
            p.drawText(QRectF(x0 + 2, 0, max(x1 - x0 - 2, 0), WORD_BAND), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(wd["text"], Qt.ElideRight, int(max(x1 - x0 - 4, 0))))

        if self.sel_in is not None:
            xi = self._x(self.sel_in, a, b)
            xo = self._x(self.sel_out, a, b) if self.sel_out is not None else xi
            p.fillRect(QRectF(xi, WORD_BAND, xo - xi, h - WORD_BAND), QColor(255, 200, 0, 40))
            p.setPen(QPen(QColor(80, 255, 120), 2))
            p.drawLine(QPointF(xi, 0), QPointF(xi, h))
            if self.sel_out is not None:
                p.setPen(QPen(QColor(255, 90, 90), 2))
                p.drawLine(QPointF(xo, 0), QPointF(xo, h))
        xp = self._x(self.playhead, a, b)
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.drawLine(QPointF(xp, 0), QPointF(xp, h))
        p.setPen(QColor(150, 150, 150))
        p.drawText(6, h - 6, f"{a:.2f}–{b:.2f}s  {(b - a) / max(w, 1) * 1000:.1f} ms/px  gain x{self.gain:.1f}")

    # --- interaction
    def _snap(self, t, a, b):
        words = self.word_source(a, b) if self.snap else []
        if not words:
            return t
        edges = [e for wd in words for e in (wd["start"], wd["end"])]
        near = min(edges, key=lambda e: abs(e - t))
        return near if abs(self._x(near, a, b) - self._x(t, a, b)) <= SNAP_PX else t

    def mousePressEvent(self, e):
        if self.samples is None:
            return
        a, b = self.view()
        x, y = e.position().x(), e.position().y()
        self._drag = None
        for name, t in (("out", self.sel_out), ("in", self.sel_in)):
            if t is not None and abs(self._x(t, a, b) - x) < SNAP_PX:
                self._drag, self._frozen = name, (a, b)
                return
        if y < WORD_BAND:  # click a word label to select that word
            t = self._t(x, a, b)
            for wd in self.word_source(a, b):
                if wd["start"] <= t <= wd["end"]:
                    self.selection_edited.emit(wd["start"], wd["end"])
                    return
        self.seek_requested.emit(self._t(x, a, b))

    def mouseMoveEvent(self, e):
        if not self._drag:
            return
        a, b = self.view()
        t = self._snap(min(max(self._t(e.position().x(), a, b), 0.0), self.dur), a, b)
        if self._drag == "in":
            self.sel_in = min(t, self.sel_out) if self.sel_out is not None else t
        else:
            self.sel_out = max(t, self.sel_in)
        self.selection_edited.emit(self.sel_in, self.sel_out)
        self.update()

    def mouseReleaseEvent(self, _):
        self._drag = self._frozen = None
        self.update()

    def wheelEvent(self, e):
        self.margin = min(30.0, max(0.05, self.margin * (0.8 if e.angleDelta().y() > 0 else 1.25)))
        self.update()
