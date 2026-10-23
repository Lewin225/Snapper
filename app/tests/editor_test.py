"""Clip editor: drag-to-adjust start/end, typed values, Save to Library and Clear buttons.

usage: python tests/editor_test.py EPISODE.mkv [SCREENSHOT.png]   (needs the display/GL environment from run.sh)
"""
import locale
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os, tempfile
os.environ.setdefault("SNAPPER_DATA", tempfile.mkdtemp())   # tests never touch the real projects

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from snapper.theme import apply_system_theme
from snapper.main_window import MainWindow
from snapper.scrubber import parse_time

import support
from support import episode_arg, shot_arg
app = support.application()
episode = episode_arg()
episode.with_name(episode.name + ".snapper.json").unlink(missing_ok=True)
win = support.window(episode, settle_ms=4000)
ed = win.editor


def drag(scrubber, dx, mods=Qt.NoModifier, steps=10):
    """Press on the value, move dx pixels in small steps (with modifiers held), release."""
    pos = QPointF(60, 35)
    QTest.mousePress(scrubber, Qt.LeftButton, mods, pos.toPoint())
    for i in range(1, steps + 1):
        p = QPointF(60 + dx * i / steps, 35)
        ev = QMouseEvent(QEvent.MouseMove, p, scrubber.mapToGlobal(p), Qt.NoButton, Qt.LeftButton, mods)
        QApplication.sendEvent(scrubber, ev)
    QTest.mouseRelease(scrubber, Qt.LeftButton, mods, QPointF(60 + dx, 35).toPoint())
    QTest.qWait(100)


assert parse_time("10:20.4") == 620.4 and parse_time("620.4") == 620.4 and parse_time("x") is None
print("ok   time parsing")

# disabled state with no selection
assert not ed.scrub_in.isEnabled() and not ed.save_btn.isEnabled() and not ed.deselect_btn.isEnabled()
print("ok   no selection: values, Save and Clear disabled")

win.set_range(40.0, 42.4)
QTest.qWait(300)
assert ed.scrub_in.value() == 40.0 and ed.scrub_out.value() == 42.4 and ed.save_btn.isEnabled()
print("ok   selection shown in the Start/End fields; length", ed.scrub_len.value())

drag(ed.scrub_in, 50)            # 50 px * 10 ms
print(f"     drag Start +50 px -> {ed.clip.start:.3f}")
assert abs(ed.clip.start - 40.5) < 0.002, ed.clip.start
assert abs(ed.wave.sel_in - 40.5) < 0.002 and abs(ed.scrub_in.value() - 40.5) < 0.002
drag(ed.scrub_in, -30, Qt.ControlModifier)   # 30 px * 1 ms
print(f"     Ctrl-drag Start -30 px -> {ed.clip.start:.3f}")
assert abs(ed.clip.start - 40.47) < 0.002, ed.clip.start
drag(ed.scrub_out, 20, Qt.ShiftModifier)     # 20 px * 100 ms = 2 s
print(f"     Shift-drag End +20 px -> {ed.clip.end:.3f}")
assert abs(ed.clip.end - 44.4) < 0.002, ed.clip.end
drag(ed.scrub_in, 5000)                       # cannot pass the end marker
print(f"     drag Start far right -> {ed.clip.start:.3f} (end is {ed.clip.end:.3f})")
assert ed.clip.start <= ed.clip.end + 1e-9 and abs(ed.clip.start - ed.clip.end) < 0.002
drag(ed.scrub_in, -1500)
assert ed.clip.start <= ed.clip.end
print("ok   dragging: 10 ms/px, Ctrl 1 ms/px, Shift 100 ms/px, start never passes end")
print("     text follows the range:", repr(ed.clip.text))

