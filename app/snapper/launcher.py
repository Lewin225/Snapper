"""Opening things: a video (asking whether to resume its project) or a project file. Used by the command line, the
start screen and the File menu, so they all behave the same."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QMessageBox, QWidget

from . import media, recent
from .model import Project

PROJECT_SUFFIX = ".snapper.json"
VIDEO_FILTER = "Video files (*.mp4 *.mkv *.mov *.m4v *.avi *.webm *.ts);;All files (*)"
PROJECT_FILTER = "Snapper projects (*.snapper.json)"


def is_project(path: Path) -> bool:
    return path.name.endswith(PROJECT_SUFFIX)


def existing_project_for(video: Path) -> Optional[Path]:
    """The project Snapper already has for this video, if any (the app's own folder, or a file an early build left
    next to the video)."""
    for p in (Project.default_path(video), video.with_name(video.name + PROJECT_SUFFIX)):
        if p.exists():
            return p
    return None


def ask_resume(parent: Optional[QWidget], video: Path, info: recent.RecentProject) -> Optional[str]:
    """'resume', 'fresh' or None (cancel). A separate function so tests can answer it."""
    box = QMessageBox(QMessageBox.Question, "Resume project?",
                      f"{video.name} already has a project ({info.clips} clip{'s' if info.clips != 1 else ''}, last "
                      f"saved {time.strftime('%d %b %Y %H:%M', time.localtime(info.modified))}).", parent=parent)
    box.setInformativeText("Starting fresh keeps the old project as a backup file next to it; nothing is deleted.")
    resume = box.addButton("Resume project", QMessageBox.AcceptRole)
    fresh = box.addButton("Start fresh", QMessageBox.DestructiveRole)
    box.addButton(QMessageBox.Cancel)
    box.setDefaultButton(resume)
    box.exec()
    return "resume" if box.clickedButton() is resume else "fresh" if box.clickedButton() is fresh else None


def back_up(project_file: Path) -> Path:
    """Sets a project file aside (it no longer ends in .snapper.json, so it is neither opened nor listed)."""
    backup = project_file.with_name(f"{project_file.name}.{time.strftime('%Y%m%d-%H%M%S')}.bak")
    os.replace(project_file, backup)
    return backup


def open_path(path: Path, parent: Optional[QWidget] = None):
    """Opens a project file, or a video (asking whether to resume its project if it has one), in a new main window.
    Returns the window, or None if the user cancelled or it could not be opened."""
    from .main_window import MainWindow   # imported here: main_window imports this module
    try:
        if not is_project(path):
            if not path.is_file():
                raise FileNotFoundError(f"File not found: {path}")
            existing = existing_project_for(path)
            if existing is not None:
                info = recent.describe(existing)
                answer = ask_resume(parent, path, info) if info is not None else "resume"
                if answer is None:
                    return None
                if answer == "fresh":
                    back_up(existing)
        win = MainWindow(path)
    except Exception as e:   # unreadable file, video that cannot be found, not a video...
        QMessageBox.warning(parent, "Open", str(e))
        return None
    recent.add(win.project.path)
    if os.environ.get("SNAPPER_SIZE"):   # e.g. 1500x950, for checking the layout at a given window size
        w, h = os.environ["SNAPPER_SIZE"].split("x")
        win.resize(int(w), int(h))
    win.show()
    return win
