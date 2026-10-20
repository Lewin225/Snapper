"""What Snapper shows when it is started without a file: recent projects, and buttons to open a video or a project."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton,
                               QVBoxLayout, QWidget)

from . import launcher, media, recent


class StartWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Snapper")
        self.resize(640, 480)
        self.opened = None   # the main window opened from here (tests look at it)
        title = QLabel("Snapper")
        title.setStyleSheet("font-size: 22pt; font-weight: bold;")
        sub = QLabel("Cut, tag and export dialogue from an episode.")
        sub.setStyleSheet("color: gray;")
        self.btn_video = QPushButton("Open video…")
        self.btn_project = QPushButton("Open project…")
        self.btn_video.setDefault(True)
        self.btn_video.clicked.connect(self.open_video_dialog)
        self.btn_project.clicked.connect(self.open_project_dialog)
        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        self.list.setStyleSheet("QListWidget::item { padding: 6px 4px; }")
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.itemActivated.connect(lambda it: self.open_recent(it))
        self.empty = QLabel("No recent projects yet.\nOpen a video to start one.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color: gray;")
        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_video)
        buttons.addWidget(self.btn_project)
        buttons.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addSpacing(8)
        lay.addLayout(buttons)
        lay.addSpacing(8)
        lay.addWidget(QLabel("Recent projects"))
        lay.addWidget(self.list, 1)
        lay.addWidget(self.empty, 1)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for e in recent.entries():
            when = time.strftime("%d %b %Y %H:%M", time.localtime(e.modified))
            item = QListWidgetItem(f"{e.video}\n{e.clips} clip{'s' if e.clips != 1 else ''} · saved {when}")
            item.setData(Qt.UserRole, str(e.path))
            item.setToolTip(str(e.path))
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.list.setVisible(self.list.count() > 0)
        self.empty.setVisible(self.list.count() == 0)

    # --- opening
    def open_recent(self, item: QListWidgetItem):
        self._open(Path(item.data(Qt.UserRole)))

    def open_video_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open video", str(Path.home()), launcher.VIDEO_FILTER)
        if path:
            self._open(Path(path))

    def open_project_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open project", str(media.projects_dir()), launcher.PROJECT_FILTER)
        if path:
            self._open(Path(path))

    def _open(self, path: Path):
        win = launcher.open_path(path, self)
        if win is not None:
            self.opened = win
            self.close()   # the main window is already open, so closing this one does not end the app

    def _context_menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        menu.addAction("Open", lambda: self.open_recent(item))
        menu.addAction("Remove from list", lambda: (recent.remove(Path(item.data(Qt.UserRole))), self.refresh()))
        menu.exec(self.list.viewport().mapToGlobal(pos))
