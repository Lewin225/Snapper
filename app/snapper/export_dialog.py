"""The export settings pop-up."""
from __future__ import annotations

from typing import Optional

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
                               QWidget)

from .export import (DEFAULT_TEMPLATE, FORMATS, SAMPLE_RATES, TOKENS, MP3_QUALITIES, WAV_BIT_DEPTHS, WAV_TEXT_FIELDS, ExportSettings,
                     output_dir_problem, plan_files, template_problem)
from .model import Project

FORMAT_LABELS = {"wav": "WAV", "mp3": "MP3"}
TEXT_FIELD_LABELS = {"wav": {"comment": "Comment (ICMT)", "title": "Title (INAM)", "subject": "Subject (ISBJ)"},
                     "mp3": {"comment": "Comment (COMM)", "title": "Title (TIT2)", "subject": "Subtitle (TIT3)"}}
MP3_LABELS = {"320": "320 kbps", "256": "256 kbps", "192": "192 kbps", "160": "160 kbps", "128": "128 kbps",
              "v0": "Variable, best (V0, about 245 kbps)", "v2": "Variable, high (V2, about 190 kbps)",
              "v4": "Variable, good (V4, about 165 kbps)"}
BIT_LABELS = {16: "16-bit", 24: "24-bit", 32: "32-bit float"}


