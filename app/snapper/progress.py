"""Progress display: one labelled bar per running background job (status bar), and the proxy banner above the video."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QEasingCurve, QPropertyAnimation, Property, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy, QWidget

WARN_BG, WARN_FG = "#ffe9a8", "#4d3b00"   # the proxy banner's amber; also the pulse behind background work in the status bar

JOB_NAMES = {"proxy": "Scrub proxy", "audio": "Decoding audio", "transcript": "Transcribing", "isolation": "Processing audio",
             "subtitles": "Reading subtitles",
             "pcm": "Preparing audio", "export": "Exporting"}


def make_bar(width: int = 110) -> QProgressBar:
    bar = QProgressBar()
    bar.setFixedWidth(width)
    bar.setFixedHeight(14)
    bar.setTextVisible(True)
    return bar


def set_fraction(bar: QProgressBar, fraction: Optional[float]):
    """None shows a busy (indeterminate) bar."""
    if fraction is None:
        bar.setRange(0, 0)
    else:
        bar.setRange(0, 100)
        bar.setValue(int(fraction * 100))


class JobBars(QWidget):
    """A labelled bar for every running job (packed together, left to right) and a button to cancel all background
    work, on a pill that pulses in the proxy banner's amber while anything runs. Empty (and invisible) otherwise."""
    cancel_requested = Signal()

    def __init__(self):
        super().__init__()
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(10, 2, 8, 2)
        self._lay.setSpacing(14)
        self._rows: dict[str, tuple[QWidget, QProgressBar]] = {}
        self._level = 1.0
        self._anim = QPropertyAnimation(self, b"level", self, duration=1800, loopCount=-1,
                                        easingCurve=QEasingCurve.InOutSine)
        self._anim.setKeyValueAt(0.0, 0.35)
        self._anim.setKeyValueAt(0.5, 1.0)
        self._anim.setKeyValueAt(1.0, 0.35)
        self.setStyleSheet(f"QLabel, QPushButton {{ color: {WARN_FG}; }}")
        self._cancel = QPushButton("✕ Cancel background work")
        self._cancel.setFocusPolicy(Qt.NoFocus)
        self._cancel.setFlat(True)
        self._cancel.setCursor(Qt.PointingHandCursor)
        self._cancel.setToolTip("Stops everything running in the background (proxy, decoding, transcription, isolation, exports)")
        self._cancel.clicked.connect(self.cancel_requested)
        self._lay.addWidget(self._cancel)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self._cancel.hide()

    def _get_level(self) -> float:
        return self._level

    def _set_level(self, v: float):
        self._level = v
        self.update()

    level = Property(float, _get_level, _set_level)

    def paintEvent(self, _e):
        if not self._rows:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(WARN_BG)
        c.setAlphaF(self._level)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(self.rect(), 4, 4)

    def update_jobs(self, state: dict[str, Optional[float]]):
        busy = bool(state)
        self._cancel.setVisible(busy)
        if busy and self._anim.state() != QPropertyAnimation.Running:
            self._anim.start()
        elif not busy:
            self._anim.stop()
        for name in [n for n in self._rows if n not in state]:
            self._rows.pop(name)[0].deleteLater()
        for name, fraction in state.items():
            if name not in self._rows:
                row = QWidget()
                row.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                lay = QHBoxLayout(row)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setSpacing(6)
                lay.addWidget(QLabel(JOB_NAMES.get(name, name)))
                bar = make_bar()
                lay.addWidget(bar)
                self._lay.insertWidget(self._lay.count() - 1, row)   # before the cancel button
                self._rows[name] = (row, bar)
            set_fraction(self._rows[name][1], fraction)
        self.update()


class ProxyBanner(QLabel):
    """A slim strip above the video explaining why scrubbing is slow while the proxy is being made."""

    def __init__(self):
        super().__init__()
        self.setContentsMargins(10, 4, 10, 4)
        self.setStyleSheet(f"background: {WARN_BG}; color: {WARN_FG}; border-radius: 3px;")
        self._hide = QTimer(self, singleShot=True, interval=4000, timeout=self.hide)
        self.hide()

    def generating(self, fraction: Optional[float]):
        self._hide.stop()
        self.setStyleSheet(f"background: {WARN_BG}; color: {WARN_FG}; border-radius: 3px;")
        pct = "" if fraction is None else f" {fraction * 100:.0f}%"
        self.setText(f"Generating scrub proxy…{pct}  Scrubbing is slow until it finishes (playing the original video).")
        self.show()

    def ready(self):
        self.setStyleSheet("background: #c9efd2; color: #1b4d2a; border-radius: 3px;")
        self.setText("Scrub proxy ready: scrubbing is now fast.")
        self.show()
        self._hide.start()

    def clear(self):
        self._hide.stop()
        self.hide()
