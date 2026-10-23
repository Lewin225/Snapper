"""Current-clip editor: waveform with handles, start/end, tags, text, and the save/clear buttons."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRegularExpression, Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from .model import BOOL, INT, STRING, Clip, Project
from .pathnames import INVALID_HELP, VALID_INPUT_PATTERN, clean_tag
from .titles import section_title
from .scrubber import TimeScrubber
from .waveform import WaveformWidget

MIN_LENGTH = 0.010  # shortest clip the Length field can make
INT_UNSET = -10000  # the spin box minimum: shown as an empty value, meaning the tag is not set on the clip

SAVE_STYLE = """
QPushButton { background: palette(highlight); color: palette(highlighted-text); font-weight: bold;
              padding: 6px 18px; border-radius: 4px; border: 1px solid palette(highlight); }
QPushButton:hover { border: 1px solid palette(text); }
QPushButton:disabled { background: palette(button); color: palette(mid); border: 1px solid palette(mid); }
"""


class ClipEditor(QWidget):
    edited = Signal()                    # the user changed something about the current clip
    range_edited = Signal(object, object)  # (start, end) after a start/end value was dragged or typed
    preview_requested = Signal(float)    # a marker is being dragged: show that moment in the video
    save_requested = Signal()
    deselect_requested = Signal()
    source_requested = Signal(str)       # the user chose "original" or "isolated" audio for this clip

    def __init__(self, project: Project):
        super().__init__()
        self.project = project
        self.clip: Clip = Clip()
        self._loading = False
        self.tag_boxes: dict[str, QComboBox] = {}
        self.int_boxes: dict[str, QSpinBox] = {}
        self.bool_boxes: dict[str, QCheckBox] = {}

        self.wave = WaveformWidget()
        self.status = section_title("Clip Editor")   # the pane title, followed by what is being edited
        self.scrub_in = TimeScrubber("Start")
        self.scrub_out = TimeScrubber("End")
        self.scrub_len = TimeScrubber("Length")
        self.scrub_len.setToolTip("Length: drag left/right to grow or shrink the clip from both ends at once "
                                  "(Shift = coarse, Ctrl = 1 ms steps). Double-click to type a length.")
        self.snap = QCheckBox("Snap to words")
        self.snap.setChecked(True)
        self.snap.setFocusPolicy(Qt.NoFocus)
        self.snap.toggled.connect(lambda v: setattr(self.wave, "snap", v))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Transcript text for this clip")
        self.text.setTabChangesFocus(True)
        self.text.setFixedHeight(self.text.fontMetrics().lineSpacing() * 2 + 16)  # room for two lines
        self.text.textChanged.connect(self._text_changed)
        self.play_btn = QPushButton("▶ Play Clip (P)")
        self.deselect_btn = QPushButton("Deselect clip (Esc)")
        self.deselect_btn.setToolTip("Stop working on this clip. A new clip's markers are cleared; a saved clip keeps "
                                     "its timings.")
        self.save_btn = QPushButton("Save to Library (Enter)")
        self.save_btn.setStyleSheet(SAVE_STYLE)
        for b in (self.play_btn, self.deselect_btn, self.save_btn):
            b.setFocusPolicy(Qt.NoFocus)
        self.deselect_btn.clicked.connect(self.deselect_requested)
        self.save_btn.clicked.connect(self.save_requested)
        self.source_btns = {"original": QPushButton("Original"), "isolated": QPushButton("Isolated")}
        self.source_group = QButtonGroup(self)
        self.source_group.setExclusive(True)
        for name, b in self.source_btns.items():
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            self.source_group.addButton(b)
            b.clicked.connect(lambda _c=False, name=name: self.source_requested.emit(name))
        self.source_btns["original"].setChecked(True)
        self.show_source("original", False)
        self.hint = QLabel()
        self.hint.setStyleSheet("color: gray;")
        self.hint.setWordWrap(True)

        self.scrub_in.changed.connect(lambda v: self._marker_changed("in", v))
        self.scrub_out.changed.connect(lambda v: self._marker_changed("out", v))
        self.scrub_len.changed.connect(self._length_changed)

        marks = QHBoxLayout()
        marks.setSpacing(12)
        left = QVBoxLayout()           # clip buttons, to the left of the Start/End values
        left.setSpacing(6)
        clip_buttons = QHBoxLayout()
        clip_buttons.setSpacing(8)
        clip_buttons.addWidget(self.play_btn)
        clip_buttons.addWidget(self.deselect_btn)
        left.addLayout(clip_buttons)
        source_row = QHBoxLayout()     # which audio the clip is cut from (and heard and exported)
        source_row.setSpacing(0)
        source_row.addWidget(QLabel("Audio  "))
        source_row.addWidget(self.source_btns["original"])
        source_row.addWidget(self.source_btns["isolated"])
        source_row.addStretch(1)
        left.addLayout(source_row)
        marks.addLayout(left)
        marks.addStretch(1)
        marks.addWidget(self.scrub_in)
        marks.addWidget(self.scrub_out)
        marks.addWidget(self.scrub_len)
        marks.addSpacing(8)
        marks.addWidget(self.snap, 0, Qt.AlignBottom)
        self.tag_row = QHBoxLayout()
        self.tag_row.setSpacing(8)
        text_row = QHBoxLayout()
        text_row.setSpacing(8)
        text_row.addWidget(QLabel("Text"))
        text_row.addWidget(self.text, 1)
        self.save_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)  # as tall as the text box beside it
        text_row.addWidget(self.save_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(10)
        lay.addWidget(self.status)
        lay.addWidget(self.wave, 1)
        lay.addLayout(marks)
        lay.addLayout(self.tag_row)
        lay.addLayout(text_row)
        lay.addWidget(self.hint)
        self.rebuild()

    # --- structure
    def rebuild(self):
        """(Re)creates the tag controls from the project; keeps current values."""
        while self.tag_row.count():
            w = self.tag_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.tag_boxes.clear()
        self.int_boxes.clear()
        self.bool_boxes.clear()
        for t in self.project.tag_types:
            kind = self.project.tag_kinds.get(t, STRING)
            if kind == BOOL:
                cb = QCheckBox(t)
                cb.setFocusPolicy(Qt.NoFocus)
                cb.toggled.connect(lambda _v, t=t: self._tag_edited(t))
                self.bool_boxes[t] = cb
                self.tag_row.addWidget(cb)
                continue
            self.tag_row.addWidget(QLabel(t.capitalize()))
            if kind == INT:
                sp = QSpinBox()
                sp.setRange(INT_UNSET, 99999)
                sp.setSpecialValueText(" ")
                sp.setValue(INT_UNSET)
                sp.setMinimumWidth(80)
                sp.setFocusPolicy(Qt.ClickFocus)
                sp.valueChanged.connect(lambda _v, t=t: self._tag_edited(t))
                self.int_boxes[t] = sp
                self.tag_row.addWidget(sp)
            else:
                box = QComboBox()
                box.setEditable(True)
                box.setInsertPolicy(QComboBox.NoInsert)
                box.setMinimumWidth(150)
                box.setFocusPolicy(Qt.ClickFocus)
                # tag values become folder names on export, so characters a path can't hold are not accepted
                box.lineEdit().setValidator(QRegularExpressionValidator(QRegularExpression(VALID_INPUT_PATTERN)))
                box.setToolTip(INVALID_HELP)
                box.activated.connect(lambda _i, t=t: self._tag_edited(t))
                box.lineEdit().editingFinished.connect(lambda t=t: self._tag_edited(t))
                self.tag_boxes[t] = box
                self.tag_row.addWidget(box)
            self.tag_row.addSpacing(8)
        self.tag_row.addStretch(1)
        self.refresh_values()
        self.load_clip(self.clip)

    def refresh_values(self):
        for t, box in self.tag_boxes.items():
            cur = box.currentText()
            box.blockSignals(True)
            box.clear()
            box.addItems(self.project.values(t))
            box.setCurrentText(cur)
            box.blockSignals(False)
        first = self.project.first_string_tag()
        chars = self.project.values(first) if first else []
        keys = "  ".join(f"{i + 1}={v}" for i, v in enumerate(chars[:9]))
        self.hint.setText("I/O set start/end · drag the Start/End values to fine-tune · Enter save · "
                          "Space play/pause · S stop · Esc deselect" + (f" · {keys}" if keys else ""))

    # --- loading / reading the current clip
    def load_clip(self, clip: Clip):
        self.clip = clip
        self._loading = True
        self.wave.set_selection(clip.start, clip.end)
        self.text.setPlainText(clip.text)
        for t, box in self.tag_boxes.items():
            box.setCurrentText(clip.tags.get(t, ""))
        for t, sp in self.int_boxes.items():
            sp.setValue(clip.tags.get(t, INT_UNSET))
        for t, cb in self.bool_boxes.items():
            cb.setChecked(bool(clip.tags.get(t)))
        self._loading = False
        self.update_info()

    def update_info(self):
        c = self.clip
        total = self.wave.dur or 1e9
        self.scrub_in.set_value(c.start)
        self.scrub_out.set_value(c.end)
        self.scrub_in.set_limits(0.0, c.end if c.end is not None else total)
        self.scrub_out.set_limits(c.start if c.start is not None else 0.0, total)
        both = c.start is not None and c.end is not None
        self.scrub_len.set_value(c.duration if both else None)
        self.scrub_len.set_limits(MIN_LENGTH, total)
        if c.id is not None:
            self._set_status("Editing a saved clip")
            self.save_btn.setText("Done (Enter)")
        else:
            self._set_status("New clip" if c.start is not None else "No selection")
            self.save_btn.setText("Save to Library (Enter)")
        self.save_btn.setEnabled(c.start is not None and c.end is not None)
        self.deselect_btn.setEnabled(c.start is not None or c.id is not None)

    def show_source(self, source: str, available: bool):
        """Shows which audio the clip uses; `available` says whether isolated audio exists for this episode."""
        for name, b in self.source_btns.items():
            b.setChecked(name == source)
        iso = self.source_btns["isolated"]
        if source == "isolated" and not available:
            iso.setToolTip("This clip uses isolated audio, but it is no longer there. It plays and exports the original "
                           "until you isolate the vocals again (Audio menu).")
            iso.setStyleSheet("color: palette(link);")
        else:
            iso.setToolTip("Only the dialogue, with music and effects removed (V switches)." if available else
                           "No isolated audio yet. Click to isolate the vocals with audio-separator.")
            iso.setStyleSheet("")
        self.source_btns["original"].setToolTip("The episode's own audio (V switches).")

    def _set_status(self, what: str):
        self.status.setText(f"Clip Editor — {what}")

    def set_range(self, a: Optional[float], b: Optional[float], text: Optional[str] = None):
        self.clip.start, self.clip.end = a, b
        if text is not None and self.clip.text_auto:
            self.clip.text = text
            self._loading = True
            self.text.setPlainText(text)
            self._loading = False
        self.wave.set_selection(a, b)
        self.update_info()
        self.edited.emit()

    def set_tag(self, tag: str, value: str):
        self.clip.tags[tag] = value
        if tag in self.tag_boxes:
            self.tag_boxes[tag].setCurrentText(value)
        self.edited.emit()

    # --- user edits
    def _marker_changed(self, which: str, v: float):
        c = self.clip
        self.range_edited.emit(v, c.end) if which == "in" else self.range_edited.emit(c.start, v)
        self.preview_requested.emit(v)

    def _length_changed(self, length: float):
        """The clip grows or shrinks around its centre; at the start or end of the episode it slides to stay inside."""
        c = self.clip
        if c.start is None or c.end is None:
            return
        total = self.wave.dur or 1e9
        mid = (c.start + c.end) / 2
        a, b = mid - length / 2, mid + length / 2
        if a < 0:
            a, b = 0.0, min(b - a, total)
        elif b > total:
            a, b = max(a - (b - total), 0.0), total
        self.range_edited.emit(a, b)

    def _text_changed(self):
        if self._loading:
            return
        self.clip.text, self.clip.text_auto = self.text.toPlainText().replace("\n", " "), False
        self.edited.emit()

    def _tag_edited(self, tag: str):
        if self._loading:
            return
        if tag in self.bool_boxes:
            v = True if self.bool_boxes[tag].isChecked() else None
        elif tag in self.int_boxes:
            n = self.int_boxes[tag].value()
            v = None if n == INT_UNSET else n
        else:
            box = self.tag_boxes[tag]
            v = clean_tag(box.currentText()) or None   # also trims trailing dots/spaces, which paths dislike
            if (v or "") != box.currentText():
                box.setCurrentText(v or "")
        if v is not None:
            self.clip.tags[tag] = v
        else:
            self.clip.tags.pop(tag, None)
        self.edited.emit()
