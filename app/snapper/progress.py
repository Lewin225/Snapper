"""Progress display: one labelled bar per running background job (status bar), and the proxy banner above the video."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget

JOB_NAMES = {"proxy": "Scrub proxy", "audio": "Decoding audio", "transcript": "Transcribing", "isolation": "Isolating vocals",
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
    """A labelled bar for every running job, in the status bar."""

    def __init__(self):
        super().__init__()
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(14)
        self._rows: dict[str, tuple[QWidget, QProgressBar]] = {}

    def update_jobs(self, state: dict[str, Optional[float]]):
        for name in [n for n in self._rows if n not in state]:
            self._rows.pop(name)[0].deleteLater()
        for name, fraction in state.items():
            if name not in self._rows:
                row = QWidget()
                lay = QHBoxLayout(row)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setSpacing(6)
                lay.addWidget(QLabel(JOB_NAMES.get(name, name)))
                bar = make_bar()
                lay.addWidget(bar)
                self._lay.addWidget(row)
                self._rows[name] = (row, bar)
            set_fraction(self._rows[name][1], fraction)


class ProxyBanner(QLabel):
    """A slim strip above the video explaining why scrubbing is slow while the proxy is being made."""

    def __init__(self):
        super().__init__()
        self.setContentsMargins(10, 4, 10, 4)
        self.setStyleSheet("background: #ffe9a8; color: #4d3b00; border-radius: 3px;")
        self._hide = QTimer(self, singleShot=True, interval=4000, timeout=self.hide)
        self.hide()

    def generating(self, fraction: Optional[float]):
        self._hide.stop()
        self.setStyleSheet("background: #ffe9a8; color: #4d3b00; border-radius: 3px;")
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
