"""Regression: dragging splitter handles can collapse the transcript and clip list, never the video or editor.

usage: python tests/layout_test.py EPISODE.mkv   (needs the display/GL environment from run.sh)
"""
import locale
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os, tempfile
os.environ.setdefault("SNAPPER_DATA", tempfile.mkdtemp())   # tests never touch the real projects

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from snapper.__main__ import dark
from snapper.main_window import MainWindow

app = QApplication(sys.argv)
locale.setlocale(locale.LC_NUMERIC, "C")
dark(app)
win = MainWindow(Path(sys.argv[1]))
win.show()
win.move(900, 40)  # leave room on the left: a real drag cannot go past the screen edge
QTest.qWait(1500)
win.reset_layout()
QTest.qWait(300)


def drag(handle, dx, dy):
    c = handle.rect().center()
    QTest.mousePress(handle, Qt.LeftButton, Qt.NoModifier, c)
    steps = 30  # a real drag is many small moves, not one jump
    for i in range(1, steps + 1):
        QTest.mouseMove(handle, c + QPoint(dx * i // steps, dy * i // steps))
        QTest.qWait(5)
    QTest.mouseRelease(handle, Qt.LeftButton, Qt.NoModifier, c + QPoint(dx, dy))
    QTest.qWait(200)


# transcript | video: drag the handle far right -> transcript may grow, video must keep its minimum
drag(win.top.handle(1), 3000, 0)
print("handle dragged right: transcript", win.transcript_panel.width(), "video", win.video.width())
assert win.video.width() >= 300, "video collapsed"
# far left -> transcript may collapse completely
drag(win.top.handle(1), -3000, 0)
print("handle dragged left: transcript", win.transcript_panel.width(), "video", win.video.width())
assert win.top.sizes()[0] == 0, "transcript should be collapsible"
assert win.video.width() >= 300
win.toggle_pane("transcript")
QTest.qWait(200)
assert win.top.sizes()[0] > 100, "F2 / View menu restores the transcript"
print("restored via toggle_pane: transcript", win.transcript_panel.width())

# video | editor vertical: neither may collapse
drag(win.left.handle(1), 0, -3000)
print("handle dragged up: video box", win.video.height(), "editor", win.editor.height())
assert win.video.height() >= 200 and win.editor.height() >= 200
drag(win.left.handle(1), 0, 3000)
assert win.editor.height() >= 200 and win.video.height() >= 200, "editor or video collapsed"

# clip list collapses and restores
drag(win.root.handle(1), 3000, 0)
print("clip list after drag right:", win.clips.width())
assert win.root.sizes()[1] == 0, "clip list should be collapsible"
win.toggle_pane("clips")
QTest.qWait(200)
assert win.root.sizes()[1] > 200
win.reset_layout()
print("LAYOUT OK")
win.close()
