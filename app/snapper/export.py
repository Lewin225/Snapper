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
import subprocess
import re
import struct
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from . import id3
from . import media as media_cache
from .model import BOOL, Clip, Project, default_bool_labels, tag_text
from .pathnames import clean_part, has_invalid_chars

FORMATS = ("wav", "mp3")
SAMPLE_RATES = (44100, 48000, 22050)
WAV_BIT_DEPTHS = (16, 24, 32)           # 32 is floating point
FORMAT_VERSION = 3                      # of the metadata written into the files (docs/export-format.md); part of every signature
# The ID3 fields a tag can be written to (the same for MP3 and WAV); TXXX is a custom field named after the tag.
# The clip text is not a choice: it is always the lyrics (USLT), the synced text is SYLT.
FRAME_CHOICES = {"TXXX": "Custom field", "TIT2": "Title", "TPE1": "Artist", "TALB": "Album", "TCON": "Genre", "TRCK": "Track",
                 "TYER": "Year", "TCOP": "Copyright", "COMM": "Comment", "TIT3": "Subtitle"}
# A tag with one of these names (in any capitals) is bound to that field until the settings say otherwise
STANDARD_TAG_FRAMES = {"title": "TIT2", "artist": "TPE1", "album": "TALB", "genre": "TCON", "track": "TRCK",
                       "date": "TYER", "year": "TYER", "comment": "COMM", "copyright": "TCOP"}
# MP3 quality choices: constant bitrate (kbps) or LAME variable bitrate (v0 best ... v4)
MP3_QUALITIES = ("320", "256", "192", "160", "128", "v0", "v2", "v4")
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
    tag_frames: dict[str, str] = field(default_factory=dict)   # tag -> ID3 field, only where it differs from default_frame
    embed_tags: bool = True
    mp3_quality: str = "192"             # MP3: kbps, or v0/v2/v4 for variable bitrate

    @property
    def source_bits(self) -> int:
        """Bit depth of the audio the clips are cut from: MP3s are encoded from 16-bit audio."""
        return 16 if self.format == "mp3" else self.bit_depth

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
        if s.mp3_quality not in MP3_QUALITIES:
            s.mp3_quality = base.mp3_quality
        frames = s.tag_frames if isinstance(s.tag_frames, dict) else {}
        s.tag_frames = {t: f for t, f in frames.items() if isinstance(t, str) and f in FRAME_CHOICES}
        return s


def default_frame(tag: str) -> str:
    """The field a tag goes to unless the settings bind it elsewhere: the standard one for its name, else a custom field."""
    return STANDARD_TAG_FRAMES.get(tag.lower(), "TXXX")


def frame_for(settings: ExportSettings, tag: str) -> str:
    return settings.tag_frames.get(tag) or default_frame(tag)


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
        while str(rel / (name + "." + settings.format)).lower() in used:
            name = f"{stem}_{k}"
            k += 1
        used.add(str(rel / (name + "." + settings.format)).lower())
        if wanted is None or c.id in wanted:
            out.append((c, rel / f"{name}.{settings.format}"))
    return out