# typed value
win.set_range(40.0, 42.4)
ed.scrub_in.mouseDoubleClickEvent(None)
assert ed.scrub_in._edit is not None
ed.scrub_in._edit.setText("0:40.250")
ed.scrub_in._edit.editingFinished.emit()
print(f"     typed 0:40.250 for Start (end is {ed.clip.end:.3f}) -> {ed.clip.start:.3f}  ")
assert abs(ed.clip.start - 40.25) < 0.002 and ed.clip.start <= ed.clip.end
win.set_range(40.0, 42.4)
ed.scrub_in.mouseDoubleClickEvent(None)
ed.scrub_in._edit.setText("0:39.9")  # 39.9
ed.scrub_in._edit.editingFinished.emit()
assert abs(ed.clip.start - 39.9) < 0.002, ed.clip.start
ed.scrub_out.mouseDoubleClickEvent(None)
ed.scrub_out._edit.setText("43")
ed.scrub_out._edit.editingFinished.emit()
assert abs(ed.clip.end - 43.0) < 0.002
ed.scrub_out.mouseDoubleClickEvent(None)
ed.scrub_out._edit.setText("45")
ed.scrub_out._edit.cancel_edit()          # what Esc does
ed.scrub_out._edit.editingFinished.emit()
assert abs(ed.clip.end - 43.0) < 0.002, "Esc should cancel the typed value"
print("ok   typed times (m:ss.mmm and seconds); Esc cancels")

# buttons
win.set_range(40.0, 42.4)
QTest.qWait(100)
mid = (ed.clip.start + ed.clip.end) / 2
drag(ed.scrub_len, 50)                       # 50 px * 10 ms = +0.5 s, split over both ends
assert abs(ed.scrub_len.value() - 2.9) < 0.005 and abs((ed.clip.start + ed.clip.end) / 2 - mid) < 0.002, \
    (ed.scrub_len.value(), ed.clip.start, ed.clip.end)
assert abs(ed.clip.start - 39.75) < 0.003 and abs(ed.clip.end - 42.65) < 0.003
drag(ed.scrub_len, -9000)                    # cannot shrink past the minimum
assert abs(ed.scrub_len.value() - 0.010) < 0.002 and ed.clip.start < ed.clip.end
ed.scrub_len.mouseDoubleClickEvent(None)
ed.scrub_len._edit.setText("1.5")
ed.scrub_len._edit.editingFinished.emit()
QTest.qWait(100)
assert abs(ed.scrub_len.value() - 1.5) < 0.002 and abs((ed.clip.start + ed.clip.end) / 2 - mid) < 0.003
win.set_range(0.5, 1.5)                      # near the start of the episode: slides instead of passing 0
ed.scrub_len.mouseDoubleClickEvent(None)
ed.scrub_len._edit.setText("4")
ed.scrub_len._edit.editingFinished.emit()
QTest.qWait(100)
assert ed.clip.start == 0.0 and abs(ed.clip.end - 4.0) < 0.002, (ed.clip.start, ed.clip.end)
print("ok   Length field: drag/type grows and shrinks the clip around its centre; stays inside the episode")
win.set_range(40.0, 42.4)
ed.set_tag("character", "voice1")
ed.save_btn.click()
QTest.qWait(200)
assert len(win.project.clips) == 1 and win.project.clips[0].tags["character"] == "voice1"
assert ed.clip.start is None and not ed.save_btn.isEnabled() and ed.clip.tags.get("character") == "voice1"
print("ok   Save to Library: clip stored, fields clear, character stays set")
win.set_range(50.0, 52.0)
ed.deselect_btn.click()
QTest.qWait(100)
assert ed.clip.start is None and len(win.project.clips) == 1
print("ok   Deselect clip: markers cleared, library unchanged")
win.clips.clip_selected.emit(win.project.clips[0])
QTest.qWait(200)
assert "Done" in ed.save_btn.text() and "— Editing" in ed.status.text() and ed.status.text().startswith("Clip Editor")
drag(ed.scrub_in, -20)       # edit the stored clip by dragging
assert abs(win.project.clips[0].start - 39.8) < 0.003, win.project.clips[0].start
print("ok   editing a saved clip: label switches to Done; dragging edits the stored clip")
ed.deselect_btn.click()

win.set_range(40.0, 42.4)
QTest.qWait(600)
if any(a.endswith('.png') for a in sys.argv[1:]):
    ed.grab().save(shot_arg())
win.project.save()
episode.with_name(episode.name + ".snapper.json").unlink(missing_ok=True)
print("EDITOR OK")
support.finish(win)
