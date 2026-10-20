"""Right-hand panel: completed clips with per-tag filters."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton,
                               QTableView, QVBoxLayout, QWidget)

from . import desktop
from .editor import SAVE_STYLE
from .titles import section_title
from .model import Clip, ClipFilter, ClipTableModel, Project


class ClipsPanel(QWidget):
    clip_selected = Signal(object)   # select to edit
    clip_play = Signal(object)
    clip_delete = Signal(object)
    clip_duplicate = Signal(object)
    rename_requested = Signal(str)   # tag type
    export_requested = Signal()
    export_settings_requested = Signal()
    auto_export_toggled = Signal(bool)

    def __init__(self, project: Project):
        super().__init__()
        self.project = project
        self.model = ClipTableModel(project)
        self.proxy = ClipFilter(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.clicked.connect(lambda ix: self.clip_selected.emit(self._clip(ix)))
        self.table.doubleClicked.connect(lambda ix: self.clip_play.emit(self._clip(ix)))
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.filter_row = QHBoxLayout()
        self.count = QLabel()
        self.play = QPushButton("Play")
        self.delete = QPushButton("Delete")
        for b in (self.play, self.delete):
            b.setFocusPolicy(Qt.NoFocus)
        self.play.clicked.connect(lambda: self.current() and self.clip_play.emit(self.current()))
        self.delete.clicked.connect(lambda: self.current() and self.clip_delete.emit(self.current()))
        self.export_btn = QPushButton("Export")
        self.export_btn.setStyleSheet(SAVE_STYLE)
        self.export_settings_btn = QPushButton("Export Settings…")
        for b in (self.export_btn, self.export_settings_btn):
            b.setFocusPolicy(Qt.NoFocus)
        self.export_btn.clicked.connect(self.export_requested)
        self.export_settings_btn.clicked.connect(self.export_settings_requested)
        self.auto_export = QCheckBox("Auto export")
        self.auto_export.setFocusPolicy(Qt.NoFocus)
        self.auto_export.setChecked(project.auto_export)
        self.auto_export.toggled.connect(self.auto_export_toggled)
        self.set_export_enabled(False, "")
        head = QHBoxLayout()
        head.addWidget(self.count, 1)
        head.addWidget(self.auto_export)
        foot = QHBoxLayout()   # every library button on one row
        foot.setSpacing(6)
        foot.addWidget(self.play)
        foot.addWidget(self.delete)
        foot.addStretch(1)
        foot.addWidget(self.export_settings_btn)
        foot.addWidget(self.export_btn)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 14, 0)   # space under the menu bar; the same 8 px gap from the video as the transcript has, 14 px off the right edge
        lay.addWidget(section_title("Library"))
        lay.addLayout(self.filter_row)
        lay.addWidget(self.table, 1)
        lay.addLayout(head)
        lay.addLayout(foot)
        lay.addSpacing(8)
        project.structure_changed.connect(self.rebuild_filters)
        project.structure_changed.connect(self._update_count)
        self.proxy.layoutChanged.connect(self._update_count)
        self.rebuild_filters()
        self._update_count()

    def _context_menu(self, pos):
        ix = self.table.indexAt(pos)
        if not ix.isValid():
            return
        self.build_context_menu(self._clip(ix)).exec(self.table.viewport().mapToGlobal(pos))

    def build_context_menu(self, clip: Clip) -> QMenu:
        exported = Path(clip.export_path) if clip.export_path else None
        has_file = exported is not None and exported.exists()
        menu = QMenu(self)
        menu.addAction("Duplicate", lambda: self.clip_duplicate.emit(clip))
        menu.addAction("Delete", lambda: self.clip_delete.emit(clip))
        menu.addSeparator()
        folder = menu.addAction("Open containing folder", lambda: desktop.show_in_folder(exported))
        app = menu.addAction("Open in system app", lambda: desktop.open_file(exported))
        for a in (folder, app):
            a.setEnabled(has_file)
            if not has_file:
                a.setToolTip("This clip has not been exported yet." if exported is None else "The exported file is gone.")
        menu.setToolTipsVisible(True)
        return menu

    def set_export_enabled(self, enabled: bool, tip: str, can_auto: bool = False, auto_tip: str = ""):
        """Export is the primary action, available once the project has export settings (and clips). Auto export
        needs working export settings but not clips."""
        self.export_btn.setEnabled(enabled)
        self.export_btn.setToolTip(tip)
        self.auto_export.setEnabled(can_auto or self.auto_export.isChecked())
        self.auto_export.setToolTip(auto_tip)

    def _clip(self, proxy_index) -> Clip:
        return self.model.clip_at(self.proxy.mapToSource(proxy_index).row())

    def current(self):
        ix = self.table.currentIndex()
        return self._clip(ix) if ix.isValid() else None

    def select(self, clip):
        """Highlight a clip's row without emitting (None clears)."""
        self.table.blockSignals(True)
        if clip is None or clip not in self.project.clips:
            self.table.clearSelection()
            self.table.setCurrentIndex(self.table.model().index(-1, -1))
        else:
            ix = self.proxy.mapFromSource(self.model.index(self.project.clips.index(clip), 0))
            if ix.isValid():
                self.table.selectRow(ix.row())
                self.table.scrollTo(ix)
        self.table.blockSignals(False)

    def rebuild_filters(self):
        """One 'All / value…' dropdown per tag type, keeping any active choice."""
        while self.filter_row.count():
            w = self.filter_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        for t in self.project.tag_types:
            box = QComboBox()
            box.setFocusPolicy(Qt.NoFocus)
            box.addItem(f"All {t}" if self.project.tag_kinds.get(t) != "string" else f"All {t}s", "")
            for v in self.project.filter_values(t):
                box.addItem(v, v)
            want = self.proxy.filters.get(t, "")
            box.setCurrentIndex(max(0, box.findData(want)))
            box.currentIndexChanged.connect(lambda _i, t=t, box=box: self.proxy.set_filter(t, box.currentData()))
            ren = QPushButton("✎")
            ren.setFixedWidth(28)
            ren.setToolTip(f"Rename a {t} everywhere")
            ren.setFocusPolicy(Qt.NoFocus)
            ren.clicked.connect(lambda _c=False, t=t: self.rename_requested.emit(t))
            self.filter_row.addWidget(box, 1)
            if self.project.tag_kinds.get(t) == "string":   # only text values can be renamed
                self.filter_row.addWidget(ren)
            else:
                ren.deleteLater()
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setStretchLastSection(False)
        text_col = self.model.columns().index("Text")
        hdr.setSectionResizeMode(text_col, QHeaderView.Stretch)

    def _update_count(self, *_):
        self.count.setText(f"{self.proxy.rowCount()} of {len(self.project.clips)} clips")
