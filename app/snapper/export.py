"""Exporting the clip library: settings, file naming and folders, WAV writing, and the export run.

Audio comes from decoded PCM that is sample-aligned with the waveform (see media.pcm_args): a clip's start and end
times are turned into sample indices once, and exactly those samples are written, so what is highlighted on the
waveform is what is exported.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import struct
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from . import media as media_cache
from .model import BOOL, Clip, Project, tag_text
from .pathnames import clean_part, has_invalid_chars

FORMATS = ("wav",)                      # mp3 comes next
SAMPLE_RATES = (44100, 48000, 22050)
WAV_BIT_DEPTHS = (16, 24, 32)           # 32 is floating point
# WAV text fields: the LIST/INFO chunk id for each choice offered in the settings
WAV_TEXT_FIELDS = {"comment": "ICMT", "title": "INAM", "subject": "ISBJ"}
TOKENS = ("id", "n", "start", "text")   # file-name template tokens; every tag name is a token too
UNTAGGED_FOLDER = "_none"
DEFAULT_TEMPLATE = "{character}_{text}"
_TOKEN_RE = re.compile(r"\{([^{}]*)\}")


@dataclass
class ExportSettings:
    output_dir: str = ""                 # where the files go; chosen in the settings dialog
    name_template: str = DEFAULT_TEMPLATE
    format: str = "wav"
    channels: int = 1                    # 1 = mono, 2 = stereo
    sample_rate: int = 44100
    bit_depth: int = 16                  # WAV: 16 or 24 bit integer, 32 bit float
    folder_tags: list[str] = field(default_factory=list)   # first folder, then sub-folders
    text_field: Optional[str] = "comment"                   # which text field the clip text is written to; None = not written
    embed_tags: bool = True

    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(d: dict) -> "ExportSettings":
        base = ExportSettings()
        s = ExportSettings(**{k: v for k, v in d.items() if k in asdict(base)})
        if s.format not in FORMATS:
            s.format = base.format
        if s.channels not in (1, 2):
            s.channels = 1
        if s.sample_rate not in SAMPLE_RATES:
            s.sample_rate = base.sample_rate
        if s.bit_depth not in WAV_BIT_DEPTHS:
            s.bit_depth = base.bit_depth
        if s.text_field not in WAV_TEXT_FIELDS:
            s.text_field = None
        return s


def output_dir_problem(path: str) -> Optional[str]:
    """Why `path` cannot be the export folder, or None if clips can be written there."""
    if not path.strip():
        return "Choose the folder the clips are exported to."
    d = Path(path)
    if not d.is_dir():
        return "That folder does not exist."
    if not os.access(d, os.W_OK):
        return "That folder is not writable."
    return None


# --------------------------------------------------------------------------- naming
def template_problem(template: str, tag_types: list[str]) -> Optional[str]:
    """Why `template` cannot be used as a file name, or None if it is fine."""
    if not template.strip():
        return "The name is empty."
    known = {*TOKENS, *tag_types}
    for tok in _TOKEN_RE.findall(template):
        if tok not in known:
            return f"Unknown field {{{tok}}}. Available: " + ", ".join("{%s}" % t for t in (*TOKENS, *tag_types))
    literal = _TOKEN_RE.sub("", template)
    if "{" in literal or "}" in literal:
        return "Unmatched { or }."
    if has_invalid_chars(literal):
        return 'The name can\'t contain  \\ / : * ? " < > |  (folders come from the folder settings).'
    return None


def render_name(template: str, clip: Clip, project: Project, n: int, digits: int) -> str:
    def value(tok: str) -> str:
        if tok == "id":
            return str(clip.id if clip.id is not None else n)
        if tok == "n":
            return f"{n:0{digits}d}"
        if tok == "start":
            return str(int(round(clip.start * 1000)))
        if tok == "text":
            return clean_part(clip.text[:40], 40) if clip.text.strip() else ""
        return tag_text(project, clip, tok) if tok in project.tag_kinds else ""
    return _TOKEN_RE.sub(lambda m: value(m.group(1)), template)


def folder_for(clip: Clip, project: Project, folder_tags: list[str]) -> list[str]:
    parts = []
    for tag in folder_tags:
        if tag not in project.tag_kinds:
            continue
        v = tag_text(project, clip, tag)
        parts.append(clean_part(v) if v else UNTAGGED_FOLDER)
    return parts


def plan_files(project: Project, settings: ExportSettings, clips: Optional[list[Clip]] = None) -> list[tuple[Clip, Path]]:
    """Where each clip goes, relative to the export folder. `{n}` is the clip's number (its id), so a clip's name
    does not change when other clips are added, removed or reordered. Names are made safe, and clashes (compared
    case-insensitively, as some file systems do) get _2, _3... added, always in clip-number order so existing
    clips keep their names when a new clip clashes with them. Planned over the whole library, then filtered
    to `clips`."""
    everyone = sorted((c for c in project.clips if c.start is not None and c.end is not None and c.id is not None),
                      key=lambda c: c.id)
    wanted = None if clips is None else {c.id for c in clips}
    used: set[str] = set()
    out = []
    for c in everyone:
        stem = clean_part(render_name(settings.name_template, c, project, c.id, 3)) or f"clip_{c.id}"
        rel = Path(*folder_for(c, project, settings.folder_tags))
        name, k = stem, 2
        while str(rel / (name + ".wav")).lower() in used:
            name = f"{stem}_{k}"
            k += 1
        used.add(str(rel / (name + ".wav")).lower())
        if wanted is None or c.id in wanted:
            out.append((c, rel / f"{name}.{settings.format}"))
    return out


def export_signature(clip: Clip, settings: ExportSettings, track: int) -> str:
    """Identifies everything that decides a clip's exported file. If it differs from the signature stored when the
    clip was exported, the file is out of date."""
    payload = {"start": clip.start, "end": clip.end, "track": track, "settings": settings.to_json(),
               "text": clip.text if settings.text_field else None,
               "tags": clip.tags if (settings.embed_tags or settings.folder_tags or "{" in settings.name_template) else None}
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- WAV
def _chunk(cid: bytes, payload: bytes) -> bytes:
    pad = b"\0" if len(payload) % 2 else b""
    return cid + struct.pack("<I", len(payload)) + payload + pad


def wav_bytes(frames: np.ndarray, rate: int, bits: int, info: Optional[dict[str, str]] = None,
              tags: Optional[dict] = None) -> bytes:
    """A WAV file for `frames` (shape (n, channels); int16 for 16 bit, int32 for 24 bit, float32 for 32 bit).
    `info` fields go in a LIST/INFO chunk (id -> text), `tags` in a custom 'snpr' chunk as JSON."""
    n, ch = frames.shape
    if bits == 16:
        data, tag, width = frames.astype("<i2").tobytes(), 1, 2
    elif bits == 24:   # the top 24 bits of the 32 bit decode, little endian
        raw = frames.astype("<i4").view(np.uint8).reshape(n, ch, 4)[:, :, 1:]
        data, tag, width = raw.tobytes(), 1, 3
    elif bits == 32:
        data, tag, width = frames.astype("<f4").tobytes(), 3, 4
    else:
        raise ValueError(f"unsupported bit depth {bits}")
    fmt = struct.pack("<HHIIHH", tag, ch, rate, rate * ch * width, ch * width, width * 8)
    if tag == 3:   # floating point WAV needs the extension size and a fact chunk
        fmt += struct.pack("<H", 0)
    body = b"WAVE" + _chunk(b"fmt ", fmt)
    if tag == 3:
        body += _chunk(b"fact", struct.pack("<I", n))
    body += _chunk(b"data", data)
    if info:
        sub = b"".join(_chunk(cid.encode("ascii"), text.encode("utf-8") + b"\0") for cid, text in info.items())
        body += _chunk(b"LIST", b"INFO" + sub)
    if tags is not None:
        body += _chunk(b"snpr", json.dumps(tags, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return b"RIFF" + struct.pack("<I", len(body)) + body


def read_wav(path: Path) -> dict:
    """Reads back a WAV written by `wav_bytes` (used by the tests): format, frames and the extra chunks."""
    raw = path.read_bytes()
    assert raw[:4] == b"RIFF" and raw[8:12] == b"WAVE" and struct.unpack("<I", raw[4:8])[0] == len(raw) - 8
    pos, out = 12, {"info": {}, "tags": None}
    while pos < len(raw):
        cid, size = raw[pos:pos + 4], struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        body = raw[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            out["format"], out["channels"], out["rate"], _br, _ba, out["bits"] = struct.unpack("<HHIIHH", body[:16])
        elif cid == b"data":
            out["data"] = body
        elif cid == b"LIST" and body[:4] == b"INFO":
            p = 4
            while p < len(body):
                sid, ssize = body[p:p + 4].decode("ascii"), struct.unpack("<I", body[p + 4:p + 8])[0]
                out["info"][sid] = body[p + 8:p + 8 + ssize].rstrip(b"\0").decode("utf-8")
                p += 8 + ssize + (ssize % 2)
        elif cid == b"snpr":
            out["tags"] = json.loads(body.decode("utf-8"))
        pos += 8 + size + (size % 2)
    ch, bits = out["channels"], out["bits"]
    if bits == 16:
        out["frames"] = np.frombuffer(out["data"], "<i2").reshape(-1, ch)
    elif bits == 24:
        b = np.frombuffer(out["data"], np.uint8).reshape(-1, ch, 3)
        out["frames"] = (np.concatenate([np.zeros_like(b[:, :, :1]), b], axis=2).copy().view("<i4")[:, :, 0])
    else:
        out["frames"] = np.frombuffer(out["data"], "<f4").reshape(-1, ch)
    return out


# --------------------------------------------------------------------------- writing
@dataclass
class ExportResult:
    files: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    cancelled: bool = False


def clip_frames(pcm: np.ndarray, rate: int, clip: Clip) -> np.ndarray:
    """The samples of a clip: [round(start*rate), round(end*rate)) of the decoded audio."""
    i0, i1 = int(round(clip.start * rate)), int(round(clip.end * rate))
    return np.asarray(pcm[max(i0, 0):min(i1, len(pcm))])


def write_one(clip: Clip, rel: Path, tag_kinds: dict[str, str], settings: ExportSettings, pcm: np.ndarray,
              out_dir: Path) -> Path:
    """Writes one clip to out_dir/rel and returns the file's path. Raises ValueError if the clip cannot be written."""
    out_dir = out_dir.resolve()
    target = (out_dir / rel).resolve()
    if out_dir not in target.parents:   # names are sanitised already; this is the last line of defence
        raise ValueError(f"{rel}: outside the export folder")
    frames = clip_frames(pcm, settings.sample_rate, clip)
    if len(frames) == 0:
        raise ValueError(f"{rel}: no audio in this time range")
    info_id = WAV_TEXT_FIELDS.get(settings.text_field or "")
    info = {info_id: clip.text} if info_id and clip.text else None
    tags = {t: (True if tag_kinds.get(t) == BOOL else v) for t, v in clip.tags.items()} if settings.embed_tags else None
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(wav_bytes(frames, settings.sample_rate, settings.bit_depth, info, tags))
    os.replace(tmp, target)
    return target


