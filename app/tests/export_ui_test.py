"""Export from the UI: the library buttons, the settings pop-up, and a real export to a folder."""
import atexit, locale, os, shutil, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("SNAPPER_DATA", tempfile.mkdtemp())
WORK = Path(tempfile.mkdtemp())
atexit.register(shutil.rmtree, WORK, ignore_errors=True)   # decoded audio is hundreds of MB: always clean up
def mk() -> Path:
    return Path(tempfile.mkdtemp(dir=WORK))
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QFileDialog, QMessageBox

from snapper import media
from snapper.export import read_wav
from snapper.export_dialog import ExportSettingsDialog
from snapper.main_window import MainWindow
from snapper.model import Clip, Project
from snapper.theme import apply_system_theme
from support import wait_until_ready

episode, shot = Path(sys.argv[1]), sys.argv[2]
app = QApplication(sys.argv)
locale.setlocale(locale.LC_NUMERIC, "C")
apply_system_theme(app)
win = MainWindow(episode)
win.show()
wait_until_ready(win)
while not media.audio_path(episode, 0).exists():
    QTest.qWait(200)
QTest.qWait(500)
win.project.add_tag_type("emotion")
win.project.add_tag_type("overlap", "bool")

assert win.project.export_settings is None and not win.clips.export_btn.isEnabled()
assert "Export Settings" in win.clips.export_btn.toolTip() and win.clips.export_settings_btn.isEnabled()
print("ok   Export is disabled until the project has export settings; Export Settings is always available")

def add(a, b, text, **tags):
    return win.project.add(Clip(a, b, text, True, tags))
c1 = add(700.0, 702.417, "But, yeah, that might be fun.", character="Alastor", emotion="happy")
c2 = add(710.0, 712.0, "Second line", character="Husk", overlap=True)
c3 = add(720.0, 721.5, "Third line", character="Alastor")
assert not win.clips.export_btn.isEnabled(), "still no settings"

out = mk() / "exports"
dlg = ExportSettingsDialog(win.project, win)
ok = dlg.buttons.button(QDialogButtonBox.Ok)
assert dlg.folder.isReadOnly() and not ok.isEnabled() and "Choose" in dlg.folder_msg.text(), "the folder must be chosen first"
dlg.folder.setText(str(out)); dlg._refresh()
assert not ok.isEnabled() and "does not exist" in dlg.folder_msg.text()
out.mkdir()
dlg.folder.setText(str(out)); dlg._refresh()
assert ok.isEnabled()
dlg.template.setText("{character}/{n}")
assert not ok.isEnabled() and dlg.template_msg.text(), "path separators in the file name are refused"
dlg.template.setText("{nope}")
assert not ok.isEnabled() and "Unknown field" in dlg.template_msg.text()
dlg.template.setText("{character}_{n}_{text}")
assert ok.isEnabled()
dlg.folder_list.item(0).setCheckState(Qt.Checked)
dlg.folder_list.setCurrentRow(1); dlg._move(-1)
dlg.folder_list.item(0).setCheckState(Qt.Checked)
s = dlg.settings()
assert s.folder_tags == ["emotion", "character"] and s.output_dir == str(out), (s.folder_tags, s.output_dir)
assert dlg.example.text().startswith("First clip: happy"), dlg.example.text()
dlg.show(); dlg.grab().save(shot.replace(".png", "_dialog.png"))
dlg.accept()
win.project.set_export_settings(dlg.settings().to_json())
assert win.clips.export_btn.isEnabled()
print("ok   settings pop-up: export folder (must exist), template validation, folder order, live example")

# --- Export returns at once; the library shows each clip's state
def label(clip):
    row = win.project.clips.index(clip)
    return win.clips.model.index(row, win.clips.model.columns().index("Export")).data()
assert all(label(c) == "" for c in (c1, c2, c3)), "never exported: blank"
warned = []
QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2:]))
win.clips.export_btn.click()
assert win.clips.export_btn.isEnabled(), "Export stays available while an export runs"
assert label(c1) in ("⋯ Queued", "◐ Exporting", "✓ Exported")
seen = set()
for _ in range(100):
    QTest.qWait(50)
    seen.update(label(c) for c in (c1, c2, c3))
    if all(label(c) == "✓ Exported" for c in (c1, c2, c3)):
        break
