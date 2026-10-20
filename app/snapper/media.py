"""Media probing, cache locations and background ffmpeg jobs."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QProcess, Signal

RATE = 44100  # waveform / export sample rate
PROXY_HEIGHT = 480
PROXY_CACHE_LIMIT = 2 * 1024**3  # oldest proxies are deleted beyond this many bytes


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or default).expanduser()


# Under Flatpak the XDG variables point into ~/.var/app/<id>/, so these land in the app's own data and cache folders.
CACHE_ROOT = Path(os.environ["SNAPPER_CACHE"]).expanduser() if os.environ.get("SNAPPER_CACHE") \
    else _xdg("XDG_CACHE_HOME", "~/.cache") / "snapper"
DATA_ROOT = Path(os.environ["SNAPPER_DATA"]).expanduser() if os.environ.get("SNAPPER_DATA") \
    else _xdg("XDG_DATA_HOME", "~/.local/share") / "snapper"


def projects_dir() -> Path:
    d = DATA_ROOT / "projects"
    d.mkdir(parents=True, exist_ok=True)
    return d
TEXT_SUBTITLE_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}


@dataclass
class MediaInfo:
    path: Path
    duration: float
    has_video: bool
    subtitles: list[dict] = field(default_factory=list)  # {"order", "codec", "lang", "title"}
    audio: list[dict] = field(default_factory=list)      # {"order", "codec", "channels", "lang", "title"}


def probe(path: Path) -> MediaInfo:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration:stream=index,codec_type,codec_name,channels,start_time:stream_tags=language,title",
                          "-of", "json", str(path)], capture_output=True, check=True, text=True).stdout
    j = json.loads(out)
    subs, audio = [], []
    for s in j.get("streams", []):
        kind = s.get("codec_type")
        if kind in ("subtitle", "audio"):
            tags = s.get("tags", {})
            target = subs if kind == "subtitle" else audio
            entry = {"order": len(target), "codec": s.get("codec_name", ""),
                     "lang": tags.get("language", ""), "title": tags.get("title", "")}
            if kind == "audio":
                entry["channels"] = s.get("channels", 0)
                try:
                    entry["start_time"] = float(s.get("start_time", 0.0))   # the track starts this late on the timeline
                except ValueError:
                    entry["start_time"] = 0.0
            target.append(entry)
    return MediaInfo(path, float(j["format"]["duration"]),
                     any(s.get("codec_type") == "video" for s in j.get("streams", [])), subs, audio)


def cache_dir(media: Path) -> Path:
    st = media.stat()
    key = hashlib.sha1(f"{media.resolve()}:{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:16]
    d = CACHE_ROOT / key
    d.mkdir(parents=True, exist_ok=True)
    return d


def audio_path(media: Path, track: int = 0) -> Path:
    """Decoded mono PCM for one audio track (track 0 keeps the original file name)."""
    return cache_dir(media) / (f"audio_{RATE}.s16" if track == 0 else f"audio_{RATE}_a{track}.s16")


def proxy_path(media: Path) -> Path:
    return cache_dir(media) / f"proxy_{PROXY_HEIGHT}_all.mkv"


def touch_proxy(path: Path):
    """Marks a proxy as just used, so pruning removes the least recently used ones first."""
    try:
        os.utime(path)
    except OSError:
        pass


def prune_proxies(keep: Path | None = None, limit: int = PROXY_CACHE_LIMIT) -> list[Path]:
    """Deletes the least recently used proxies until all proxies together fit in `limit` bytes.
    The proxy in `keep` (the one in use) is never deleted. Returns what was removed."""
    found = []
    for f in CACHE_ROOT.glob("*/proxy_*.mkv"):
        try:
            st = f.stat()
        except OSError:
            continue
        found.append((st.st_mtime, st.st_size, f))
    total = sum(size for _m, size, _f in found)
    removed = []
    for _m, size, f in sorted(found):
        if total <= limit:
            break
        if keep is not None and f == keep:
            continue
        try:
            f.unlink()
        except OSError:
            continue
        total -= size
        removed.append(f)
    return removed


def subtitle_path(media: Path, order: int) -> Path:
    return cache_dir(media) / f"subs_{order}.srt"


def open_audio(path: Path) -> np.memmap:
    """Mono s16 PCM on disk; memory-mapped so RAM stays flat."""
    return np.memmap(path, dtype=np.int16, mode="r")


class FfmpegJob(QObject):
    """Runs ffmpeg writing to <out>.tmp, renames on success, reports progress from -progress."""
    progress = Signal(float)
    done = Signal(bool, str)

    def __init__(self, args: list[str], duration: float, out: Path, parent=None):
        super().__init__(parent)
        self._out, self._tmp, self._dur = out, out.with_name(out.name + ".tmp"), max(duration, 1.0)
        self._proc = QProcess(self)
        self._proc.setProgram("ffmpeg")
        self._proc.setArguments(["-nostdin", "-v", "error", "-progress", "pipe:1", "-nostats", "-y",
                                 *args, str(self._tmp)])
        self._proc.readyReadStandardOutput.connect(self._read)
        self._proc.finished.connect(self._finished)
        self._proc.errorOccurred.connect(self._error)

    def _error(self, err):
        if err == QProcess.FailedToStart:  # a killed process also reports an error; only this one is a failure to run
            self.done.emit(False, "ffmpeg could not be started")

    def start(self):
        self._proc.start()

    def kill(self):
        self._proc.kill()

    def _read(self):
        for line in bytes(self._proc.readAllStandardOutput()).decode(errors="replace").splitlines():
            if line.startswith("out_time_us="):
                try:
                    self.progress.emit(min(1.0, int(line.split("=")[1]) / 1e6 / self._dur))
                except ValueError:
                    pass

    def _finished(self, code, _status):
        if code == 0:
            try:
                os.replace(self._tmp, self._out)
            except FileNotFoundError:  # another window already produced the same file
                if not self._out.exists():
                    self.done.emit(False, f"{self._tmp.name} disappeared")
                    return
            self.progress.emit(1.0)
            self.done.emit(True, "")
        else:
            err = bytes(self._proc.readAllStandardError()).decode(errors="replace")
            self._tmp.unlink(missing_ok=True)
            self.done.emit(False, err.strip() or f"ffmpeg exited with {code}")


SAMPLE_FORMATS = {16: ("s16le", "int16"), 24: ("s32le", "int32"), 32: ("f32le", "float32")}  # bit depth -> ffmpeg, numpy


def pcm_args(info: MediaInfo, track: int, channels: int, rate: int, bits: int) -> list[str]:
    """ffmpeg arguments that decode one audio track to raw PCM. The waveform and every export are decoded with
    these same arguments (only channels/rate/depth differ), so sample N of one is the same moment as sample N of
    the other. A track that starts late on the timeline is padded with silence, so sample 0 is always time 0."""
    filters = []
    start = info.audio[track].get("start_time", 0.0) if track < len(info.audio) else 0.0
    if start > 0.0005:
        filters.append(f"adelay={round(start * 1000)}:all=1")
    # ffmpeg scales a surround downmix to avoid clipping for integer output but not for float output; fixing the
    # scale makes 16-, 24- and 32-bit decodes (and so every export format) the same loudness.
    filters.append("aresample=rematrix_maxval=1.0")
    return ["-i", str(info.path), "-map", f"0:a:{track}", "-vn", "-af", ",".join(filters),
            "-ac", str(channels), "-ar", str(rate), "-f", SAMPLE_FORMATS[bits][0]]


def audio_job(info: MediaInfo, duration: float, track: int = 0, parent=None) -> FfmpegJob:
    """The waveform's audio: mono, 16-bit, RATE."""
    return FfmpegJob(pcm_args(info, track, 1, RATE, 16), duration, audio_path(info.path, track), parent)


