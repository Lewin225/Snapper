"""Exporting the clip library: settings, file naming and folders, WAV writing, and the export run.

Audio comes from decoded PCM that is sample-aligned with the waveform (see media.pcm_args): a clip's start and end
times are turned into sample indices once, and exactly those samples are written, so what is highlighted on the
waveform is what is exported.
"""
from __future__ import annotations

import json
import os
import re
import struct
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import QThread, Signal

from .model import BOOL, Clip, Project, tag_text
from .pathnames import clean_part, has_invalid_chars

FORMATS = ("wav",)                      # mp3 comes next
SAMPLE_RATES = (44100, 48000, 22050)
WAV_BIT_DEPTHS = (16, 24, 32)           # 32 is floating point
# WAV text fields: the LIST/INFO chunk id for each choice offered in the settings
WAV_TEXT_FIELDS = {"comment": "ICMT", "title": "INAM", "subject": "ISBJ"}
TOKENS = ("id", "n", "start", "text")   # file-name template tokens; every tag name is a token too
UNTAGGED_FOLDER = "_none"
DEFAULT_TEMPLATE = "{character}_{n}"
_TOKEN_RE = re.compile(r"\{([^{}]*)\}")


@dataclass
class ExportSettings:
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
    """Where each clip goes, relative to the export folder. Names are made safe, and clashes (compared
    case-insensitively, as some file systems do) get _2, _3... added."""
    clips = [c for c in (clips if clips is not None else project.clips) if c.start is not None and c.end is not None]
    digits = max(3, len(str(len(clips))))
    used: set[str] = set()
    out = []
    for n, c in enumerate(clips, 1):
        stem = clean_part(render_name(settings.name_template, c, project, n, digits)) or f"clip_{n}"
        rel = Path(*folder_for(c, project, settings.folder_tags))
        name, k = stem, 2
        while str(rel / (name + ".wav")).lower() in used:
            name = f"{stem}_{k}"
            k += 1
        used.add(str(rel / (name + ".wav")).lower())
        out.append((c, rel / f"{name}.{settings.format}"))
    return out


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


# --------------------------------------------------------------------------- the run
@dataclass
class ExportResult:
    files: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    cancelled: bool = False


def clip_frames(pcm: np.ndarray, rate: int, clip: Clip) -> np.ndarray:
    """The samples of a clip: [round(start*rate), round(end*rate)) of the decoded audio."""
    i0, i1 = int(round(clip.start * rate)), int(round(clip.end * rate))
    return np.asarray(pcm[max(i0, 0):min(i1, len(pcm))])


def write_plan(plan: list[tuple[Clip, Path]], tag_kinds: dict[str, str], settings: ExportSettings, pcm: np.ndarray,
               out_dir: Path, progress: Optional[Callable[[float], None]] = None,
               cancelled: Callable[[], bool] = lambda: False) -> ExportResult:
    """Writes the planned clips under `out_dir`. `pcm` is the decoded audio at the settings' rate/channels/depth."""
    result = ExportResult()
    out_dir = out_dir.resolve()
    info_id = WAV_TEXT_FIELDS.get(settings.text_field or "")
    for i, (clip, rel) in enumerate(plan):
        if cancelled():
            result.cancelled = True
            break
        target = (out_dir / rel).resolve()
        if out_dir not in target.parents:   # names are sanitised already; this is the last line of defence
            result.skipped.append(f"{rel}: outside the export folder")
            continue
        frames = clip_frames(pcm, settings.sample_rate, clip)
        if len(frames) == 0:
            result.skipped.append(f"{rel}: no audio in this time range")
            continue
        info = {info_id: clip.text} if info_id and clip.text else None
        tags = {t: (True if tag_kinds.get(t) == BOOL else v) for t, v in clip.tags.items()} \
            if settings.embed_tags else None
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(wav_bytes(frames, settings.sample_rate, settings.bit_depth, info, tags))
        os.replace(tmp, target)
        result.files.append(target)
        if progress:
            progress((i + 1) / len(plan))
    return result


def export_clips(project: Project, settings: ExportSettings, pcm: np.ndarray, out_dir: Path,
                 progress: Optional[Callable[[float], None]] = None,
                 cancelled: Callable[[], bool] = lambda: False) -> ExportResult:
    return write_plan(plan_files(project, settings), dict(project.tag_kinds), settings, pcm, out_dir, progress, cancelled)


class ExportWorker(QThread):
    """Runs export_clips off the UI thread."""
    progress = Signal(float)
    finished_with = Signal(object, str)   # (ExportResult or None, error text)

    def __init__(self, project: Project, settings: ExportSettings, pcm: np.ndarray, out_dir: Path, parent=None):
        super().__init__(parent)
        # A snapshot taken now, on the UI thread: the library may be edited while the export runs.
        plan = [(replace(c, tags=dict(c.tags)), rel) for c, rel in plan_files(project, settings)]
        self._args = (plan, dict(project.tag_kinds), settings, pcm, out_dir)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            res = write_plan(*self._args, progress=self.progress.emit, cancelled=lambda: self._cancel)
        except Exception as e:   # disk full, permission denied...
            self.finished_with.emit(None, f"{type(e).__name__}: {e}")
            return
        self.finished_with.emit(res, "")