assert all(label(c) == "✓ Exported" for c in (c1, c2, c3)), [label(c) for c in (c1, c2, c3)]
files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.wav"))
assert files == ["_none/Alastor/Alastor_003_Third line.wav", "_none/Husk/Husk_002_Second line.wav",
                 "happy/Alastor/Alastor_001_But, yeah, that might be fun.wav"], files
wf = media.open_pcm(media.audio_path(episode, 0), 1, 16)
for c in (c1, c2, c3):
    w = read_wav(Path(c.export_path))
    assert np.array_equal(w["frames"], wf[int(round(c.start * 44100)):int(round(c.end * 44100))])
    assert w["info"]["ICMT"] == c.text and w["tags"]["character"] == c.tags["character"]
assert read_wav(Path(c2.export_path))["tags"] == {"character": "Husk", "overlap": True}
assert not warned and "Export finished" in win.statusBar().currentMessage() and "export" not in win._job_state
print("ok   Export button: non-blocking; library goes queued/exporting -> '✓ Exported'; samples identical to the waveform")

# --- editing a clip marks it Changed; Export then writes only that clip and tidies up the old file
mtimes = {c.id: Path(c.export_path).stat().st_mtime_ns for c in (c1, c3)}
old_path = Path(c2.export_path)
c2.tags["character"] = "Alastor"; c2.tags["emotion"] = "sad"
win.project.touch(c2)
assert label(c2) == "● Changed" and label(c1) == "✓ Exported", (label(c2), label(c1))
win.clips.export_btn.click()
for _ in range(100):
    QTest.qWait(50)
    if label(c2) == "✓ Exported":
        break
assert label(c2) == "✓ Exported" and Path(c2.export_path).exists()
assert Path(c2.export_path).relative_to(out).as_posix() == "sad/Alastor/Alastor_002_Second line.wav", c2.export_path
assert not old_path.exists() and not old_path.parent.exists(), "the old file and its now-empty folder are removed"
assert all(Path(c.export_path).stat().st_mtime_ns == mtimes[c.id] for c in (c1, c3)), "other clips untouched"
win.clips.export_btn.click()
assert "already exported" in win.statusBar().currentMessage()
print("ok   a changed clip shows '● Changed'; Export writes only it, moves it, removes the old file and empty folder")

# --- a clip that cannot be written fails visibly, others carry on
bad = add(99999.0, 99999.5, "Nowhere", character="Husk")
win.clips.export_btn.click()
for _ in range(100):
    QTest.qWait(50)
    if label(bad) == "✗ Failed":
        break
assert label(bad) == "✗ Failed"
row = win.project.clips.index(bad)
tip = win.clips.model.index(row, win.clips.model.columns().index("Export")).data(Qt.ToolTipRole)
assert "no audio" in tip, tip
win.project.remove(bad)
print("ok   an unwritable clip shows '✗ Failed' with the reason")

# --- changing the settings marks everything Changed; a stereo 24-bit export decodes first, without blocking
s = win.project.export_settings.copy(); s.update(channels=2, bit_depth=24, text_field="title", embed_tags=False)
win.project.set_export_settings(s)
assert all(label(c) == "● Changed" for c in (c1, c2, c3))
win.clips.export_btn.click()
assert win.clips.export_btn.isEnabled() and label(c1) == "⋯ Queued"
seen_pcm = False
for _ in range(900):
    QTest.qWait(100)
    seen_pcm = seen_pcm or "pcm" in win.status_jobs._rows
    if all(label(c) == "✓ Exported" for c in (c1, c2, c3)):
        break
assert seen_pcm and all(label(c) == "✓ Exported" for c in (c1, c2, c3))
w = read_wav(Path(c2.export_path))
assert (w["channels"], w["bits"], w["rate"]) == (2, 24, 44100) and w["info"] == {"INAM": "Second line"} and w["tags"] is None
print("ok   new settings: clips show Changed; stereo 24-bit audio is prepared in the background, then exported")

# --- a missing export folder is reported, not crashed on
import shutil
win.project.set_export_settings({**win.project.export_settings, "output_dir": str(out / "gone")})
win.clips.export_btn.click()
assert not win.clips.export_btn.isEnabled() and "export folder" in win.clips.export_btn.toolTip()
win.project.set_export_settings({**win.project.export_settings, "output_dir": str(out)})

