"""Regression: typing in the character box / text field must not trigger cutting shortcuts.

usage: python tests/typing_test.py EPISODE.mkv   (needs the display/GL environment from run.sh)
"""
import locale, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os, tempfile
os.environ.setdefault("SNAPPER_DATA", tempfile.mkdtemp())   # tests never touch the real projects
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from snapper.theme import apply_system_theme
from snapper.main_window import MainWindow
from support import episode_arg
ep = episode_arg()
import support
app = support.application()
win = support.window(ep, settle_ms=4000); win.activateWindow()
calls = []
for name in ("set_in", "set_out", "commit", "deselect_clip", "play_selection"):
    orig = getattr(win, name)
    setattr(win, name, (lambda n, o: (lambda *a: (calls.append(n), o(*a))))(name, orig))
orig_toggle = win.player.toggle
win.player.toggle = lambda: (calls.append("toggle"), orig_toggle())
box = next(iter(win.editor.tag_boxes.values()))

def type_into(label, widget_click):
    calls.clear()
    QTest.mouseClick(widget_click, Qt.LeftButton)
    QTest.qWait(300)
    fw = QApplication.focusWidget()
    print(f"{label}: focus widget = {type(fw).__name__}", flush=True)
    for ch in "Billy Ops pos":
        QTest.keyClicks(QApplication.focusWidget() or widget_click, ch)
        QTest.qWait(30)
    print(f"   typed text={box.currentText()!r} shortcuts fired={calls}", flush=True)
    assert not calls, "shortcuts fired while typing"

type_into("click combo lineEdit", box.lineEdit())
win.setFocus(); QTest.qWait(200)
type_into("click combo arrow area", box)
win.text = win.editor.text
win.editor.text.clear()
type_into("click clip text field", win.editor.text)
print("text field contents:", repr(win.editor.text.toPlainText()))
# Return leaves the field and the shortcuts work again
QTest.mouseClick(box.lineEdit(), Qt.LeftButton); QTest.qWait(200)
QTest.keyClick(QApplication.focusWidget() or box, Qt.Key_Return); QTest.qWait(200)
print("after Return focus =", type(QApplication.focusWidget()).__name__, flush=True)
calls.clear(); QTest.keyClick(win, Qt.Key_I); QTest.qWait(100)
print("I after leaving field fires:", calls, flush=True)
assert calls == ["set_in"]
print("TYPING OK")
support.finish(win)
