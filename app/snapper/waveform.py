"""Fine-adjust waveform: shows the selection plus a margin, with draggable in/out handles. It has no background of its
own (the window shows through). The original audio is always drawn; the isolated audio, once there (or as far as it
has got while it is still being made), is drawn over it in a second colour on the same scale."""
from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .media import RATE

WORD_BAND = 18  # px at the top reserved for word labels
SNAP_PX = 8
DRAG_PX = 4            # a press that moves less than this is a click
SELECT_HOLD_MS = 250   # hold the right button this long before dragging selects a clip (a quick slip never clears a clip)


class WaveformWidget(QWidget):
    selection_edited = Signal(object, object)  # (in, out) after the user dragged a handle or clicked a word
    seek_requested = Signal(float)
    scrub_requested = Signal(float)   # the playhead is being dragged: show this moment (latest wins), the exact seek follows

    def __init__(self):
        super().__init__()
        self.samples: Optional[np.ndarray] = None
        self.iso_samples: Optional[np.ndarray] = None   # the isolated audio, same rate and timeline as `samples`
        self.iso_upto: Optional[float] = None           # how far (seconds) it is usable while still being made; None = all of it
        self.show_iso = False                           # draw it over the original
        self._iso_version = 0
        self.dur = 0.0
        self.sel_in: Optional[float] = None
        self.sel_out: Optional[float] = None
        self.playhead = 0.0
        self.margin = 3.0
        self.word_source = lambda a, b: []  # (start, end) -> words overlapping that span
        self.snap = True
        self._drag: Optional[str] = None
        self.view_offset = 0.0              # seconds the view is panned away from the selection (left-drag with a clip selected)
        self._pan: Optional[dict] = None    # a left press that may turn into a drag
        self._rsel: Optional[dict] = None   # a right press: waiting for the hold, then selecting
        self._hold = QTimer(self, singleShot=True, interval=SELECT_HOLD_MS, timeout=self._hold_elapsed)
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

    def set_isolated(self, samples: Optional[np.ndarray], upto: Optional[float] = None):
        """The isolated audio to overlay. While it is still being made `samples` is filled in progressively and `upto` says
        how many seconds of it are done."""
        self.iso_samples, self.iso_upto = samples, upto
        self._iso_version += 1
        self.update()

    def set_show_isolated(self, on: bool):
        if on != self.show_iso:
            self.show_iso = on
            self.update()

    def set_selection(self, a: Optional[float], b: Optional[float]):
        if a is None or self.sel_in is None or b is None or self.sel_out is None or b < self.sel_in or a > self.sel_out:
            self.view_offset = 0.0   # no clip, a new one, or a different one: the view goes back to it
        self.sel_in, self.sel_out = a, b
        self.update()

    def set_playhead(self, t: float):
        """The playback position. While the playhead is being dragged the drag decides where it is."""
        if self._pan and self._pan["moved"] and self._pan["follow"]:
            return
        self.playhead = t

    # --- geometry
    def view(self) -> tuple[float, float]:
        if self._frozen:  # while a handle is dragged the view must not move under the cursor
            return self._frozen
        if self.sel_in is None:
            a, b = self.playhead - self.margin, self.playhead + self.margin
        else:
            a, b = self.sel_in - self.margin, (self.sel_out if self.sel_out is not None else self.sel_in) + self.margin
        a = max(0.0, a)
        b = min(self.dur, max(b, a + 0.5))
        off = max(-a, min(self.dur - b, self.view_offset))   # panned, but never past either end of the episode
        return a + off, b + off

    def _x(self, t, a, b):
        return (t - a) / (b - a) * self.width()

    def _t(self, x, a, b):
        return a + x / max(self.width(), 1) * (b - a)

    # --- painting
    def _dim(self) -> QColor:
        c = QColor(self.palette().color(QPalette.Text))
        c.setAlpha(150)
        return c

    def changeEvent(self, e):
        if e.type() == QEvent.PaletteChange:   # the cached peak image holds the old colours
            self._key = None
            self.update()
        super().changeEvent(e)

    def iso_color(self) -> QColor:
        c = self.palette().color(QPalette.Link)
        hi = self.palette().color(QPalette.Highlight)
        if abs(c.hue() - hi.hue()) < 25 and abs(c.lightness() - hi.lightness()) < 60:   # must stand out from the original's colour
            c = QColor(255, 150, 0)
        return c

    def _lines(self, seg: np.ndarray, w: int, h: int, color: QColor, gain: float, total: int):
        """Peak lines (min..max per pixel column) for `seg`, which is the first part of a view `total` samples long."""
        n = min(int(w * len(seg) / total), len(seg))   # a partly finished overlay covers only part of the width
        if n < 1:
            return None, gain
        edges = np.linspace(0, len(seg), n + 1).astype(int)
        mn, mx = np.minimum.reduceat(seg, edges[:-1]), np.maximum.reduceat(seg, edges[:-1])
        if gain <= 0:   # the original sets the scale; the isolated audio shares it, so what was removed shows
            gain = 0.95 / max(float(np.percentile(np.maximum(-mn, mx), 99.5)), 0.02)   # auto-gain
        mid, half = (h + WORD_BAND) / 2, (h - WORD_BAND) / 2
        xs = np.arange(n) * (w * len(seg) / total) / n
        y0 = mid - np.clip(mx * gain, -1, 1) * half
        y1 = mid - np.clip(mn * gain, -1, 1) * half
        return [QLineF(x, ya, x, yb) for x, ya, yb in zip(xs, y0, y1)], gain

    def _render_peaks(self, a, b, w, h):
        pm = QPixmap(w, h)
        pm.fill(Qt.transparent)
        seg = np.asarray(self.samples[int(a * RATE):int(b * RATE)], dtype=np.float32) / 32768.0
        if not (len(seg) and w):
            return pm
        iso = None
        if self.show_iso and self.iso_samples is not None:
            hi = int(b * RATE) if self.iso_upto is None else min(int(b * RATE), int(self.iso_upto * RATE))
            lo = int(a * RATE)
            if hi > lo:   # the part of this view that is isolated so far
                iso = np.asarray(self.iso_samples[lo:hi], dtype=np.float32) / 32768.0
        p = QPainter(pm)
        base = QColor(self.palette().color(QPalette.Highlight))
        if iso is not None:
            base.setAlpha(110)   # the original steps back so the isolated audio stands out
        lines, self.gain = self._lines(seg, w, h, base, 0.0, len(seg))
        if lines:
            p.setPen(QPen(base, 1))
            p.drawLines(lines)
        if iso is not None:
            lines, _ = self._lines(iso, w, h, self.iso_color(), self.gain, len(seg))
            if lines:
                p.setPen(QPen(self.iso_color(), 1))
                p.drawLines(lines)
        p.end()
        return pm

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        if self.samples is None:
            p.setPen(self._dim())
            p.drawText(self.rect(), Qt.AlignCenter, "Decoding audio…")
            return
        a, b = self.view()
        key = (round(a, 4), round(b, 4), w, h, self.show_iso, self._iso_version)
        if key != self._key:
            self._pm, self._key = self._render_peaks(a, b, w, h), key
        p.drawPixmap(0, 0, self._pm)

        fm = QFontMetrics(p.font())
        text, mid = self.palette().color(QPalette.Text), self.palette().color(QPalette.Mid)
        for wd in self.word_source(a, b):
            x0, x1 = self._x(wd["start"], a, b), self._x(wd["end"], a, b)
            p.setPen(mid)
            p.drawLine(QPointF(x0, 0), QPointF(x0, WORD_BAND))
            p.setPen(text)
            p.drawText(QRectF(x0 + 2, 0, max(x1 - x0 - 2, 0), WORD_BAND), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(wd["text"], Qt.ElideRight, int(max(x1 - x0 - 4, 0))))

        if self.sel_in is not None:
            xi = self._x(self.sel_in, a, b)
            xo = self._x(self.sel_out, a, b) if self.sel_out is not None else xi
            tint = QColor(text)
            tint.setAlpha(45)   # lightens or darkens the selection, whatever the theme
            p.fillRect(QRectF(xi, WORD_BAND, xo - xi, h - WORD_BAND), tint)
            p.setPen(QPen(QColor(80, 255, 120), 2))
            p.drawLine(QPointF(xi, 0), QPointF(xi, h))
            if self.sel_out is not None:
                p.setPen(QPen(QColor(255, 90, 90), 2))
                p.drawLine(QPointF(xo, 0), QPointF(xo, h))
        xp = self._x(self.playhead, a, b)
        p.setPen(QPen(text, 1))
        p.drawLine(QPointF(xp, 0), QPointF(xp, h))
        p.setPen(self._dim())
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
        if e.button() == Qt.RightButton:   # hold, then drag: select a clip
            self._rsel = {"x0": x, "t0": self._t(x, a, b), "view": (a, b), "state": "wait"}
            self._hold.start()
            return
        if e.button() != Qt.LeftButton:
            return
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
        # a click moves the playhead; a drag pans: it scrubs while no clip is selected (the view follows the playhead) and
        # offsets the view while one is
        self._pan = {"x0": x, "t0": self._t(x, a, b), "playhead0": self.playhead, "off0": self.view_offset,
                     "spp": (b - a) / max(self.width(), 1), "moved": False, "follow": self.sel_in is None}

    def _hold_elapsed(self):
        if self._rsel and self._rsel["state"] == "wait":
            self._rsel["state"] = "armed"
            self.setCursor(Qt.CrossCursor)

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if self._rsel:
            r = self._rsel
            if abs(x - r["x0"]) >= DRAG_PX:
                if r["state"] == "wait":
                    r["state"] = "cancelled"   # moved before the hold was up: not a selection
                    self._hold.stop()
                elif r["state"] == "armed":
                    r["state"] = "select"
                    self._frozen = r["view"]
                if r["state"] == "select":
                    a, b = self._frozen
                    t = self._snap(min(max(self._t(x, a, b), 0.0), self.dur), a, b)
                    t0 = self._snap(r["t0"], a, b)
                    self.selection_edited.emit(min(t0, t), max(t0, t))
                    self.update()
            return
        if self._pan:
            p = self._pan
            dx = x - p["x0"]
            if not p["moved"]:
                if abs(dx) < DRAG_PX:
                    return
                p["moved"] = True
                self.setCursor(Qt.ClosedHandCursor)
            if p["follow"]:
                self.playhead = min(max(p["playhead0"] - dx * p["spp"], 0.0), self.dur)
                self.scrub_requested.emit(self.playhead)
            else:
                self.view_offset = p["off0"] - dx * p["spp"]
            self.update()
            return
        if not self._drag:
            return
        a, b = self.view()
        t = self._snap(min(max(self._t(x, a, b), 0.0), self.dur), a, b)
        if self._drag == "in":
            self.sel_in = min(t, self.sel_out) if self.sel_out is not None else t
        else:
            self.sel_out = max(t, self.sel_in)
        self.selection_edited.emit(self.sel_in, self.sel_out)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._rsel and e.button() == Qt.RightButton:
            self._hold.stop()
            self._rsel = None
        elif self._pan and e.button() == Qt.LeftButton:
            p, self._pan = self._pan, None
            if not p["moved"]:
                self.seek_requested.emit(p["t0"])   # a click
            elif p["follow"]:
                self.seek_requested.emit(self.playhead)   # the exact moment where the drag ended
        self.unsetCursor()
        self._drag = self._frozen = None
        self.update()

    def wheelEvent(self, e):
        self.margin = min(30.0, max(0.05, self.margin * (0.8 if e.angleDelta().y() > 0 else 1.25)))
        self.update()