def export_signature(clip: Clip, settings: ExportSettings, track: int, labels: Optional[dict] = None) -> str:
    """Identifies everything that decides a clip's exported file. If it differs from the signature stored when the
    clip was exported, the file is out of date. `labels` maps each Yes/No tag to its two words (they are in the file
    and its name), see Project.all_bool_labels."""
    uses_tags = settings.embed_tags or settings.folder_tags or "{" in settings.name_template
    named = {*settings.folder_tags, *_TOKEN_RE.findall(settings.name_template)}
    # every Yes/No tag's answer is in the file when tags are embedded; otherwise only the ones the name or folders use
    used = {t: list(v) for t, v in (labels or {}).items() if settings.embed_tags or t in named}
    sets = settings.to_json()
    if not settings.embed_tags:
        sets["tag_frames"] = {}   # no tags in the file: where they would go changes nothing
    payload = {"format": FORMAT_VERSION, "start": clip.start, "end": clip.end, "track": track, "settings": sets,
               "text": clip.text,
               "tags": clip.tags if uses_tags else None, "labels": used}
    if clip.source != "original":   # absent for the original, so signatures made before isolation existed stay valid
        payload["source"] = clip.source
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- the tag
def clip_tag(clip: Clip, settings: ExportSettings, kinds: dict[str, str], labels: Optional[dict] = None) -> bytes:
    """The ID3v2.3 tag for a clip (b"" when nothing is to be written): the clip text as the lyrics (USLT),
    each tag in the field the settings bind it to (see frame_for; a field already taken by an earlier tag, or TXXX, gives
    a custom frame named after the tag), and
    the whole of it as JSON in a TXXX frame 'snpr', with the tags' real types. Both answers of a Yes/No tag are written,
    as the tag's labels. `kinds` maps every tag type to its kind, in order; `labels` is Project.all_bool_labels()."""
    items = []   # (tag, value for the JSON, text for the frame)
    if settings.embed_tags:
        for name, kind in kinds.items():
            if kind == BOOL:
                on = bool(clip.tags.get(name))
                yes, no = (labels or {}).get(name) or default_bool_labels(name)
                items.append((name, on, yes if on else no))
            elif clip.tags.get(name) not in (None, ""):
                items.append((name, clip.tags[name], str(clip.tags[name])))
        items += [(n, v, str(v)) for n, v in clip.tags.items() if n not in kinds and v not in (None, "")]

    def frame(fid: str, text: str) -> bytes:
        return id3.comment_frame(text) if fid == "COMM" else id3.text_frame(fid, text)

    used, standard, custom = set(), [], []
    for name, _value, text in items:
        fid = frame_for(settings, name)
        if fid == "TYER" and not re.fullmatch(r"\d{4}", text):   # TYER holds a four-digit year only
            fid = "TXXX"
        if fid != "TXXX" and fid not in used:
            used.add(fid)
            standard.append(frame(fid, text))
        else:
            custom.append(id3.txxx_frame(name, text))
    frames = [id3.uslt_frame(clip.text)] if clip.text else []
    frames += standard + custom
    doc: dict = {"format": FORMAT_VERSION}
    if clip.text:
        doc["text"] = clip.text
    if settings.embed_tags:
        doc["tags"] = {name: value for name, value, _text in items}
    if len(doc) > 1:
        frames.append(id3.txxx_frame("snpr", json.dumps(doc, ensure_ascii=False, sort_keys=True)))
    return id3.tag(frames) if frames else b""


# --------------------------------------------------------------------------- WAV and MP3
def _chunk(cid: bytes, payload: bytes) -> bytes:
    pad = b"\0" if len(payload) % 2 else b""
    return cid + struct.pack("<I", len(payload)) + payload + pad


def encode_mp3(frames: np.ndarray, rate: int, quality: str, target: Path, tag: bytes = b""):
    """Encodes 16-bit `frames` (n, channels) to an MP3 at `target` with ffmpeg's LAME encoder, then puts the ID3 `tag`
    in front. ffmpeg writes no tags of its own (it still leaves an empty tag header, which is cut off)."""
    n, ch = frames.shape
    q = ["-q:a", quality[1:]] if quality.startswith("v") else ["-b:a", f"{quality}k"]
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "s16le", "-ar", str(rate), "-ac", str(ch), "-i", "-",
           "-c:a", "libmp3lame", *q, "-map_metadata", "-1", "-write_id3v2", "0", "-fflags", "+bitexact", "-f", "mp3", str(target)]
    r = subprocess.run(cmd, input=frames.astype("<i2").tobytes(), capture_output=True)
    if r.returncode:
        target.unlink(missing_ok=True)
        raise ValueError(f"MP3 encoding failed: {r.stderr.decode(errors='replace').strip()[-200:]}")
    audio = target.read_bytes()
    target.write_bytes(tag + audio[id3.size_of(audio):])