def remove_exported(old: Path, out_dir: Path):
    """Deletes a clip's earlier export (it moved or was renamed) and any folders that became empty, never going
    above out_dir and never touching anything outside it."""
    out_dir = out_dir.resolve()
    try:
        old = old.resolve()
    except OSError:
        return
    if out_dir not in old.parents:
        return
    old.unlink(missing_ok=True)
    d = old.parent
    while d != out_dir:
        try:
            d.rmdir()   # only succeeds while empty
        except OSError:
            break
        d = d.parent


def write_plan(plan: list[tuple[Clip, Path]], tag_kinds: dict[str, str], settings: ExportSettings, pcm: np.ndarray,
               out_dir: Path, progress: Optional[Callable[[float], None]] = None,
               cancelled: Callable[[], bool] = lambda: False) -> ExportResult:
    """Writes a whole plan (a batch export). `pcm` is the decoded audio at the settings' rate/channels/depth."""
    result = ExportResult()
    for i, (clip, rel) in enumerate(plan):
        if cancelled():
            result.cancelled = True
            break
        try:
            result.files.append(write_one(clip, rel, tag_kinds, settings, pcm, out_dir))
        except ValueError as e:
            result.skipped.append(str(e))
        if progress:
            progress((i + 1) / len(plan))
    return result


