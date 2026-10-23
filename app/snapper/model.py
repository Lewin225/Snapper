"""Clips, tags and the project file (saved next to the episode as <episode>.snapper.json)."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor

from . import media as media_cache
from .pathnames import INVALID_HELP, clean_tag

INVALID_HELP_TEXT = INVALID_HELP + " (names are used for folders and files)."

STRING, INT, BOOL = "string", "int", "bool"
KINDS = (STRING, INT, BOOL)


@dataclass
class Clip:
    start: Optional[float] = None
    end: Optional[float] = None
    text: str = ""
    text_auto: bool = True  # text follows the transcript until the user edits it
    tags: dict[str, Any] = field(default_factory=dict)  # string -> str, int -> int, bool -> True (absent = off)
    id: Optional[int] = None
    export_sig: Optional[str] = None   # what was last exported for this clip (see export.export_signature) ...
    export_path: Optional[str] = None  # ... and where the file went
    source: str = "original"           # which audio the clip is cut from: "original", or "isolated" (dialogue only)

    @property
    def duration(self) -> float:
        return (self.end - self.start) if self.start is not None and self.end is not None else 0.0

    def to_json(self) -> dict:
        return {"id": self.id, "start": self.start, "end": self.end, "text": self.text,
                "text_auto": self.text_auto, "tags": self.tags,
                "export_sig": self.export_sig, "export_path": self.export_path, "source": self.source}

    @staticmethod
    def from_json(d: dict) -> "Clip":
        return Clip(d["start"], d["end"], d.get("text", ""), d.get("text_auto", True),
                    dict(d.get("tags", {})), d["id"], d.get("export_sig"), d.get("export_path"),
                    d.get("source", "original"))


class Project(QObject):
    structure_changed = Signal()      # clips added/removed/reordered, or tag types changed
    clip_changed = Signal(object)     # one clip edited in place
    dirty = Signal()                  # anything that needs saving
    value_renamed = Signal(str, str, str)  # tag, old, new

    def __init__(self, media: Path, path: Optional[Path] = None):
        """A project for `media`. Without `path` it lives in the app's projects folder, one per video file; the
        project file records the video's path, so it can also be opened directly (see `from_file`)."""
        super().__init__()
        self.media = media
        self.path = path or self.default_path(media)
        self.tag_types: list[str] = ["character"]
        self.tag_kinds: dict[str, str] = {"character": STRING}
        self.tag_values: dict[str, list[str]] = {}  # first-seen order, so number-key shortcuts stay stable
        self.clips: list[Clip] = []
        self.audio_track = 0                         # which audio track of the episode is being cut
        self.auto_export = False                     # export clips as soon as they are created or changed
        self.proxy_enabled = True                    # use (and generate) the fast-scrubbing proxy video
        self.selected_clip: Optional[int] = None     # id of the clip open in the editor, if any
        self.position = 0.0                          # where the playhead was when the project was last saved
        self.pending: Optional[dict] = None          # the clip being cut but not saved yet (start/end/text/tags), if any
        self.before_save = None                      # called just before saving, so the window can fill in the two above
        self.transcript_source: Optional[str] = None
        self.transcript: Optional[list[dict]] = None  # the transcript lines (with word times), kept with the project
        self.export_settings: Optional[dict] = None   # see export.ExportSettings; None until the user sets it up
        self._next_id = 1
        legacy = media.with_name(media.name + ".snapper.json")  # early builds saved next to the video
        if self.path.exists():
            self._load()
        elif path is None and legacy.exists():
            self._load(legacy)

    @staticmethod
    def default_path(media: Path) -> Path:
        key = hashlib.sha1(str(media.resolve()).encode()).hexdigest()[:8]
        return media_cache.projects_dir() / f"{media.stem}-{key}.snapper.json"

    @classmethod
    def from_file(cls, path: Path) -> "Project":
        """Opens a project file; `media` is the video it points to (it may no longer exist: check)."""
        d = json.loads(path.read_text())
        video = Path(d.get("video", ""))
        rel = d.get("video_rel")
        if not video.exists() and rel and (path.parent / rel).exists():
            video = (path.parent / rel).resolve()
        return cls(video, path)

    def set_media(self, media: Path):
        """Points the project at the video's new location (after the user found it again)."""
        self.media = media
        self.dirty.emit()

    # --- persistence
    def _load(self, path: Optional[Path] = None):
        d = json.loads((path or self.path).read_text())
        self.tag_types = d.get("tag_types", self.tag_types)
        self.tag_kinds = {t: d.get("tag_kinds", {}).get(t, STRING) for t in self.tag_types}
        self.tag_values = d.get("tag_values", {})
        self.audio_track = d.get("audio_track", 0)
        self.proxy_enabled = d.get("proxy_enabled", True)
        self.auto_export = bool(d.get("auto_export", False))
        self.selected_clip = d.get("selected_clip")
        self.position = float(d.get("position") or 0.0)
        self.pending = d.get("pending")
        self.transcript = d.get("transcript")
        self.transcript_source = d.get("transcript_source")   # "whisperx:original" / "whisperx:processed", else not WhisperX
        self.export_settings = d.get("export_settings")
        self.clips = [Clip.from_json(c) for c in d.get("clips", [])]
        self._next_id = d.get("next_id", max((c.id for c in self.clips), default=0) + 1)
        for c, raw in zip(self.clips, d.get("clips", [])):   # older files kept flags apart from tags
            for f in raw.get("flags", []):
                if f not in self.tag_kinds:
                    self.tag_types.append(f)
                    self.tag_kinds[f] = BOOL
                c.tags[f] = True

    def save(self):
        if self.before_save:
            self.before_save()
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            rel = os.path.relpath(self.media.resolve(), self.path.resolve().parent)
        except ValueError:  # another drive on Windows
            rel = None
        tmp.write_text(json.dumps({
            "version": 2, "video": str(self.media.resolve()), "video_rel": rel, "proxy_enabled": self.proxy_enabled,
            "auto_export": self.auto_export,
            "audio_track": self.audio_track, "selected_clip": self.selected_clip,
            "position": round(self.position, 3), "pending": self.pending,
            "tag_types": self.tag_types, "tag_kinds": self.tag_kinds, "tag_values": self.tag_values,
            "next_id": self._next_id, "clips": [c.to_json() for c in self.clips],
            "transcript": self.transcript, "transcript_source": self.transcript_source, "export_settings": self.export_settings}, indent=1))
        os.replace(tmp, self.path)

    def save_as(self, path: Path):
        self.path = path
        self.save()

    def set_transcript(self, lines: list[dict], source: Optional[str] = None):
        """`source` says where the lines came from: "whisperx:original" or "whisperx:processed" for a WhisperX run on that
        audio, None for subtitles."""
        self.transcript = lines
        self.transcript_source = source
        self.dirty.emit()

    def set_export_settings(self, settings: dict):
        self.export_settings = settings
        self.dirty.emit()

    def select(self, clip_id: Optional[int]):
        if clip_id != self.selected_clip:
            self.selected_clip = clip_id
            self.dirty.emit()

    # --- clips
    def _note_values(self, clip: Clip) -> bool:
        """Remembers tag values in first-seen order; True if a new one appeared."""
        new = False
        for t, v in clip.tags.items():
            if self.tag_kinds.get(t) == STRING and isinstance(v, str) and clean_tag(v) != v:
                v = clip.tags[t] = clean_tag(v)   # a value must always be usable as a folder name
            if self.tag_kinds.get(t) == STRING and v and v not in self.tag_values.setdefault(t, []):
                self.tag_values[t].append(v)
                new = True
        return new

    def add(self, clip: Clip) -> Clip:
        clip.id, self._next_id = self._next_id, self._next_id + 1
        self._note_values(clip)
        self.clips.append(clip)
        self.clips.sort(key=lambda c: c.start)
        self.structure_changed.emit()
        self.dirty.emit()
        return clip

    def remove(self, clip: Clip):
        self.clips.remove(clip)
        if self.selected_clip == clip.id:
            self.selected_clip = None
        self.structure_changed.emit()
        self.dirty.emit()

    def touch(self, clip: Clip):
        """Call after editing a stored clip."""
        new_value = self._note_values(clip)
        before = [c.id for c in self.clips]
        self.clips.sort(key=lambda c: c.start)
        if new_value or [c.id for c in self.clips] != before:
            self.structure_changed.emit()
        else:
            self.clip_changed.emit(clip)
        self.dirty.emit()

    # --- tags
    def values(self, tag: str) -> list[str]:
        return list(self.tag_values.get(tag, []))

    def first_string_tag(self) -> Optional[str]:
        """The tag the number-key quick picks and the T key work on (normally 'character')."""
        return next((t for t in self.tag_types if self.tag_kinds.get(t) == STRING), None)

    def filter_values(self, tag: str) -> list[str]:
        """The choices offered by the library filter for a tag."""
        kind = self.tag_kinds.get(tag, STRING)
        if kind == BOOL:
            return ["Yes", "No"]
        if kind == INT:
            return [str(v) for v in sorted({c.tags[tag] for c in self.clips if tag in c.tags})]
        return self.values(tag)

    RESERVED_TAG_NAMES = ("id", "n", "start", "text")   # file-name template tokens

    @classmethod
    def tag_name_problem(cls, name: str) -> Optional[str]:
        """Why `name` cannot be a tag type name, or None if it can."""
        if not name.strip():
            return "The name is empty."
        if clean_tag(name) != name.strip():
            return INVALID_HELP_TEXT
        if name.strip().lower() in cls.RESERVED_TAG_NAMES:
            return f"'{name.strip()}' is reserved for file naming ({', '.join(cls.RESERVED_TAG_NAMES)})."
        return None

    def add_tag_type(self, name: str, kind: str = STRING):
        if name and name not in self.tag_types and kind in KINDS and not self.tag_name_problem(name):
            self.tag_types.append(name)
            self.tag_kinds[name] = kind
            self.structure_changed.emit()
            self.dirty.emit()

    def rename_value(self, tag: str, old: str, new: str):
        """Renames a tag value across every clip (e.g. voice1 -> Alastor)."""
        new = clean_tag(new)
        if not new:
            return
        merged: list[str] = []
        for v in self.tag_values.get(tag, []):
            v = new if v == old else v
            if v not in merged:  # renaming onto an existing value merges the two
                merged.append(v)
        self.tag_values[tag] = merged
        for c in self.clips:
            if c.tags.get(tag) == old:
                c.tags[tag] = new
        self.value_renamed.emit(tag, old, new)
        self.structure_changed.emit()
        self.dirty.emit()


