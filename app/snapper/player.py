"""mpv wrapper and the OpenGL video widget. mpv plays the audio, so the video follows it."""
from __future__ import annotations

import ctypes
import os
from typing import Optional

import mpv
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtOpenGLWidgets import QOpenGLWidget


LOG_ALL = bool(os.environ.get("SNAPPER_MPV_LOG"))  # debugging: print mpv warnings too


class Player(QObject):
    position = Signal(float)
    paused_changed = Signal(bool)
    ready = Signal(float)      # a file finished loading; duration
    restarted = Signal()       # a seek completed
    loaded_signal = Signal()   # internal: a file finished loading (any thread)

    def __init__(self, parent=None):
        super().__init__(parent)
        # 10-bit nvdec output renders as noise in the Qt GL context, so frames are converted to 8-bit.
        extra = {"ao": os.environ["SNAPPER_AO"]} if os.environ.get("SNAPPER_AO") else {}  # debugging aid
        self.mpv = mpv.MPV(**extra, vo="libmpv", keep_open="yes", pause=True, audio_channels="stereo", hr_seek="yes",
                           vf="format=yuv420p", loglevel=os.environ.get("SNAPPER_MPV_LEVEL", "warn"),
                           log_handler=lambda lvl, comp, msg: (lvl in ("error", "fatal") or LOG_ALL) and
                           print(f"[mpv {lvl}] {comp}: {msg.strip()}", flush=True))
        self.pos, self.duration, self.paused = 0.0, 0.0, True
        self.play_start = 0.0
        self._file: Optional[tuple] = None
        self._gl = False
        self._pending: Optional[float] = None
        self._loaded = False
        self._aid = 1  # mpv audio track id (1-based)
        self._iso: Optional[str] = None     # the isolated-dialogue audio file, added to the video as one more audio track
        self._n_audio = 0                   # how many audio tracks the video has itself (the isolated one comes after them)
        self._iso_aid = 1                   # its mpv track id
        self._want_iso = False              # whether that extra track is the one to hear
        self._iso_loaded = False            # whether the current file has it
        self._queued_seek: Optional[tuple[float, bool]] = None  # seek asked for while a file was loading
        self._inflight = False
        self._end: Optional[float] = None
        self._range_timer = QTimer(self, interval=10, timeout=self._check_end)

        @self.mpv.property_observer("time-pos")
        def _tp(_n, v):
            if v is not None:
                self.pos = v
                self.position.emit(v)

        @self.mpv.property_observer("duration")
        def _du(_n, v):
            if v:
                self.duration = v
                self.ready.emit(v)

        @self.mpv.property_observer("pause")
        def _pa(_n, v):
            self.paused = bool(v)
            self.paused_changed.emit(self.paused)

        @self.mpv.event_callback("start-file")
        def _sf(_e):
            self._loaded = False
            self._iso_loaded = self._iso is not None   # a new file is opened with the extra track (see _do_load)

        @self.mpv.event_callback("file-loaded")
        def _fl(_e):
            self._loaded = True
            self._apply_audio()
            self.loaded_signal.emit()

        @self.mpv.event_callback("playback-restart")
        def _pr(_e):
            self.restarted.emit()

        self.restarted.connect(self._on_restart)
        self.loaded_signal.connect(self._on_loaded)

    def set_audio_track(self, index: int):
        """Chooses which audio track is heard (0-based, in file order)."""
        self._aid = index + 1
        if self._loaded:
            self._apply_audio()

    def _apply_audio(self):
        """Selects the track to hear: the isolated one when wanted and present, else the chosen original."""
        aid = self._iso_aid if self._want_iso and self._iso_loaded else self._aid
        if aid == 1 and not self._loaded:
            return
        try:
            self.mpv.aid = aid
        except Exception:
            pass

    def set_isolated(self, path: Optional[str], n_audio: int) -> bool:
        """Makes the isolated-dialogue audio (a WAV the same length as the video) available as one more audio track,
        or removes it (None). `n_audio` is how many audio tracks the video itself has. Returns True when the video
        has to be loaded again to drop or replace an extra track it already has."""
        if path and self._iso and self._iso.endswith(".tmp") and path == self._iso[:-4]:
            self._iso = path   # the file that was being written was renamed when it finished: mpv keeps reading it
            return False
        changed = path != self._iso
        had = self._iso_loaded
        self._iso, self._n_audio = path, n_audio
        self._iso_aid = n_audio + 1
        if path is None:
            self._want_iso = False
        if not (changed and self._loaded):
            return False
        if had:
            self._iso_loaded = False   # mpv cannot drop a track: the caller reloads the file
            return True
        if path is not None:
            try:
                self.mpv.command("audio-add", path, "auto")
                self._iso_loaded = True
            except Exception as e:
                print(f"[player] could not add the isolated audio: {e}", flush=True)
        self._apply_audio()
        return False

    def use_isolated(self, on: bool):
        """Hears the isolated dialogue (True) or the original audio (False)."""
        self._want_iso = on and self._iso is not None
        if self._loaded:
            self._apply_audio()

    # --- loading
    def load(self, path: str, hwdec: str, start: float = 0.0, pause: bool = True):
        self._file = (path, hwdec, start, pause)
        self._loaded = False
        if self._gl:
            self._do_load()

    def gl_ready(self):
        """The render context exists; mpv must not open a file before this."""
        self._gl = True
        if self._file:
            self._do_load()

    def _do_load(self):
        path, hwdec, start, pause = self._file
        self.mpv["hwdec"] = hwdec
        opts = {"audio_files": self._iso} if self._iso else {}   # the isolated audio rides along as an extra track
        self.mpv.loadfile(path, "replace", start=f"{start:.3f}", pause="yes" if pause else "no", **opts)

    def now(self) -> float:
        """The playback position straight from mpv. `pos` is fed by an asynchronous event and can lag a moment
        behind, which must not happen when marking in/out points."""
        try:
            t = self.mpv.time_pos
        except Exception:
            t = None
        return t if t is not None else self.pos

    # --- transport
    def seek(self, t: float, exact: bool = True):
        if not self._loaded:
            self._queued_seek = (t, exact)  # applied when the file finishes loading
            return
        try:
            self.mpv.command("seek", min(max(0.0, t), self.duration), "absolute+" + ("exact" if exact else "keyframes"))
        except SystemError as e:  # mpv rejects seeks during file transitions; never crash the UI for it
            print(f"[player] seek to {t:.2f} rejected: {e}", flush=True)

    def _on_loaded(self):
        if self._queued_seek:
            t, exact = self._queued_seek
            self._queued_seek = None
            self.seek(t, exact)

    def scrub(self, t: float):
        """Latest wins: only the newest target is kept, so seeks never queue up behind the cursor."""
        self._pending = t
        if not self._inflight:
            self._issue()

    def _issue(self):
        t, self._pending = self._pending, None
        if t is not None:
            self._inflight = True
            self.seek(t, exact=False)

    def _on_restart(self):
        self._inflight = False
        if self.paused:
            # A seek finished: refresh the position even if mpv sent no time-pos event. Only while paused: a blocking
            # read during playback can wait on mpv while mpv waits on this thread to draw a frame, stalling playback.
            t = self.now()
            self.pos = t
            self.position.emit(t)
        self._issue()

    def toggle(self):
        self._end = None
        self._range_timer.stop()
        if self.paused:
            self.play_start = self.now()
        self.mpv.pause = not self.paused

    def stop(self):
        """Pause and return to where playback last started, to replay a spot while tuning a cut."""
        self._end = None
        self._range_timer.stop()
        self.mpv.pause = True
        self.seek(self.play_start)

    def play_range(self, a: float, b: Optional[float]):
        self.play_start = a
        self._end = b
        self.seek(a)
        self.mpv.pause = False
        if b is not None:
            self._range_timer.start()

    def _check_end(self):
        if self._end is not None and self.pos >= self._end:
            self.mpv.pause = True
            self.seek(self._end)
            self._end = None
            self._range_timer.stop()

    def shutdown(self):
        self.mpv.terminate()