def wav_bytes(frames: np.ndarray, rate: int, bits: int, tag: bytes = b"") -> bytes:
    """A WAV file for `frames` (shape (n, channels); int16 for 16 bit, int32 for 24 bit, float32 for 32 bit). The ID3
    `tag`, if any, goes in an 'ID3 ' chunk after the audio, the one place the file keeps its metadata."""
    n, ch = frames.shape
    if bits == 16:
        data, fmt_tag, width = frames.astype("<i2").tobytes(), 1, 2
    elif bits == 24:   # the top 24 bits of the 32 bit decode, little endian
        raw = frames.astype("<i4").view(np.uint8).reshape(n, ch, 4)[:, :, 1:]
        data, fmt_tag, width = raw.tobytes(), 1, 3
    elif bits == 32:
        data, fmt_tag, width = frames.astype("<f4").tobytes(), 3, 4
    else:
        raise ValueError(f"unsupported bit depth {bits}")
    fmt = struct.pack("<HHIIHH", fmt_tag, ch, rate, rate * ch * width, ch * width, width * 8)
    if fmt_tag == 3:   # floating point WAV needs the extension size and a fact chunk
        fmt += struct.pack("<H", 0)
    body = b"WAVE" + _chunk(b"fmt ", fmt)
    if fmt_tag == 3:
        body += _chunk(b"fact", struct.pack("<I", n))
    body += _chunk(b"data", data)
    if tag:
        body += _chunk(b"ID3 ", tag)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def read_wav(path: Path) -> dict:
    """Reads back a WAV written by `wav_bytes` (used by the tests): format, frames, the ID3 frames (`id3`), and from them
    the clip's `tags` and `meta` (the 'snpr' JSON). Files from before format 2 kept this in a LIST/INFO chunk (`info`)
    and a 'snpr' chunk; those are still read."""
    raw = path.read_bytes()
    assert raw[:4] == b"RIFF" and raw[8:12] == b"WAVE" and struct.unpack("<I", raw[4:8])[0] == len(raw) - 8
    pos, out = 12, {"info": {}, "tags": None, "meta": None, "id3": []}
    while pos < len(raw):
        cid, size = raw[pos:pos + 4], struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        body = raw[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            out["format"], out["channels"], out["rate"], _br, _ba, out["bits"] = struct.unpack("<HHIIHH", body[:16])
        elif cid == b"data":
            out["data"] = body
        elif cid in (b"ID3 ", b"id3 "):
            out["id3"] = id3.parse(body)
        elif cid == b"LIST" and body[:4] == b"INFO":
            p = 4
            while p < len(body):
                sid, ssize = body[p:p + 4].decode("ascii"), struct.unpack("<I", body[p + 4:p + 8])[0]
                out["info"][sid] = body[p + 8:p + 8 + ssize].rstrip(b"\0").decode("utf-8")
                p += 8 + ssize + (ssize % 2)
        elif cid == b"snpr":
            out["tags"] = json.loads(body.decode("utf-8"))
        pos += 8 + size + (size % 2)
    snpr = next((f.text for f in out["id3"] if f.id == "TXXX" and f.desc == "snpr"), None)
    if snpr is not None:
        out["meta"] = json.loads(snpr)
        out["tags"] = out["meta"].get("tags")
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
              out_dir: Path, labels: Optional[dict] = None) -> Path:
    """Writes one clip to out_dir/rel and returns the file's path. Raises ValueError if the clip cannot be written."""
    out_dir = out_dir.resolve()
    target = (out_dir / rel).resolve()
    if out_dir not in target.parents:   # names are sanitised already; this is the last line of defence
        raise ValueError(f"{rel}: outside the export folder")
    frames = clip_frames(pcm, settings.sample_rate, clip)
    if len(frames) == 0:
        raise ValueError(f"{rel}: no audio in this time range")
    tag = clip_tag(clip, settings, tag_kinds, labels)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    if settings.format == "mp3":
        encode_mp3(frames, settings.sample_rate, settings.mp3_quality, tmp, tag)
    else:
        tmp.write_bytes(wav_bytes(frames, settings.sample_rate, settings.bit_depth, tag))
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
               cancelled: Callable[[], bool] = lambda: False, labels: Optional[dict] = None) -> ExportResult:
    """Writes a whole plan (a batch export). `pcm` is the decoded audio at the settings' rate/channels/depth."""
    result = ExportResult()
    for i, (clip, rel) in enumerate(plan):
        if cancelled():
            result.cancelled = True
            break
        try:
            result.files.append(write_one(clip, rel, tag_kinds, settings, pcm, out_dir, labels))
        except ValueError as e:
            result.skipped.append(str(e))
        if progress:
            progress((i + 1) / len(plan))
    return result


