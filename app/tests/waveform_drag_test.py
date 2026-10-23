"""Dragging the waveform: with no clip selected a left-drag scrubs the playhead under the timeline (a click still just moves
it); with a clip selected it pans the view; holding the right button, then dragging, selects a clip (a quick right-click
or a drag before the hold is up does nothing, so a clip is never cleared by accident).

usage: python tests/waveform_drag_test.py [EPISODE.mkv]   (needs the display/GL environment from run.sh)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os, tempfile
os.environ.setdefault("SNAPPER_DATA", tempfile.mkdtemp())   # tests never touch the real projects
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import support
from snapper.waveform import SELECT_HOLD_MS

app = support.application()
win = support.window()
wave, ed = win.editor.wave, win.editor
Y = 60   # below the word band


def press(x, button=Qt.LeftButton):
    QTest.mousePress(wave, button, Qt.NoModifier, QPointF(x, Y).toPoint())


def move(x, button=Qt.LeftButton, steps=8, x0=None):
    x0 = x0 if x0 is not None else move.last
    for i in range(1, steps + 1):
        p = QPointF(x0 + (x - x0) * i / steps, Y)
        QApplication.sendEvent(wave, QMouseEvent(QEvent.MouseMove, p, wave.mapToGlobal(p), Qt.NoButton, button, Qt.NoModifier))
    move.last = x


def release(x, button=Qt.LeftButton):
    QTest.mouseRelease(wave, button, Qt.NoModifier, QPointF(x, Y).toPoint())
    QTest.qWait(150)


def secs_per_px():
    a, b = wave.view()
    return (b - a) / wave.width()


# --- no clip selected: left-drag scrubs
win.player.seek(100.0)
QTest.qWait(800)
assert wave.sel_in is None
x0 = wave.width() // 2
spp = secs_per_px()
before = wave.playhead
press(x0); move.last = x0
move(x0 - 100)                                   # drag the waveform 100 px to the left: the playhead moves later
assert abs(wave.playhead - (before + 100 * spp)) < 0.02, (wave.playhead, before, spp)
mid = wave.playhead
QTest.qWait(300)
assert abs(wave.playhead - mid) < 1e-6, "the playhead stays where the drag put it while the seeks catch up"
release(x0 - 100)
QTest.qWait(600)
assert abs(win.player.pos - mid) < 0.3 and abs(wave.playhead - win.player.pos) < 0.3, (win.player.pos, mid)
print("ok   no clip selected: dragging the waveform scrubs the playhead under the timeline")

# --- while playing, in "playback" scrub mode: it plays (mpv's scrub audio) as the mouse moves, holds when the mouse is still,
# plays on when let go
win.set_scrub_mode("chunks", save=False)
win.player.seek(100.0)
win.player.mpv.pause = False
QTest.qWait(1200)
assert not win.player.paused
import time
issued = []
real_seek = win.player.seek
win.player.seek = lambda t, exact=True, block=True: (issued.append(exact), real_seek(t, exact, block))[1]
press(x0); move.last = x0
t0 = time.perf_counter()
for i in range(1, 121):                            # a steady drag, one pixel per event
    move(x0 - i, steps=1)
    QTest.qWait(8)
took = time.perf_counter() - t0
assert took < 3.0, f"the window must not block on every seek ({took:.1f} s for 120 mouse moves)"
move(x0 - 120, steps=1)
assert issued and all(issued), "dragging seeks to the frame under the cursor, not to a keyframe"
win.player.seek = real_seek
assert not win.player.paused, "still playing while the mouse moves: that is the scrub audio"
QTest.qWait(500)                                   # the mouse does not move
assert win.player.paused, "held when the mouse is still"
hold_from = win.player.pos
QTest.qWait(1200)
assert abs(win.player.pos - hold_from) < 0.15 and abs(wave.playhead - hold_from) < 0.3, (win.player.pos, hold_from, wave.playhead)
assert abs(win.player.now() - wave.playhead) < 0.05, ("held exactly at the cursor", win.player.now(), wave.playhead)
move(x0 - 90, steps=3)                             # moving again plays on from there
QTest.qWait(60)
assert not win.player.paused
QTest.qWait(500)
assert win.player.paused
at_release = wave.playhead
release(x0 - 90)
QTest.qWait(250)
assert abs(win.player.now() - at_release) < 0.45, ("playing on from the release point", win.player.now(), at_release)
QTest.qWait(550)
assert not win.player.paused and win.player.pos > hold_from + 0.3, "it was playing before the drag, so it plays on after"
assert "Pause" in win.btn_play.text()
win.player.mpv.pause = True
QTest.qWait(300)
print("ok   dragging while playing: plays while the mouse moves, holds still when it stops, plays on when let go")
# and a drag that starts paused leaves it paused
win.player.seek(100.0)
QTest.qWait(500)
press(x0); move.last = x0
move(x0 + 40)
release(x0 + 40)
QTest.qWait(600)
assert win.player.paused
print("ok   a drag that started paused leaves it paused")

# --- tape scrub: the voice itself (numpy), then the drag
import numpy as np
from snapper.media import RATE
from snapper.tape_scrub import TapeVoice, LAG
ramp = (np.arange(RATE * 20) % 30000).astype(np.int16)     # a sawtooth: the value tells where the sample came from
tone = (np.sin(np.arange(RATE * 20) * 2 * np.pi * 440 / RATE) * 12000).astype(np.int16)

def run(voice, seconds, target_at):
    out = []
    for i in range(int(seconds * RATE / 512)):
        voice.set_target(target_at(i * 512 / RATE))
        out.append(voice.render(512))
    return np.concatenate(out)

v = TapeVoice(); v.begin(5.0, tone, None, 0.0, False)
fwd = run(v, 1.0, lambda t: 5.0 + t)                         # the cursor moves at normal speed: normal speed sound
assert abs(v.speed - 1.0) < 0.05 and abs(v.pos / RATE - 5.9) < 0.12, (v.speed, v.pos / RATE)
assert np.abs(fwd[RATE // 2:]).max() > 0.2, "the audio under the cursor is heard"
w = np.abs(np.fft.rfft(fwd[RATE // 2:RATE // 2 + 8192] * np.hanning(8192)))
assert abs(np.argmax(w) * RATE / 8192 - 440) < 15, "at normal speed the pitch is unchanged"
v.begin(5.0, tone, None, 0.0, False)
fast = run(v, 1.0, lambda t: 5.0 + 2 * t)
w = np.abs(np.fft.rfft(fast[RATE // 2:RATE // 2 + 8192] * np.hanning(8192)))
assert abs(np.argmax(w) * RATE / 8192 - 880) < 25, "twice as fast is an octave up"
print("ok   tape scrub: normal speed keeps the pitch, twice as fast is an octave higher")

v.begin(10.0, ramp, None, 0.0, False)
back = run(v, 1.0, lambda t: 10.0 - t)
assert v.speed < -0.9 and v.pos / RATE < 9.2, (v.speed, v.pos / RATE)
seg = back[RATE // 2:RATE // 2 + 4000]
assert np.median(np.diff(seg)) < 0, "moving backwards plays the audio backwards"
print("ok   moving the cursor backwards plays the audio backwards")

v.begin(5.0, tone, None, 0.0, False)
run(v, 0.5, lambda t: 5.0 + t)
still = run(v, 1.5, lambda t: 5.5 + 0.5)                     # the cursor stops: the sound dies away, then silence
assert np.abs(still[-RATE // 2:]).max() < 1e-4 and abs(v.pos / RATE - 6.0) < 0.01, "silent when still"
assert np.abs(still[:2000]).max() > 0.01, "...but not cut off sharply"
v.ending = True
assert np.abs(run(v, 0.2, lambda t: 6.0)[-2000:]).max() < 1e-4
print("ok   a still cursor is silent (the sound dies away, no click)")

def pitch(sig):
    w = np.abs(np.fft.rfft(sig * np.hanning(len(sig))))
    return np.argmax(w) * RATE / len(sig)

for speed in (1.0, 2.0, 0.5, -1.5):                          # granular: the pitch stays, whatever the speed
    v = TapeVoice(); v.begin(10.0, tone, None, 0.0, False, granular=True)
    g = run(v, 1.2, lambda t: 10.0 + speed * t)
    assert abs(pitch(g[RATE // 2:RATE // 2 + 16384]) - 440) < 30, (speed, pitch(g[RATE // 2:RATE // 2 + 16384]))
    assert 0.1 < np.abs(g[RATE // 2:]).max() < 0.5, (speed, np.abs(g[RATE // 2:]).max())
v = TapeVoice(); v.begin(5.0, tone, None, 0.0, False, granular=True)
run(v, 0.5, lambda t: 5.0 + t)
still = run(v, 1.5, lambda t: 6.0)
assert np.abs(still[-RATE // 2:]).max() < 1e-4, "granular is silent when the cursor is still too"
print("ok   granular scrub: the pitch stays at 440 Hz at 1x, 2x, 0.5x and backwards; silent when still")

# the preview volume applies to the scrub sound, on mpv's curve, and so does mute
win.volume.setValue(100)
assert abs(win._preview_gain() - 1.0) < 1e-9
win.volume.setValue(50)
assert abs(win._preview_gain() - 0.125) < 1e-9 and abs(win.tape.voice.gain - 0.125) < 1e-9
v = TapeVoice(); v.begin(5.0, tone, None, 0.0, False); loud = np.abs(run(v, 1.0, lambda t: 5.0 + t)).max()
v = TapeVoice(); v.gain = 0.125; v.begin(5.0, tone, None, 0.0, False); quiet = np.abs(run(v, 1.0, lambda t: 5.0 + t)).max()
assert abs(quiet / loud - 0.125) < 0.01 and abs(loud - 12000 / 32768 * 1.16) < 0.03, (loud, quiet)
win.toggle_mute()
assert win._preview_gain() == 0.0 and win.tape.voice.gain == 0.0
win.toggle_mute()
win.volume.setValue(80)
print("ok   the scrub sound follows the volume slider (mpv's cubic curve) and mute, at mpv's loudness")

iso = (tone // 4)
v.begin(3.0, tone, iso, 8.0, True)                            # processed audio where it exists, the original beyond
assert v._array() is iso
v.pos = 7.5 * RATE
assert v._array() is tone
print("ok   the processed audio is used where it exists, the original beyond it")

# the drag: tape and muted modes stop the video for the drag and play on after; playback mode is above
for mode in ("tape", "granular", "off"):
    win.set_scrub_mode(mode, save=False)
    win.player.seek(100.0)
    win.player.mpv.pause = False
    QTest.qWait(700)
    press(x0); move.last = x0
    move(x0 + 60, steps=6)
    QTest.qWait(150)
    assert win.player.paused, f"{mode}: the video is stopped while the waveform is dragged"
    assert (win.tape.active and win.tape.voice.target > 0) == (mode != "off")
    assert win.tape.voice.granular == (mode == "granular") or mode == "off"
    here = wave.playhead
    release(x0 + 60)
    QTest.qWait(700)
    assert not win.player.paused and win.player.pos > here - 0.3 and not win.tape.active, mode
    win.player.mpv.pause = True
    QTest.qWait(200)
print("ok   tape and muted scrub: the video stops for the drag and plays on from where it was released")
win.set_scrub_mode("chunks", save=False)

# --- endless dragging: the pointer is put back after every move, so a drag can go on past the edge of the screen
class Pointer:
    """Stands in for the pointer and the warp. `virt` is where the pointer is on screen: the hand moves it, a warp puts it back
    at the anchor, and (as on X11) the system then reports it there."""
    def __init__(self, sync=True, allowed=True):
        self.warps, self.sync, self.allowed, self.virt = [], sync, allowed, QPointF()
    def report(self):
        local = QPointF(wave.mapFromGlobal(self.virt.toPoint()))
        QApplication.sendEvent(wave, QMouseEvent(QEvent.MouseMove, local, self.virt, Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    def warp(self, pos):
        self.warps.append((pos.x(), pos.y()))
        if not self.allowed:
            return False
        self.virt = QPointF(pos)
        if self.sync:
            self.report()
        return True

def endless_drag(pointer, per_event=3, n=900):
    win.player.mpv.pause = True
    win.player.seek(400.0)
    QTest.qWait(600)
    wave.relative.warp = pointer.warp
    spp = secs_per_px()
    press(x0)
    pointer.virt = QPointF(wave.mapToGlobal(QPointF(x0, Y).toPoint()))
    for _ in range(n):                                  # the hand keeps moving: the warps keep the pointer near its anchor
        pointer.virt += QPointF(per_event, 0)
        pointer.report()
    shown = wave.playhead
    cursor = wave.cursor().shape()
    release(int(wave.mapFromGlobal(pointer.virt.toPoint()).x()))
    return 400.0, shown, spp, pointer.warps, cursor

start_t, shown, spp, warps, cursor = endless_drag(Pointer(), per_event=-3)
want = start_t + 3 * 900 * spp                          # 2700 px of hand movement, far more than the waveform is wide
assert 2700 > wave.width() and abs(shown - want) < 0.5, (shown, want)
assert len(warps) > 800 and len(set(warps[:-1])) == 1, "the pointer is put back at the same anchor after the moves"
assert cursor == Qt.BlankCursor and wave.cursor().shape() != Qt.BlankCursor, "hidden while dragging, shown again after"
assert wave.relative.warp and not wave.relative.active
print(f"ok   endless drag: 2700 px of movement through a {wave.width()} px waveform, the pointer held at its anchor and hidden")

start_t, shown, spp, warps, cursor = endless_drag(Pointer(sync=False), per_event=-3)
assert abs(shown - (start_t + 3 * 900 * spp)) < 0.5 + 8 * 3 * spp, "also where the system sends no report for a warp"
print("ok   the same where a warp is not answered with a report")

win.player.mpv.pause = True
win.player.seek(400.0)
QTest.qWait(600)
ptr = Pointer(allowed=False)                            # a native Wayland window: the pointer cannot be moved
wave.relative.warp = ptr.warp
spp = secs_per_px()
press(x0)
ptr.virt = QPointF(wave.mapToGlobal(QPointF(x0, Y).toPoint()))
for _ in range(100):
    ptr.virt += QPointF(1, 0)                           # an absolute drag: the pointer travels
    ptr.report()
shown = wave.playhead
release(x0 + 100)
assert abs(shown - (400.0 - 100 * spp)) < 0.3 and len(ptr.warps) == 1, (shown, 400.0 - 100 * spp, len(ptr.warps))
print("ok   where the pointer cannot be moved the drag is an ordinary one (one refused warp, then none)")
from snapper.drag import _warp
wave.relative.warp = _warp   # (refuses under SNAPPER_NO_WARP, which the tests set)

# --- a click still moves the playhead
t_click = wave._t(x0 + 150, *wave.view())
press(x0 + 150); release(x0 + 150)
QTest.qWait(500)
assert abs(win.player.pos - t_click) < 0.3, (win.player.pos, t_click)
print("ok   a click (no drag) still moves the playhead to that spot")

# --- clip selected: left-drag pans the view, nothing else changes
win.set_range(100.0, 103.0)
QTest.qWait(300)
a0, b0 = wave.view()
pos0, sel0 = win.player.pos, (wave.sel_in, wave.sel_out)
spp = secs_per_px()
press(x0); move.last = x0
move(x0 + 80)
a1, b1 = wave.view()
assert abs((a1 - a0) - (-80 * spp)) < 0.02 and abs((b1 - b0) - (-80 * spp)) < 0.02, (a0, a1, spp)
release(x0 + 80)
QTest.qWait(300)
assert (wave.sel_in, wave.sel_out) == sel0 and (ed.clip.start, ed.clip.end) == sel0 and abs(win.player.pos - pos0) < 0.05
print("ok   a clip selected: dragging offsets the view; the clip and the playhead are untouched")
win.set_range(100.2, 103.1)                       # an edit of the same clip keeps the view where it was put
assert wave.view_offset != 0.0
win.set_range(300.0, 302.0)                       # another clip: back to it
assert wave.view_offset == 0.0
print("ok   the offset lasts for this clip and resets for another")

# --- right button: hold, then drag, selects
win.set_range(None, None)
QTest.qWait(200)
assert wave.sel_in is None
before_view = wave.view()
a, b = wave.view()
xa, xb = int(wave.width() * 0.3), int(wave.width() * 0.55)
ta, tb = wave._t(xa, a, b), wave._t(xb, a, b)
press(xa, Qt.RightButton); move.last = xa
QTest.qWait(SELECT_HOLD_MS // 3)                  # not held long enough: the drag does nothing
move(xb, Qt.RightButton)
release(xb, Qt.RightButton)
assert wave.sel_in is None and ed.clip.start is None, "dragging before the hold is up selects nothing"
press(xa, Qt.RightButton); release(xa, Qt.RightButton)
assert wave.sel_in is None, "a quick right-click does nothing"
press(xa, Qt.RightButton); move.last = xa
QTest.qWait(SELECT_HOLD_MS + 120)
assert wave.cursor().shape() == Qt.CrossCursor, "the cursor says the drag will select now"
move(xb, Qt.RightButton)
release(xb, Qt.RightButton)
assert ed.clip.start is not None and abs(ed.clip.start - ta) < 0.06 and abs(ed.clip.end - tb) < 0.06, (ed.clip.start, ed.clip.end, ta, tb)
print(f"ok   right button: hold {SELECT_HOLD_MS} ms, then drag selects {ed.clip.start:.2f}-{ed.clip.end:.2f}; early drags and quick clicks do nothing")

# --- the same while a clip is selected: it is replaced, but only after the hold
win.set_range(200.0, 203.0)
QTest.qWait(300)
a, b = wave.view()
xa, xb = int(wave.width() * 0.4), int(wave.width() * 0.6)
press(xa, Qt.RightButton); move.last = xa
move(xb, Qt.RightButton)                          # no hold
release(xb, Qt.RightButton)
assert (ed.clip.start, ed.clip.end) == (200.0, 203.0), "a drag without the hold leaves the selected clip alone"
press(xa, Qt.RightButton); move.last = xa
QTest.qWait(SELECT_HOLD_MS + 120)
move(xb, Qt.RightButton)
release(xb, Qt.RightButton)
assert abs(ed.clip.start - wave._t(xa, a, b)) < 0.06 and abs(ed.clip.end - wave._t(xb, a, b)) < 0.06
print("ok   with a clip selected, only a held right-drag replaces it")

print("WAVEFORM DRAG OK")
support.finish(win)