def export_pcm_path(media: Path, track: int, channels: int, rate: int, bits: int) -> Path:
    if (channels, rate, bits) == (1, RATE, 16):
        return audio_path(media, track)   # identical to the waveform's audio: exports slice that very file
    return cache_dir(media) / f"export_a{track}_{channels}ch_{rate}_{bits}.pcm"


def pcm_job(info: MediaInfo, duration: float, track: int, channels: int, rate: int, bits: int, parent=None) -> FfmpegJob:
    return FfmpegJob(pcm_args(info, track, channels, rate, bits), duration,
                     export_pcm_path(info.path, track, channels, rate, bits), parent)


def open_pcm(path: Path, channels: int, bits: int) -> np.ndarray:
    """A decoded PCM file as an (frames, channels) array, memory-mapped so RAM stays flat."""
    return np.memmap(path, dtype=SAMPLE_FORMATS[bits][1], mode="r").reshape(-1, channels)


def proxy_job(media: Path, duration: float, parent=None) -> FfmpegJob:
    """480p all-intra H.264 (every frame a keyframe) so any scrub position decodes instantly."""
    return FfmpegJob(["-i", str(media), "-map", "0:v:0", "-map", "0:a?",  # every audio track, so the track picker works on the proxy
                      "-vf", f"scale=-2:{PROXY_HEIGHT},format=yuv420p",
                      "-c:v", "libx264", "-preset", "veryfast", "-g", "1", "-crf", "34",
                      "-c:a", "copy", "-f", "matroska"], duration, proxy_path(media), parent)


