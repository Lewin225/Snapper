"""Transcript data, subtitle fallback, the WhisperX background job and the transcript panel."""
from __future__ import annotations

import bisect
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QProcess, Qt, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QLabel, QLineEdit, QMenu, QProgressBar, QPushButton, QStackedLayout,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

SPEECH_BACKEND_DIR = Path(__file__).resolve().parents[2] / "speech_backend"
WX_PYTHON = os.environ.get("SNAPPER_WX_PYTHON", os.path.expanduser("~/envs/wx/bin/python"))


class Transcript:
    """Lines are dicts: {start, end, text, speaker, words: [{text, start, end}]} (words may be empty)."""

    def __init__(self, lines: Optional[list[dict]] = None):
        self.lines: list[dict] = sorted(lines or [], key=lambda l: l["start"])
        self._starts = [l["start"] for l in self.lines]

    def extend(self, new: list[dict]):
        self.lines = sorted(self.lines + new, key=lambda l: l["start"])
        self._starts = [l["start"] for l in self.lines]

    def index_at(self, t: float) -> int:
        """Line containing t, else the last line starting before t, else -1."""
        i = bisect.bisect_right(self._starts, t) - 1
        return i

    def text_for(self, a: float, b: float) -> str:
        """Words (or, without word times, whole lines) whose centre falls inside [a, b]."""
        out = []
        for l in self.lines:
            if l["end"] < a or l["start"] > b:
                continue
            words = [w for w in l.get("words", []) if w.get("start") is not None]
            if words:
                out += [w["text"] for w in words if a <= (w["start"] + w["end"]) / 2 <= b]
            elif a <= (l["start"] + l["end"]) / 2 <= b or (l["start"] >= a and l["end"] <= b):
                out.append(l["text"])
        return " ".join(out).strip()

    def words_between(self, a: float, b: float) -> list[dict]:
        return [w for l in self.lines for w in l.get("words", [])
                if w.get("start") is not None and w["end"] >= a and w["start"] <= b]

    def save(self, path: Path):
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.lines))
        os.replace(tmp, path)

    @staticmethod
    def load(path: Path) -> "Transcript":
        return Transcript(json.loads(path.read_text()))


def parse_srt(text: str) -> list[dict]:
    """Line-level only: subtitle timings are not trusted, and there are no word times."""
    lines = []
    for blk in re.split(r"\n\s*\n", text.replace("\r", "").strip()):
        parts = blk.split("\n")
        m = next((re.match(r"(\d+):(\d+):(\d+)[,.](\d+) --> (\d+):(\d+):(\d+)[,.](\d+)", p) for p in parts
                  if "-->" in p), None)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start, end = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        body = " ".join(parts[parts.index(m.string) + 1:]) if m.string in parts else ""
        body = re.sub(r"<[^>]+>|\{\\[^}]*\}", "", body)
        body = re.sub(r"^\s*-\s*", "", body).strip()
        if not body or re.fullmatch(r"\[.*\]|\(.*\)|♪.*", body):
            continue  # empty, sound cues and music notes
        lines.append({"start": start, "end": end, "text": body, "speaker": None, "words": []})
    return lines


class TranscriptJob(QObject):
    """Runs the WhisperX worker as a subprocess; results arrive one window at a time."""
    lines_ready = Signal(list)
    progress = Signal(float)
    done = Signal(bool, str)

    def __init__(self, media: Path, audio_track: int = 0, parent=None):
        super().__init__(parent)
        self._buf = b""
        self._err = b""
        self._saw_done = False
        self._proc = QProcess(self)
        self._proc.setProgram(WX_PYTHON)
        self._proc.setArguments(["-u", str(SPEECH_BACKEND_DIR / "transcribe_worker.py"), str(media),
                                 "--audio-stream", str(audio_track)])
        self._proc.readyReadStandardOutput.connect(self._read)
        self._proc.readyReadStandardError.connect(lambda: setattr(self, "_err", self._err[-4000:] +
                                                                  bytes(self._proc.readAllStandardError())))
        self._proc.finished.connect(self._finished)
        self._proc.errorOccurred.connect(
            lambda e: self.done.emit(False, f"could not start {WX_PYTHON}") if e == QProcess.FailedToStart else None)

    def start(self):
        self._proc.start()

    def kill(self):
        self._proc.kill()

    def _read(self):
        self._buf += bytes(self._proc.readAllStandardOutput())
        *complete, self._buf = self._buf.split(b"\n")
        for raw in complete:
            if not raw.startswith(b"@@"):
                continue
            msg = json.loads(raw[2:])
            if msg.get("done"):
                self._saw_done = True
            else:
                self.lines_ready.emit(msg["lines"])
                self.progress.emit(msg["progress"])

    def _finished(self, code, _status):
        ok = code == 0 and self._saw_done
        self.done.emit(ok, "" if ok else self._err.decode(errors="replace")[-600:] or f"worker exited with {code}")