def export_clips(project: Project, settings: ExportSettings, pcm: np.ndarray, out_dir: Path,
                 progress: Optional[Callable[[float], None]] = None,
                 cancelled: Callable[[], bool] = lambda: False) -> ExportResult:
    return write_plan(plan_files(project, settings), dict(project.tag_kinds), settings, pcm, out_dir, progress, cancelled)


# --------------------------------------------------------------------------- the background queue
class _Worker(QThread):
    """Writes queued clips one at a time, off the UI thread."""
    started_clip = Signal(int)
    finished_clip = Signal(int, bool, str)   # clip id, ok, file path or error text

    def __init__(self, parent=None):
        super().__init__(parent)
        self.jobs: queue.Queue = queue.Queue()
        self._pcm: dict[str, np.ndarray] = {}

    def run(self):
        while True:
            job = self.jobs.get()
            if job is None:
                return
            clip, rel, kinds, settings, pcm_path, old = job
            self.started_clip.emit(clip.id)
            try:
                if pcm_path not in self._pcm:
                    self._pcm[pcm_path] = media_cache.open_pcm(Path(pcm_path), settings.channels, settings.bit_depth)
                out_dir = Path(settings.output_dir)
                target = write_one(clip, rel, kinds, settings, self._pcm[pcm_path], out_dir)
                if old and Path(old).resolve() != target:
                    remove_exported(Path(old), out_dir)
                self.finished_clip.emit(clip.id, True, str(target))
            except Exception as e:   # bad time range, disk full, permission denied...
                self.finished_clip.emit(clip.id, False, str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}")


