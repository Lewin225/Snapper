"""Play Clip plays in -> out and stops at the out marker; Play from In keeps going.

usage: python tests/play_clip_test.py EPISODE.mkv   (needs the display/GL environment from run.sh)
"""
import locale
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os, tempfile
os.environ.setdefault("SNAPPER_DATA", tempfile.mkdtemp())   # tests never touch the real projects
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from snapper.theme import apply_system_theme
from snapper.main_window import MainWindow
from support import wait_until_ready

import support
app = support.application()
win = support.window()
btn = {b.text(): b for b in win.findChildren(QPushButton)}

win.set_range(40.0, 42.4)
btn["▶ Play Clip (P)"].click()
QTest.qWait(1000)
assert not win.player.paused, "should be playing mid-clip"
QTest.qWait(3500)
print(f"Play Clip: paused={win.player.paused} pos={win.player.pos:.3f} (out marker 42.400)")
assert win.player.paused and abs(win.player.pos - 42.4) < 0.1, "should stop at the out marker"

win.play_from_in()   # no button any more; the I-key position is the clip start
for _ in range(80):   # mpv in a test window can be slow to start: wait for it to pass the out marker
    QTest.qWait(100)
    if win.player.pos > 42.9:
        break
print(f"Play from In: paused={win.player.paused} pos={win.player.pos:.3f}")
assert not win.player.paused and win.player.pos > 42.9, "Play from In must not stop at the out marker"
win.player.stop()
# playhead motion: Accurate steps with mpv's reports (once per video frame); Smooth moves on every screen refresh
def distinct_positions(ms=1500):
    seen, end = set(), time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QTest.qWait(2)
        seen.add(round(win.editor.wave.playhead, 5))
    return len(seen)
win.set_range(40.0, 60.0)
win.player.play_range(40.0, 60.0)
QTest.qWait(800)
win.set_playhead_motion("accurate")
accurate = distinct_positions()
win.set_playhead_motion("smooth")
smooth = distinct_positions()
assert win._glide.isActive() and abs(win.editor.wave.playhead - win.player.pos) < 0.4, (win.editor.wave.playhead, win.player.pos)
win.player.stop()
for _ in range(40):   # the seek back to where playback started reports its position a moment later
    QTest.qWait(50)
    if abs(win.editor.wave.playhead - win.player.pos) < 1e-6:
        break
assert not win._glide.isActive() and abs(win.editor.wave.playhead - win.player.pos) < 1e-6, ("paused: exactly where mpv is", win._glide.isActive(), win.editor.wave.playhead, win.player.pos)
assert win.act_motion["smooth"].isChecked() and QSettings("snapper", "snapper").value("playhead/motion") == "smooth"
print(f"ok   playhead motion: {accurate} distinct positions in 1.5 s while Accurate, {smooth} while Smooth")
assert smooth > accurate * 2, (accurate, smooth)   # video 24-30 fps; the screen is 60 Hz or more
print("PLAY CLIP OK")
support.finish(win)
