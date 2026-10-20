"""The recent-projects list shown on the start screen and in File > Open recent. Only paths are kept (in the app's
settings); everything shown about a project is read from its file."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings

MAX_RECENT = 15


@dataclass
class RecentProject:
    path: Path
    video: str        # the video's file name
    clips: int
    modified: float   # when the project file was last written


def _paths() -> list[str]:
    v = QSettings("snapper", "snapper").value("recent", [])
    return [v] if isinstance(v, str) else list(v or [])


def add(project_path: Path):
    """Moves a project to the top of the list."""
    p = str(project_path.resolve())
    paths = [p] + [q for q in _paths() if q != p]
    QSettings("snapper", "snapper").setValue("recent", paths[:MAX_RECENT])


def remove(project_path: Path):
    p = str(project_path.resolve())
    QSettings("snapper", "snapper").setValue("recent", [q for q in _paths() if q != p])


def describe(path: Path) -> RecentProject | None:
    """What the list shows about a project file, or None if it is missing or unreadable."""
    try:
        d = json.loads(path.read_text())
        return RecentProject(path, Path(d.get("video", "")).name or path.name, len(d.get("clips", [])),
                             os.stat(path).st_mtime)
    except (OSError, ValueError, AttributeError):
        return None


def entries() -> list[RecentProject]:
    """Recent projects that still exist, most recently opened first."""
    found = (describe(Path(p)) for p in _paths())
    return [e for e in found if e is not None]