class ExportSettingsDialog(QDialog):
    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("Export settings")
        self.setMinimumWidth(560)
        cur = ExportSettings.from_json(project.export_settings) if project.export_settings else ExportSettings()
        # tags that no longer exist cannot be folders
        cur.folder_tags = [t for t in cur.folder_tags if t in project.tag_kinds]

        self.folder = QLineEdit(cur.output_dir)
        self.folder.setPlaceholderText("Choose where the clips are exported to")
        self.folder.setReadOnly(True)   # picked with the system folder dialog, which is what grants access in a sandbox
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        self.folder_row = QHBoxLayout()
        self.folder_row.addWidget(self.folder, 1)
        self.folder_row.addWidget(browse)
        self.folder_msg = QLabel()
        self.folder_msg.setWordWrap(True)
        self.folder_msg.setStyleSheet("color: #c0392b;")
        self.template = QLineEdit(cur.name_template)
        self.template.setToolTip("Fields: " + ", ".join("{%s}" % t for t in (*TOKENS, *project.tag_types)))
        self.placeholder_box = QWidget()   # explanation, and buttons that insert each placeholder
        self.placeholders = QVBoxLayout(self.placeholder_box)
        self.placeholders.setContentsMargins(0, 0, 0, 0)
        self.placeholders.setSpacing(4)
        self.template_msg = QLabel()
        self.template_msg.setWordWrap(True)
        self.template_msg.setStyleSheet("color: #c0392b;")
        self.example = QLabel()
        self.example.setStyleSheet("color: gray;")
        self.example.setWordWrap(True)
        self.format = QComboBox()
        for f in FORMATS:
            self.format.addItem(FORMAT_LABELS[f], f)
        self.channels = QComboBox()
        self.channels.addItem("Mono", 1)
        self.channels.addItem("Stereo", 2)
        self.channels.setToolTip("Surround sources are mixed down. The clip is cut from the audio track chosen in the "
                                 "main window.")
        self.rate = QComboBox()
        for r in SAMPLE_RATES:
            self.rate.addItem(f"{r} Hz", r)

        # format-specific options: each format shows its own rows (WAV: bit depth; MP3: bitrate / quality)
        self.bits = QComboBox()
        for b in WAV_BIT_DEPTHS:
            self.bits.addItem(BIT_LABELS[b], b)
        self.bits_label = QLabel("Bit depth")
        self.quality = QComboBox()
        for q in MP3_QUALITIES:
            self.quality.addItem(MP3_LABELS[q], q)
        self.quality_label = QLabel("Quality")

        # folders
        self.folder_list = QListWidget()
        self.folder_list.setMaximumHeight(110)
        self.up, self.down = QPushButton("Move up"), QPushButton("Move down")
        self.up.clicked.connect(lambda: self._move(-1))
        self.down.clicked.connect(lambda: self._move(1))
        self.folder_example = QLabel()
        self.folder_example.setStyleSheet("color: gray;")
        self.folder_example.setWordWrap(True)
        fl = QVBoxLayout()
        fl.addWidget(QLabel("Tick the tags to sort clips into folders. The top tag is the first folder, the next one "
                            "its sub-folder, and so on. Clips without a value go in “_none”."))
        fl.itemAt(0).widget().setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self.folder_list, 1)
        buttons = QVBoxLayout()
        buttons.addWidget(self.up)
        buttons.addWidget(self.down)
        buttons.addStretch(1)
        row.addLayout(buttons)
        fl.addLayout(row)
        fl.addWidget(self.folder_example)
        folders = QGroupBox("Folders")
        folders.setLayout(fl)

        # text and tags
        self.text_field = QComboBox()
        self.text_field.addItem("Don't write the text", None)
        for k in WAV_TEXT_FIELDS:
            self.text_field.addItem(TEXT_FIELD_LABELS["wav"][k], k)
        self.embed_tags = QCheckBox("Add the clip's tags to the file")
        self.embed_tags.setToolTip("Written as JSON in a custom 'snpr' chunk of the WAV file.")

        form = QFormLayout()
        form.addRow("Export folder", self.folder_row)
        form.addRow("", self.folder_msg)
        form.addRow("File name", self.template)
        form.addRow("", self.placeholder_box)
        form.addRow("", self.template_msg)
        form.addRow("", self.example)
        form.addRow("Format", self.format)
        form.addRow("Channels", self.channels)
        form.addRow("Sample rate", self.rate)
        form.addRow(self.bits_label, self.bits)
        form.addRow(self.quality_label, self.quality)
        form.addRow("Clip text goes in", self.text_field)
        form.addRow("", self.embed_tags)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        reset = QPushButton("Defaults")
        reset.clicked.connect(lambda: self._load(ExportSettings(output_dir=self.folder.text())))
        self.buttons.addButton(reset, QDialogButtonBox.ResetRole)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(folders)
        lay.addWidget(self.buttons)

        self.template.textChanged.connect(self._refresh)
        self.folder_list.itemChanged.connect(self._refresh)
        self.folder_list.model().rowsMoved.connect(self._refresh)
        self.format.currentIndexChanged.connect(self._format_changed)
        self._build_placeholders()
        self._load(cur)

    def _build_placeholders(self):
        """The file name is a template: explain it, and offer every placeholder as a button that inserts it."""
        while self.placeholders.count():
            item = self.placeholders.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    w = item.layout().takeAt(0).widget()
                    if w:
                        w.deleteLater()
        intro = QLabel("The name is made from <b>placeholders</b> in curly braces, replaced for each clip. "
                       "Click one to insert it at the cursor.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: gray;")
        self.placeholders.addWidget(intro)
        info = [("n", "the clip's number, zero-padded (001, 002, …)"), ("id", "the clip's number, not padded"),
                ("start", "where the clip starts in the episode, in milliseconds"),
                ("text", "the start of the clip's text")]
        info += [(t, f"the clip's “{t}” tag" + (" (Yes / No)" if self.project.tag_kinds[t] == "bool" else ""))
                 for t in self.project.tag_types]
        grid = QGridLayout()
        grid.setSpacing(4)
        legend = QGridLayout()   # one row per placeholder; short lines, so nothing needs wrapping
        legend.setHorizontalSpacing(10)
        legend.setVerticalSpacing(1)
        legend.setColumnStretch(1, 1)
        for i, (name, what) in enumerate(info):
            b = QPushButton("{%s}" % name)
            b.setToolTip(what[0].upper() + what[1:])
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _c=False, n=name: self.template.insert("{%s}" % n))
            grid.addWidget(b, i // 4, i % 4)
            key = QLabel("<b>{%s}</b>" % name)
            desc = QLabel(what)
            desc.setStyleSheet("color: gray;")
            legend.addWidget(key, i, 0)
            legend.addWidget(desc, i, 1)
        self.placeholders.addLayout(grid)
        self.placeholders.addLayout(legend)
        ex = QLabel("Example: <b>{character}_{text}</b> gives <i>Alastor_But, yeah, that might be fun</i> plus the file type. Folders are set separately, below.")
        ex.setWordWrap(True)
        ex.setStyleSheet("color: gray;")
        self.placeholders.addWidget(ex)

    def _browse(self):
        start = self.folder.text() if Path(self.folder.text()).is_dir() else str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Export clips to…", start)
        if chosen:
            self.folder.setText(chosen)
            self._refresh()

    def _format_changed(self, *_):
        fmt = self.format.currentData()
        for w in (self.bits, self.bits_label):
            w.setVisible(fmt == "wav")
        for w in (self.quality, self.quality_label):
            w.setVisible(fmt == "mp3")
        for i in range(1, self.text_field.count()):   # the same three choices, named for the format's own tags
            self.text_field.setItemText(i, TEXT_FIELD_LABELS[fmt][self.text_field.itemData(i)])
        self.embed_tags.setToolTip("Written as JSON in a custom 'snpr' " + (
            "chunk of the WAV file." if fmt == "wav" else "text frame (TXXX) of the MP3's ID3 tag."))
        self._refresh()   # the example file name shows the format's extension

    # --- values
    def _set(self, combo: QComboBox, data):
        combo.setCurrentIndex(max(0, combo.findData(data)))

    def _load(self, s: ExportSettings):
        self.folder.setText(s.output_dir)
        self.template.setText(s.name_template)
        self._set(self.format, s.format)
        self._set(self.channels, s.channels)
        self._set(self.rate, s.sample_rate)
        self._set(self.bits, s.bit_depth)
        self._set(self.quality, s.mp3_quality)
        self._set(self.text_field, s.text_field)
        self.embed_tags.setChecked(s.embed_tags)
        folder_tags = [t for t in s.folder_tags if t in self.project.tag_kinds]
        order = folder_tags + [t for t in self.project.tag_types if t not in folder_tags]
        self.folder_list.blockSignals(True)
        self.folder_list.clear()
        for tag in order:
            item = QListWidgetItem(f"{tag}  ({self.project.tag_kinds[tag]})")
            item.setData(Qt.UserRole, tag)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if tag in folder_tags else Qt.Unchecked)
            self.folder_list.addItem(item)
        self.folder_list.blockSignals(False)
        self.folder_list.setCurrentRow(0)
        self._format_changed()
        self._refresh()

    def _move(self, d: int):
        r = self.folder_list.currentRow()
        if 0 <= r + d < self.folder_list.count():
            item = self.folder_list.takeItem(r)
            self.folder_list.insertItem(r + d, item)
            self.folder_list.setCurrentRow(r + d)
            self._refresh()

    def settings(self) -> ExportSettings:
        tags = [self.folder_list.item(i).data(Qt.UserRole) for i in range(self.folder_list.count())
                if self.folder_list.item(i).checkState() == Qt.Checked]
        return ExportSettings(
            output_dir=self.folder.text(), name_template=self.template.text().strip() or DEFAULT_TEMPLATE, format=self.format.currentData(),
            channels=self.channels.currentData(), sample_rate=self.rate.currentData(),
            bit_depth=self.bits.currentData(), folder_tags=tags, text_field=self.text_field.currentData(),
            embed_tags=self.embed_tags.isChecked(), mp3_quality=self.quality.currentData())

    def _refresh(self, *_):
        s = self.settings()
        problem = template_problem(self.template.text(), self.project.tag_types)
        self.template_msg.setText(problem or "")
        self.template_msg.setVisible(bool(problem))
        folder_problem = output_dir_problem(self.folder.text())
        self.folder_msg.setText(folder_problem or "")
        self.folder_msg.setVisible(bool(folder_problem))
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(problem is None and folder_problem is None)
        if problem is None and self.project.clips:
            c, rel = plan_files(self.project, s, self.project.clips[:1])[0]
            self.example.setText(f"First clip: {rel}")
        else:
            self.example.setText("" if problem else "No clips yet.")
        self.folder_example.setText("Folders: " + (" / ".join(s.folder_tags) if s.folder_tags else "none (one folder)"))
