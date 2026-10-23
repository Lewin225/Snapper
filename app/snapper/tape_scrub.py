"""Tape-style scrub sound: while the playhead is dragged, the audio under the cursor is played from the decoded samples at the
speed the cursor moves, backwards when it moves backwards, silent when it is still. mpv is not involved (it can only play
forward from a seek, which sounds like chunks). The sound goes to PulseAudio (or PipeWire's PulseAudio server, which is what
the Flatpak has access to) through libpulse-simple with ctypes and a buffer of about 30 ms; Qt's own audio output crashed
while listing the devices on some systems."""
from __future__ import annotations

import ctypes
import ctypes.util
import threading
from typing import Optional

import numpy as np

from .media import RATE

LAG = 0.05          # seconds: the sound follows the cursor with this much give, which is what smooths the speed
MAX_SPEED = 12.0    # times normal speed, either way
GAIN = 0.8
FADE = 0.06         # seconds to let the sound die away when the drag ends
STILL = 0.04        # speed (times normal) below which nothing is heard


class TapeVoice:
    """The sound itself, as numpy: `render(n)` gives the next n mono frames at `out_rate`."""

    def __init__(self, out_rate: int = RATE):
        self.out_rate = out_rate
        self.sources: tuple = (None, None, 0.0, False)   # original, processed, seconds of processed that exist, use processed
        self.pos = self.target = 0.0                      # in source samples
        self.speed = 0.0                                  # times normal speed
        self.level = 0.0                                  # 0..1, the fade at the start and end of a drag
        self.ending = False

    def begin(self, t: float, main, iso, iso_upto: float, use_iso: bool):
        self.sources = (main, iso, iso_upto, use_iso)
        self.pos = self.target = t * RATE
        self.speed, self.level, self.ending = 0.0, 0.0, False

    def set_target(self, t: float):
        self.target = t * RATE

    def _array(self):
        main, iso, upto, use_iso = self.sources
        if use_iso and iso is not None and self.pos / RATE < upto - 1.0:
            return iso
        return main

    def render(self, n: int) -> np.ndarray:
        arr = self._array()
        out = np.zeros(n, np.float32)
        if arr is None or len(arr) < 2:
            return out
        dt = n / self.out_rate
        want = 0.0 if self.ending else float(np.clip((self.target - self.pos) / RATE / LAG, -MAX_SPEED, MAX_SPEED))
        v1 = self.speed + (want - self.speed) * min(1.0, dt / (LAG / 2))   # smoothed, so a jerk is not a click
        speeds = np.linspace(self.speed, v1, n, dtype=np.float64)
        steps = speeds * (RATE / self.out_rate)
        idx = self.pos + np.cumsum(steps)
        self.pos, self.speed = float(np.clip(idx[-1], 0, len(arr) - 2)), v1
        i0 = np.clip(np.floor(idx).astype(np.int64), 0, len(arr) - 2)
        frac = (idx - i0).astype(np.float32)
        a = np.asarray(arr[i0], dtype=np.float32)
        b = np.asarray(arr[i0 + 1], dtype=np.float32)
        s = (a + (b - a) * np.clip(frac, 0, 1)) * (GAIN / 32768.0)
        amp = np.clip(np.abs(speeds) / STILL, 0.0, 1.0).astype(np.float32)   # nothing when still, no click on the way in
        moved = dt / (FADE if self.ending else 0.005)   # the fade in at the start of a drag, and out at the end
        level1 = float(np.clip(self.level + (-moved if self.ending else moved), 0.0, 1.0))
        ramp = np.linspace(self.level, level1, n, dtype=np.float32)
        self.level = level1
        return s * amp * ramp


BLOCK = 256         # frames per write (about 6 ms)
BUFFER = 0.03       # seconds of sound the output holds: the delay between the hand and the ear


class _Spec(ctypes.Structure):
    _fields_ = [("format", ctypes.c_int), ("rate", ctypes.c_uint32), ("channels", ctypes.c_uint8)]


class _Attr(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint32) for n in ("maxlength", "tlength", "prebuf", "minreq", "fragsize")]


_lib = None


def _pulse():
    """libpulse-simple, or None where there is no PulseAudio client library."""
    global _lib
    if _lib is None:
        try:
            lib = ctypes.CDLL(ctypes.util.find_library("pulse-simple") or "libpulse-simple.so.0")
            lib.pa_simple_new.restype = ctypes.c_void_p
            lib.pa_simple_new.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
                                          ctypes.POINTER(_Spec), ctypes.c_void_p, ctypes.POINTER(_Attr),
                                          ctypes.POINTER(ctypes.c_int)]
            lib.pa_simple_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_int)]
            lib.pa_simple_free.argtypes = [ctypes.c_void_p]
            _lib = lib
        except OSError:
            _lib = False
    return _lib or None


class TapeScrub:
    """Plays a TapeVoice while a drag lasts. The output is opened when the drag begins and closed shortly after it ends."""

    def __init__(self):
        self.voice = TapeVoice(RATE)
        self.active = False
        self._thread: Optional[threading.Thread] = None

    @staticmethod
    def available() -> bool:
        return _pulse() is not None

    def begin(self, t: float, main, iso, iso_upto: float, use_iso: bool) -> bool:
        """Starts sounding at time t. False when there is no PulseAudio library or no samples (the drag is then silent)."""
        if main is None or not self.available():
            return False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(0.5)   # the previous drag is still fading out: let it finish
        self.voice.begin(t, main, iso, iso_upto, use_iso)
        self.active = True
        self._thread = threading.Thread(target=self._run, name="tape-scrub", daemon=True)
        self._thread.start()
        return True

    def set_target(self, t: float):
        if self.active:
            self.voice.set_target(t)

    def end(self):
        """The drag is over: the sound dies away and the output closes."""
        if self.active:
            self.active = False
            self.voice.ending = True

    def _run(self):
        lib = _pulse()
        err = ctypes.c_int(0)
        frame = 2 * 2
        spec = _Spec(3, RATE, 2)   # PA_SAMPLE_S16LE, stereo
        attr = _Attr(0xFFFFFFFF, int(RATE * BUFFER) * frame, 0, int(RATE * 0.01) * frame, 0xFFFFFFFF)
        stream = lib.pa_simple_new(None, b"Snapper", 1, None, b"scrub", ctypes.byref(spec), None, ctypes.byref(attr),
                                   ctypes.byref(err))
        if not stream:
            return
        try:
            while True:
                mono = np.clip(self.voice.render(BLOCK), -1.0, 1.0)
                pcm = np.repeat((mono * 32767).astype(np.int16), 2).tobytes()
                if lib.pa_simple_write(stream, pcm, len(pcm), ctypes.byref(err)) < 0:
                    break
                if self.voice.ending and self.voice.level <= 0.0:
                    break
        finally:
            lib.pa_simple_free(stream)
