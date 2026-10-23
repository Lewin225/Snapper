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

# --- while playing: it plays (the scrub audio) as the mouse moves, holds when the mouse is still, plays on when let go
win.player.seek(100.0)
win.player.mpv.pause = False
QTest.qWait(1200)
assert not win.player.paused
import time
press(x0); move.last = x0
t0 = time.perf_counter()
for i in range(1, 121):                            # a steady drag, one pixel per event
    move(x0 - i, steps=1)
    QTest.qWait(8)
took = time.perf_counter() - t0
assert took < 3.0, f"the window must not block on every seek ({took:.1f} s for 120 mouse moves)"
move(x0 - 120, steps=1)
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