class VideoWidget(QOpenGLWidget):
    frame_ready = Signal()

    def __init__(self, player: Player):
        super().__init__()
        self.player = player
        self.ctx = None
        self.frame_ready.connect(self.update)

    def initializeGL(self):
        egl = ctypes.CDLL("libEGL.so.1")
        egl.eglGetProcAddress.restype = ctypes.c_void_p
        egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]
        self._get_proc = mpv.MpvGlGetProcAddressFn(lambda _, name: egl.eglGetProcAddress(name))
        self.ctx = mpv.MpvRenderContext(self.player.mpv, "opengl",
                                        opengl_init_params={"get_proc_address": self._get_proc})
        self.ctx.update_cb = lambda: self.frame_ready.emit()
        self.frameSwapped.connect(self.ctx.report_swap)  # tells mpv the frame was shown, so it can schedule the next
        self.player.gl_ready()

    def paintGL(self):
        if self.ctx:
            self.ctx.update()  # required before every render: lets mpv advance to the next video frame
            r = self.devicePixelRatio()
            self.ctx.render(opengl_fbo={"w": int(self.width() * r), "h": int(self.height() * r),
                                        "fbo": self.defaultFramebufferObject()}, flip_y=True)

    def closeEvent(self, e):
        if self.ctx:
            self.ctx.update_cb = None
            self.ctx.free()
            self.ctx = None
        super().closeEvent(e)
