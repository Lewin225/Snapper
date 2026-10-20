"""Right-hand panel: completed clips with per-tag filters."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QTableView, QVBoxLayout, QWidget)

from .model import Clip, ClipFilter, ClipTableModel, Project


class ClipsPanel(QWidget):
    clip_selected = Signal(object)   # select to edit
    clip_play = Signal(object)
    clip_delete = Signal(object)
    rename_requested = Signal(str)   # tag type

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
        self.filter_row = QHBoxLayout()
        self.count = QLabel()
        self.play = QPushButton("Play")
        self.delete = QPushButton("Delete")
        for b in (self.play, self.delete):
            b.setFocusPolicy(Qt.NoFocus)
        self.play.clicked.connect(lambda: self.current() and self.clip_play.emit(self.current()))
        self.delete.clicked.connect(lambda: self.current() and self.clip_delete.emit(self.current()))
        foot = QHBoxLayout()
        foot.addWidget(self.count, 1)
        foot.addWidget(self.play)
        foot.addWidget(self.delete)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(self.filter_row)
        lay.addWidget(self.table, 1)
        lay.addLayout(foot)
        project.structure_changed.connect(self.rebuild_filters)
        project.structure_changed.connect(self._update_count)
        self.proxy.layoutChanged.connect(self._update_count)
        self.rebuild_filters()
        self._update_count()

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