class ExportManager(QObject):
    """Exports clips in the background and remembers each clip's state, so the library can show which clip is
    queued, exporting, done, changed since, or failed. Clips can be added at any time, even while it is working."""
    state_changed = Signal(int)    # a clip's state changed (clip id)
    progress = Signal(float)       # fraction of the current batch written
    idle = Signal()                # nothing queued or running any more

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self._transient: dict[int, tuple[str, str]] = {}   # clip id -> (queued|exporting|failed, message)
        self._sig: dict[int, str] = {}
        self._failed_sig: dict[int, Optional[str]] = {}   # clip id -> its signature when it failed
        self._sigs_at_submit: dict[int, str] = {}   # clip id -> signature when it was queued
        self._settings: Optional[tuple[int, ExportSettings]] = None
        self._worker: Optional[_Worker] = None
        self._pending = 0     # submitted and not finished
        self._batch_total = 0
        self._batch_done = 0
        for sig in (project.dirty, project.structure_changed, project.clip_changed):
            sig.connect(self._invalidate)

    # --- state
    def _invalidate(self, *_):
        self._sig.clear()
        self._settings = None

    def settings(self) -> Optional[ExportSettings]:
        d = self.project.export_settings
        if d is None:
            return None
        if self._settings is None or self._settings[0] != id(d):
            self._settings = (id(d), ExportSettings.from_json(d))
        return self._settings[1]

    def current_signature(self, clip: Clip) -> Optional[str]:
        s = self.settings()
        if s is None:
            return None
        if clip.id not in self._sig:
            self._sig[clip.id] = export_signature(clip, s, self.project.audio_track)
        return self._sig[clip.id]

    def state(self, clip: Clip) -> str:
        if clip.id in self._transient:
            st = self._transient[clip.id][0]
            if st == "failed" and self._failed_sig.get(clip.id) != self.current_signature(clip):
                del self._transient[clip.id]   # edited since it failed: worth another try
            else:
                return st
        if clip.export_sig:
            return "done" if clip.export_sig == self.current_signature(clip) else "changed"
        return "none"

    def status(self, clip: Clip) -> tuple[str, str]:
        st = self.state(clip)
        if clip.id in self._transient:
            return st, self._transient[clip.id][1]
        tips = {"done": f"Exported to {clip.export_path}", "none": "Not exported yet",
                "changed": "Changed since it was exported (or the export settings changed). Export again to update it."}
        return st, tips.get(st, "")

    def outstanding(self, clips: list[Clip], retry_failed: bool = True) -> list[Clip]:
        """Clips that still need exporting: never exported, changed since, or (if asked) failed last time."""
        wanted = ("none", "changed", "failed") if retry_failed else ("none", "changed")
        return [c for c in clips if self.state(c) in wanted]

    def verify_files(self):
        """Forgets exports whose file has been deleted since (so they show as not exported)."""
        for c in self.project.clips:
            if c.export_sig and c.export_path and not Path(c.export_path).exists():
                c.export_sig = c.export_path = None
                self.state_changed.emit(c.id)

    # --- queue
    def mark_queued(self, clips: list[Clip]):
        for c in clips:
            self._transient[c.id] = ("queued", "Waiting to be exported")
            self.state_changed.emit(c.id)
        self._batch_total += len(clips)
        self._pending += len(clips)

    def cancel_queued(self, clips: list[Clip], reason: str):
        """The audio for these clips could not be prepared."""
        for c in clips:
            self._transient[c.id] = ("failed", reason)
            self._failed_sig[c.id] = self.current_signature(c)
            self.state_changed.emit(c.id)
        self._pending -= len(clips)
        self._batch_done += len(clips)
        self._check_idle()

    def submit(self, clips: list[Clip], settings: ExportSettings, pcm_path: Path):
        """Queues clips (already marked queued) for writing. `pcm_path` is the decoded audio matching `settings`."""
        if self._worker is None:
            self._worker = _Worker(self)
            self._worker.started_clip.connect(self._on_started)
            self._worker.finished_clip.connect(self._on_finished)
            self._worker.start()
        plan = {c.id: rel for c, rel in plan_files(self.project, settings, clips)}
        kinds = dict(self.project.tag_kinds)
        for c in clips:
            snap = replace(c, tags=dict(c.tags))   # the clip may be edited while it waits
            self._sigs_at_submit[c.id] = export_signature(c, settings, self.project.audio_track)
            self._worker.jobs.put((snap, plan[c.id], kinds, settings, str(pcm_path), c.export_path))

    def _on_started(self, clip_id: int):
        self._transient[clip_id] = ("exporting", "Exporting…")
        self.state_changed.emit(clip_id)

    def _on_finished(self, clip_id: int, ok: bool, info: str):
        clip = next((c for c in self.project.clips if c.id == clip_id), None)
        if ok:
            self._transient.pop(clip_id, None)
            if clip is not None:
                clip.export_sig = self._sigs_at_submit.get(clip_id)
                clip.export_path = info
                self.project.dirty.emit()
        else:
            self._transient[clip_id] = ("failed", info)
            self._failed_sig[clip_id] = self._sigs_at_submit.get(clip_id)
        self._pending -= 1
        self._batch_done += 1
        self.state_changed.emit(clip_id)
        self.progress.emit(self._batch_done / max(self._batch_total, 1))
        self._check_idle()

    def _check_idle(self):
        if self._pending <= 0:
            self._pending = self._batch_total = self._batch_done = 0
            self.idle.emit()

    def busy(self) -> bool:
        return self._pending > 0

    def shutdown(self):
        if self._worker is not None:
            self._worker.jobs.put(None)
            self._worker.wait(10000)
            self._worker = None