def export_clips(project: Project, settings: ExportSettings, pcm: np.ndarray, out_dir: Path,
                 progress: Optional[Callable[[float], None]] = None,
                 cancelled: Callable[[], bool] = lambda: False) -> ExportResult:
    return write_plan(plan_files(project, settings), dict(project.tag_kinds), settings, pcm, out_dir, progress, cancelled,
                      project.all_bool_labels())


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
            clip, rel, kinds, labels, settings, pcm_path, old, old_root = job
            self.started_clip.emit(clip.id)
            try:
                if pcm_path not in self._pcm:
                    self._pcm[pcm_path] = media_cache.open_pcm(Path(pcm_path), settings.channels, settings.source_bits)
                out_dir = Path(settings.output_dir)
                target = write_one(clip, rel, kinds, settings, self._pcm[pcm_path], out_dir, labels)
                if old and old_root and Path(old).resolve() != target:   # the new copy exists: drop the old one
                    remove_exported(Path(old), Path(old_root))
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
        self._sigs_at_submit: dict[int, str] = {}
        self._delete_old: dict[int, bool] = {}
        self._cleanup_roots: list[Path] = []   # earlier export folders whose files may be deleted once re-exported   # clip id -> signature when it was queued
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

    def forget_audio(self):
        """Drops the decoded audio the writer holds open (the isolated audio may have just been replaced on disk)."""
        if self._worker is not None and not self.busy():
            self._worker._pcm.clear()

    def current_signature(self, clip: Clip) -> Optional[str]:
        s = self.settings()
        if s is None:
            return None
        if clip.id not in self._sig:
            self._sig[clip.id] = export_signature(clip, s, self.project.audio_track, self.project.all_bool_labels())
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

    def submit(self, clips: list[Clip], settings: ExportSettings, pcm_paths):
        """Queues clips (already marked queued) for writing. `pcm_paths` maps each audio source ("original",
        "isolated") to its decoded audio matching `settings`; a single path stands for the original only."""
        if not isinstance(pcm_paths, dict):
            pcm_paths = {"original": pcm_paths}
        if self._worker is None:
            self._worker = _Worker(self)
            self._worker.started_clip.connect(self._on_started)
            self._worker.finished_clip.connect(self._on_finished)
            self._worker.start()
        plan = {c.id: rel for c, rel in plan_files(self.project, settings, clips)}
        kinds, labels = dict(self.project.tag_kinds), self.project.all_bool_labels()
        for c in clips:
            snap = replace(c, tags=dict(c.tags))   # the clip may be edited while it waits
            self._sigs_at_submit[c.id] = export_signature(c, settings, self.project.audio_track, labels)
            self._worker.jobs.put((snap, plan[c.id], kinds, labels, settings, str(pcm_paths[c.source]), c.export_path,
                                   self._old_root(c.id, c.export_path, settings)))

    # The user's answer about a clip's old file, until that clip has been exported again: True = delete it once the new
    # copy is written, False = leave it. Clips with no entry have not been asked about yet.
    def decide_old_file(self, clip_ids: list[int], delete: bool):
        for i in clip_ids:
            self._delete_old[i] = delete

    def forget_decisions(self):
        self._delete_old.clear()

    def undecided(self, clips: list[Clip]) -> list[Clip]:
        return [c for c in clips if c.id not in self._delete_old]

    def moved_files(self, clips: list[Clip], settings: ExportSettings) -> list[Clip]:
        """Clips whose earlier export is still on disk but would now be written somewhere else (a different folder,
        name or format), so the old file would be left behind or cleaned up."""
        out = Path(settings.output_dir).resolve()
        moved = []
        for clip, rel in plan_files(self.project, settings, clips):
            if clip.export_path and Path(clip.export_path).exists() and \
                    Path(clip.export_path).resolve() != (out / rel).resolve():
                moved.append(clip)
        return moved

    def allow_cleanup(self, folder: str):
        """Files exported to `folder` may be tidied up (empty folders removed) when their clips move elsewhere."""
        root = Path(folder).resolve()
        if root not in self._cleanup_roots:
            self._cleanup_roots.append(root)

    def _old_root(self, clip_id: int, old: Optional[str], settings: ExportSettings) -> Optional[str]:
        """Where an earlier export of a clip may be deleted once the new copy exists, or None to leave it alone
        (the user said no to cleaning up). The returned folder is the limit for tidying up empty folders."""
        if not old or not self._delete_old.get(clip_id):
            return None
        return self.folder_limit(old, settings)

    def folder_limit(self, old: str, settings: ExportSettings) -> Optional[str]:
        """The folder an exported file lives in, as far as tidying up empty folders may go."""
        try:
            p = Path(old).resolve()
            for root in (Path(settings.output_dir).resolve(), *self._cleanup_roots):
                if root in p.parents:
                    return str(root)
            return str(p.parent.parent)   # an export folder from an earlier session: just the file (and its own folder)
        except OSError:
            return None

    def _on_started(self, clip_id: int):
        self._transient[clip_id] = ("exporting", "Exporting…")
        self.state_changed.emit(clip_id)

    def delete_file_of(self, clip: Clip) -> bool:
        """Deletes the clip's exported file (and folders that become empty). True if there was one."""
        s = self.settings()
        if not clip.export_path or not Path(clip.export_path).exists() or s is None:
            return False
        root = self.folder_limit(clip.export_path, s)
        if root is None:
            return False
        remove_exported(Path(clip.export_path), Path(root))
        clip.export_sig = clip.export_path = None
        return True

    def _on_finished(self, clip_id: int, ok: bool, info: str):
        self._delete_old.pop(clip_id, None)
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

    def cancel_waiting(self) -> int:
        """Drops the clips still waiting to be written (the one being written finishes). Returns how many."""
        n = 0
        while self._worker is not None:
            try:
                job = self._worker.jobs.get_nowait()
            except queue.Empty:
                break
            if job is None:   # a shutdown request must not be lost
                self._worker.jobs.put(None)
                break
            self._transient.pop(job[0].id, None)
            self._delete_old.pop(job[0].id, None)
            self.state_changed.emit(job[0].id)
            n += 1
        self._pending -= n
        self._batch_done += n
        if n:
            self._check_idle()
        return n

    def shutdown(self):
        if self._worker is not None:
            self._worker.jobs.put(None)
            self._worker.wait(10000)
            self._worker = None