class SubtitleExtractJob(QObject):
    """Extracts every text subtitle track to <cache>/subs_<n>.srt in one pass over the file."""
    done = Signal(bool, str)

    def __init__(self, media: Path, orders: list[int], parent=None):
        super().__init__(parent)
        self._pairs = [(o, subtitle_path(media, o)) for o in orders]
        args = ["-nostdin", "-v", "error", "-y", "-i", str(media)]
        for o, path in self._pairs:
            args += ["-map", f"0:s:{o}?", "-c:s", "srt", "-f", "srt", str(path.with_name(path.name + ".tmp"))]
        self._proc = QProcess(self)
        self._proc.setProgram("ffmpeg")
        self._proc.setArguments(args)
        self._proc.finished.connect(self._finished)
        self._proc.errorOccurred.connect(
            lambda e: self.done.emit(False, "ffmpeg could not be started") if e == QProcess.FailedToStart else None)

    def start(self):
        self._proc.start()

    def kill(self):
        self._proc.kill()

    def _finished(self, code, _status):
        for _o, path in self._pairs:
            tmp = path.with_name(path.name + ".tmp")
            if tmp.exists():
                os.replace(tmp, path)
        self.done.emit(code == 0, bytes(self._proc.readAllStandardError()).decode(errors="replace")[-300:])


def extract_subtitle(media: Path, order: int) -> Path:
    """One subtitle track to a cached .srt (used when the background extraction has not produced it)."""
    out = subtitle_path(media, order)
    if not out.exists():
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(media), "-map", f"0:s:{order}",
                        "-c:s", "srt", "-f", "srt", str(out)], check=True)
    return out


def remove_export_audio(media: Path):
    """Deletes this video's temporary export decodes (the waveform's own audio is kept)."""
    for f in cache_dir(media).glob("export_*.pcm"):
        f.unlink(missing_ok=True)


def purge_old_export_audio(max_age_s: float = 86400.0):
    """Removes export decodes left behind by a crash: anything not touched for a day."""
    import time
    for f in CACHE_ROOT.glob("*/export_*.pcm"):
        try:
            if time.time() - f.stat().st_mtime > max_age_s:
                f.unlink()
        except OSError:
            pass