# --- tags can't hold path characters
box = win.editor.tag_boxes["character"]
box.lineEdit().clear()
QTest.keyClicks(box.lineEdit(), 'Al/a:s*t?"o<r>|\\')
assert box.lineEdit().text() == "Alastor", box.lineEdit().text()
print("ok   the tag box refuses characters a path can't hold")

# --- library buttons share one row; the panes have titles
from PySide6.QtWidgets import QLabel
ys = {b.mapTo(win, b.rect().center()).y() for b in (win.clips.play, win.clips.delete, win.clips.export_settings_btn, win.clips.export_btn)}
assert max(ys) - min(ys) < 4, ys
titles = {l.text().split(" — ")[0] for l in win.findChildren(QLabel) if l.text().split(" — ")[0] in ("Transcript", "Playback", "Library", "Clip Editor")}
assert titles == {"Transcript", "Playback", "Library", "Clip Editor"}, titles
print("ok   Play/Delete/Export Settings/Export are on one row; Transcript, Playback, Library and Clip Editor have titles")

# --- auto export: ticking it exports what is outstanding, then new and changed clips follow by themselves
def waitfor(cond, n=150):
    for _ in range(n):
        QTest.qWait(100)
        if cond():
            return True
    return False
assert win.clips.auto_export.isEnabled() and not win.clips.auto_export.isChecked() and not win.project.auto_export
win.project.set_export_settings({**win.project.export_settings, "channels": 1, "bit_depth": 16})
win.clips.auto_export.click()
assert win.project.auto_export
assert waitfor(lambda: all(label(c) == "✓ Exported" for c in (c1, c2, c3))), [label(c) for c in (c1, c2, c3)]
new = add(740.0, 741.0, "Auto one", character="Husk")
assert waitfor(lambda: label(new) == "✓ Exported"), label(new)
assert Path(new.export_path).exists() and Path(new.export_path).name == "Husk_003_Auto one.wav".replace("003", "%03d" % new.id)
old = new.export_path
new.text = "Auto two"; new.end = 741.5; win.project.touch(new)
assert waitfor(lambda: label(new) == "✓ Exported" and new.export_path != old), (label(new), new.export_path)
assert not Path(old).exists()
bad = add(99999.0, 99999.5, "Nowhere", character="Husk")
assert waitfor(lambda: label(bad) == "✗ Failed")
tries = []
orig = win.exporter.submit
win.exporter.submit = lambda *a, **k: (tries.append(1), orig(*a, **k))[1]
win.project.touch(c1); QTest.qWait(1500)     # unrelated change: the failed clip is not retried
assert not tries and label(bad) == "✗ Failed", tries
win.exporter.submit = orig
bad.start, bad.end = 700.0, 701.0; win.project.touch(bad)   # edited: now it is tried again, and works
assert waitfor(lambda: label(bad) == "✓ Exported")
win.project.remove(bad)
win.clips.auto_export.click()
assert not win.project.auto_export
late = add(750.0, 751.0, "Not auto", character="Husk")
QTest.qWait(1500)
assert label(late) == "", label(late)
win.project.remove(late)
win.project.save(); assert '"auto_export": false' in Path(win.project.path).read_text()
win.clips.auto_export.click()   # leave it on: saved with the project
QTest.qWait(300)
print("ok   Auto export: exports outstanding clips when ticked, then new and edited clips by itself; failed clips retry only after an edit; off again does nothing")

# --- the states survive closing and reopening; a deleted file shows as not exported
win.project.save()
Path(c3.export_path).unlink()
proj = win.project.path
win2 = MainWindow(proj)
win2.show()
win.close()
wait_until_ready(win2)
by_id = {c.id: c for c in win2.project.clips}
def label2(cid):
    row = win2.project.clips.index(by_id[cid])
    return win2.clips.model.index(row, win2.clips.model.columns().index("Export")).data()
assert label2(c1.id) == "✓ Exported" and label2(c2.id) == "✓ Exported" and label2(c3.id) == "", (label2(c1.id), label2(c3.id))
assert not list(media.cache_dir(episode).glob("export_*.pcm")), "temporary export audio removed on close"
print("ok   export state is saved with the project; deleted files show as not exported; temporary audio removed")
win2.close()
print("EXPORT UI OK")
