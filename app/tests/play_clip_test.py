"""Play Clip plays in -> out and stops at the out marker; Play from In keeps going.

usage: python tests/play_clip_test.py EPISODE.mkv   (needs the display/GL environment from run.sh)
"""
import locale
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os, tempfile
os.environ.setdefault("SNAPPER_DATA", tempfile.mkdtemp())   # tests never touch the real projects
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from snapper.theme import apply_system_theme
from snapper.main_window import MainWindow
from support import wait_until_ready

app = QApplication(sys.argv)
locale.setlocale(locale.LC_NUMERIC, "C")
apply_system_theme(app)
win = MainWindow(__import__('support').episode_arg())
win.show()
wait_until_ready(win)
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
print("PLAY CLIP OK")
win.close()