def tag_text(project: Project, clip: Clip, tag: str) -> str:
    """A clip's tag value as shown in the library and matched by its filters."""
    v = clip.tags.get(tag)
    kind = project.tag_kinds.get(tag, STRING)
    if kind == BOOL:
        return "Yes" if v else "No"
    return "" if v is None else str(v)


EXPORT_LABELS = {"done": "✓ Exported", "exporting": "◐ Exporting", "queued": "⋯ Queued", "changed": "● Changed",
                 "failed": "✗ Failed"}
SPINNER = "◐◓◑◒"
EXPORT_COLORS = {"done": "#2e9e5b", "failed": "#d04437", "changed": "#d98b1f"}


class ClipTableModel(QAbstractTableModel):
    def __init__(self, project: Project):
        super().__init__()
        self.p = project
        self.export_status = None   # callable(Clip) -> (state, tooltip), set by whoever runs exports
        self._spin = 0              # frame of the 'exporting' marker's animation
        project.structure_changed.connect(self._reset)
        project.clip_changed.connect(self._row_changed)

    def _reset(self):
        self.beginResetModel()
        self.endResetModel()

    def _row_changed(self, clip):
        r = self.p.clips.index(clip)
        self.dataChanged.emit(self.index(r, 0), self.index(r, self.columnCount() - 1))

    def tick(self):
        """Advances the 'exporting' marker's animation."""
        self._spin += 1
        if self.rowCount():
            col = self.columns().index("Export")
            self.dataChanged.emit(self.index(0, col), self.index(self.rowCount() - 1, col))

    def refresh_clip(self, clip_id: int):
        """The export state of one clip changed: repaint its Export cell."""
        for r, c in enumerate(self.p.clips):
            if c.id == clip_id:
                col = self.columns().index("Export")
                self.dataChanged.emit(self.index(r, col), self.index(r, col))
                return

    def columns(self) -> list[str]:
        return ["#", "In", "Dur", *self.p.tag_types, "Text", "Export"]

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.p.clips)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns())

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.columns()[section]

    def clip_at(self, row: int) -> Clip:
        return self.p.clips[row]

    def data(self, index, role=Qt.DisplayRole):
        c, col = self.p.clips[index.row()], self.columns()[index.column()]
        if col == "Export":
            state, tip = self.export_status(c) if self.export_status else ("none", "")
            if role == Qt.DisplayRole:
                if state == "exporting":
                    return SPINNER[self._spin % len(SPINNER)] + " Exporting"
                return EXPORT_LABELS.get(state, "")
            if role == Qt.ForegroundRole and state in EXPORT_COLORS:
                return QColor(EXPORT_COLORS[state])
            if role == Qt.ToolTipRole:
                return tip or None
            return None
        if role != Qt.DisplayRole:
            return None
        if col == "#":
            return index.row() + 1
        if col == "In":
            return f"{int(c.start // 60)}:{c.start % 60:06.3f}"
        if col == "Dur":
            return f"{c.duration:.2f}s"
        if col == "Text":
            return c.text
        if self.p.tag_kinds.get(col) == BOOL:
            return "✓" if c.tags.get(col) else ""
        return tag_text(self.p, c, col)


class ClipFilter(QSortFilterProxyModel):
    """Keeps clips whose tags match every active filter (tag -> value)."""

    def __init__(self, source: ClipTableModel):
        super().__init__()
        self.setSourceModel(source)
        self.filters: dict[str, str] = {}

    def set_filter(self, tag: str, value: Optional[str]):
        if value:
            self.filters[tag] = value
        else:
            self.filters.pop(tag, None)
        self.invalidateFilter()

    def filterAcceptsRow(self, row, _parent):
        c = self.sourceModel().clip_at(row)
        p = self.sourceModel().p
        return all(tag_text(p, c, t) == v for t, v in self.filters.items())