class TranscriptPanel(QTableWidget):
    """One row per transcript line: start time in its own column so wrapped text never disturbs the timestamps.
    Row number == line index, also while a search filter hides rows."""
    line_selected = Signal(int)

    def __init__(self):
        super().__init__(0, 2)
        self.setWordWrap(True)
        self.setShowGrid(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.horizontalHeader().hide()
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.transcript = Transcript()
        self._follow = -1
        self._fit = QTimer(self)
        self._fit.setSingleShot(True)
        self._fit.setInterval(60)
        self._fit.timeout.connect(self.resizeRowsToContents)
        self.cellClicked.connect(lambda r, _c: self.line_selected.emit(r))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit.start()  # wrapped text changes height with the width; refit once resizing settles

    def set_transcript(self, tr: Transcript):
        self.transcript = tr
        self.setUpdatesEnabled(False)
        self.clearContents()
        self.setRowCount(len(tr.lines))
        for i, l in enumerate(tr.lines):
            t = QTableWidgetItem(f"{int(l['start'] // 60)}:{l['start'] % 60:04.1f}")
            t.setForeground(Qt.gray)
            t.setTextAlignment(Qt.AlignRight | Qt.AlignTop)
            self.setItem(i, 0, t)
            self.setItem(i, 1, QTableWidgetItem(l["text"]))
        self.resizeRowsToContents()
        self.setUpdatesEnabled(True)
        self._follow = -1

    def filter(self, text: str):
        """Shows only the lines containing `text` (case-insensitive); empty shows all."""
        needle = text.strip().lower()
        for i, l in enumerate(self.transcript.lines):
            self.setRowHidden(i, bool(needle) and needle not in l["text"].lower())

    def follow(self, t: float, scroll: bool = True):
        """Highlights the line at `t`; scrolls it to the centre only when `scroll` (during playback)."""
        i = self.transcript.index_at(t)
        if i != self._follow and 0 <= i < self.rowCount():
            self._follow = i
            self.blockSignals(True)
            self.setAutoScroll(scroll)  # moving the current row would otherwise scroll it into view by itself
            self.setCurrentCell(i, 1)
            self.setAutoScroll(True)
            if scroll:
                self.scrollToItem(self.item(i, 1), QAbstractItemView.PositionAtCenter)
            self.blockSignals(False)


class TranscriptArea(QWidget):
    """The transcript list, or - while there is no transcript - buttons for getting one."""
    generate_requested = Signal()
    subtitles_requested = Signal(int)   # embedded subtitle track (0-based, file order)
    file_requested = Signal()

    def __init__(self, panel: TranscriptPanel):
        super().__init__()
        self.panel = panel
        self.tracks: list[tuple[int, str]] = []  # (track, label) of the usable subtitle tracks
        self.message = QLabel("No transcript yet")
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignCenter)
        self.btn_generate = QPushButton("Generate using\nWhisperX")
        self.btn_video = QPushButton("Load from video ▾")
        self.btn_file = QPushButton("Load .srt file…")
        for b in (self.btn_generate, self.btn_video, self.btn_file):
            b.setFocusPolicy(Qt.NoFocus)
        self.btn_generate.clicked.connect(self.generate_requested)
        self.btn_video.clicked.connect(self._video_clicked)
        self.btn_file.clicked.connect(self.file_requested)
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addStretch(1)
        self.bar_empty = QProgressBar()      # progress while there are no lines to show yet
        self.bar_empty.hide()
        for w in (self.message, self.bar_empty, self.btn_generate, self.btn_video, self.btn_file):
            lay.addWidget(w)
        lay.addStretch(2)
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search transcript…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(panel.filter)
        listing = QWidget()
        ll = QVBoxLayout(listing)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)
        self.busy_label = QLabel()           # progress strip above the list while lines are still arriving
        self.busy_label.setStyleSheet("color: #9fc4f0;")
        self.busy_label.setWordWrap(True)
        self.bar_list = QProgressBar()
        self.bar_list.setFixedHeight(12)
        self.busy_label.hide()
        self.bar_list.hide()
        ll.addWidget(self.busy_label)
        ll.addWidget(self.bar_list)
        ll.addWidget(self.search)
        ll.addWidget(panel, 1)
        self._stack.addWidget(page)
        self._stack.addWidget(listing)
        self.set_tracks([])

    def set_tracks(self, tracks: list[tuple[int, str]]):
        self.tracks = tracks
        self.btn_video.setEnabled(bool(tracks))
        self.btn_video.setToolTip("" if tracks else "This file has no text subtitle tracks")

    def _video_clicked(self):
        if len(self.tracks) == 1:
            self.subtitles_requested.emit(self.tracks[0][0])
            return
        menu = QMenu(self)
        for order, label in self.tracks:
            menu.addAction(label, lambda o=order: self.subtitles_requested.emit(o))
        menu.exec(self.btn_video.mapToGlobal(self.btn_video.rect().bottomLeft()))

    def set_busy(self, text: Optional[str], fraction: Optional[float] = None):
        """Shows progress while a transcript is being generated: a bar in place of the buttons, or above the list
        once the first lines have arrived. `text` None ends it."""
        busy = text is not None
        pct = "" if fraction is None else f" {fraction * 100:.0f}%"
        self.message.setText(f"{text}{pct}" if busy else "No transcript yet")
        self.busy_label.setText(f"{text}{pct}  New lines appear as they are found." if busy else "")
        for bar in (self.bar_empty, self.bar_list):
            bar.setVisible(busy)
            if busy:
                if fraction is None:
                    bar.setRange(0, 0)
                else:
                    bar.setRange(0, 100)
                    bar.setValue(int(fraction * 100))
        self.busy_label.setVisible(busy)
        for b in (self.btn_generate, self.btn_video, self.btn_file):
            b.setEnabled(not busy and (b is not self.btn_video or bool(self.tracks)))

    def refresh(self):
        self._stack.setCurrentIndex(1 if self.panel.rowCount() else 0)
        self.panel.filter(self.search.text())   # new lines arrive while a search is typed: keep it applied
