"""The export settings pop-up."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)

from .export import (DEFAULT_TEMPLATE, FORMATS, SAMPLE_RATES, TOKENS, WAV_BIT_DEPTHS, WAV_TEXT_FIELDS, ExportSettings,
                     plan_files, template_problem)
from .model import Project

FORMAT_LABELS = {"wav": "WAV"}
TEXT_FIELD_LABELS = {"comment": "Comment (ICMT)", "title": "Title (INAM)", "subject": "Subject (ISBJ)"}
BIT_LABELS = {16: "16-bit", 24: "24-bit", 32: "32-bit float"}


class ExportSettingsDialog(QDialog):
    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("Export settings")
        self.setMinimumWidth(520)
        cur = ExportSettings.from_json(project.export_settings) if project.export_settings else ExportSettings()
        # tags that no longer exist cannot be folders
        cur.folder_tags = [t for t in cur.folder_tags if t in project.tag_kinds]

        self.template = QLineEdit(cur.name_template)
        self.template.setToolTip("Fields: " + ", ".join("{%s}" % t for t in (*TOKENS, *project.tag_types)))
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

        # format-specific options: each format shows its own rows (WAV: bit depth; MP3 will add bitrate / quality)
        self.bits = QComboBox()
        for b in WAV_BIT_DEPTHS:
            self.bits.addItem(BIT_LABELS[b], b)
        self.bits_label = QLabel("Bit depth")

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
            self.text_field.addItem(TEXT_FIELD_LABELS[k], k)
        self.embed_tags = QCheckBox("Add the clip's tags to the file")
        self.embed_tags.setToolTip("Written as JSON in a custom 'snpr' chunk of the WAV file.")

        form = QFormLayout()
        form.addRow("File name", self.template)
        form.addRow("", self.template_msg)
        form.addRow("", self.example)
        form.addRow("Format", self.format)
        form.addRow("Channels", self.channels)
        form.addRow("Sample rate", self.rate)
        form.addRow(self.bits_label, self.bits)
        form.addRow("Clip text goes in", self.text_field)
        form.addRow("", self.embed_tags)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        reset = QPushButton("Defaults")
        reset.clicked.connect(lambda: self._load(ExportSettings()))
        self.buttons.addButton(reset, QDialogButtonBox.ResetRole)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(folders)
        lay.addWidget(self.buttons)

        self.template.textChanged.connect(self._refresh)
        self.folder_list.itemChanged.connect(self._refresh)
        self.folder_list.model().rowsMoved.connect(self._refresh)
        self.format.currentIndexChanged.connect(self._format_changed)
        self._load(cur)

    def _format_changed(self, *_):
        wav = self.format.currentData() == "wav"
        self.bits.setVisible(wav)
        self.bits_label.setVisible(wav)

    # --- values
    def _set(self, combo: QComboBox, data):
        combo.setCurrentIndex(max(0, combo.findData(data)))

    def _load(self, s: ExportSettings):
        self.template.setText(s.name_template)
        self._set(self.format, s.format)
        self._set(self.channels, s.channels)
        self._set(self.rate, s.sample_rate)
        self._set(self.bits, s.bit_depth)
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
            name_template=self.template.text().strip() or DEFAULT_TEMPLATE, format=self.format.currentData(),
            channels=self.channels.currentData(), sample_rate=self.rate.currentData(),
            bit_depth=self.bits.currentData(), folder_tags=tags, text_field=self.text_field.currentData(),
            embed_tags=self.embed_tags.isChecked())

    def _refresh(self, *_):
        s = self.settings()
        problem = template_problem(self.template.text(), self.project.tag_types)
        self.template_msg.setText(problem or "")
        self.template_msg.setVisible(bool(problem))
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(problem is None)
        if problem is None and self.project.clips:
            c, rel = plan_files(self.project, s, self.project.clips[:1])[0]
            self.example.setText(f"First clip: {rel}")
        else:
            self.example.setText("" if problem else "No clips yet.")
        self.folder_example.setText("Folders: " + (" / ".join(s.folder_tags) if s.folder_tags else "none (one folder)"))
