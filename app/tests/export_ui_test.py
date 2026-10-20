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
    win.project.add(Clip(a, b, text, True, tags))
add(700.0, 702.417, "But, yeah, that might be fun.", character="Alastor", emotion="happy")
add(710.0, 712.0, "Second line", character="Husk", overlap=True)
add(720.0, 721.5, "Third line", character="Alastor")
assert not win.clips.export_btn.isEnabled(), "still no settings"

dlg = ExportSettingsDialog(win.project, win)
ok = dlg.buttons.button(QDialogButtonBox.Ok)
dlg.template.setText("{character}/{n}")
assert not ok.isEnabled() and dlg.template_msg.text(), "path separators in the file name are refused"
dlg.template.setText("{nope}")
assert not ok.isEnabled() and "Unknown field" in dlg.template_msg.text()
dlg.template.setText("{character}_{n}_{text}")
assert ok.isEnabled()
dlg.folder_list.item(0).setCheckState(Qt.Checked)          # character
dlg.folder_list.setCurrentRow(1); dlg._move(-1)            # emotion above character
dlg.folder_list.item(0).setCheckState(Qt.Checked)
s = dlg.settings()
assert s.folder_tags == ["emotion", "character"], s.folder_tags
assert dlg.example.text().startswith("First clip: happy"), dlg.example.text()
dlg.show(); dlg.grab().save(shot.replace(".png", "_dialog.png"))
dlg.accept()
win.project.set_export_settings(dlg.settings().to_json())
assert win.clips.export_btn.isEnabled()
print("ok   settings pop-up: template validation, folder order, live example; saving enables Export")

# --- a mono 16-bit export: no decoding, straight from the waveform audio
out = mk()
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(out))
warned = []
QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2:]))
win.clips.export_btn.click()
for _ in range(100):
    QTest.qWait(100)
    if win._export_worker is None and list(out.rglob("*.wav")):
        break
files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.wav"))
assert files == ["_none/Alastor/Alastor_003_Third line.wav", "_none/Husk/Husk_002_Second line.wav",
                 "happy/Alastor/Alastor_001_But, yeah, that might be fun.wav"], files
wf = media.open_pcm(media.audio_path(episode, 0), 1, 16)
for c in win.project.clips:
    f = next(p for p in out.rglob("*.wav") if f"_{c.text}" in p.name)
    w = read_wav(f)
    assert np.array_equal(w["frames"], wf[int(round(c.start * 44100)):int(round(c.end * 44100))])
    assert w["info"]["ICMT"] == c.text and w["tags"]["character"] == c.tags["character"]
assert read_wav(out / "_none/Husk/Husk_002_Second line.wav")["tags"] == {"character": "Husk", "overlap": True}
assert not warned and win.statusBar().currentMessage().startswith("Exported 3 clips")
print("ok   Export button: 3 WAVs in tag folders, samples identical to the waveform, text and tags embedded")

# --- stereo 24-bit: needs a decode first, shown as a job; the temporary file is removed afterwards
s = win.project.export_settings.copy(); s.update(channels=2, bit_depth=24, text_field="title", embed_tags=False)
win.project.set_export_settings(s)
out2 = mk()
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(out2))
win.clips.export_btn.click()
seen_pcm = False
for _ in range(900):
    QTest.qWait(100)
    seen_pcm = seen_pcm or "pcm" in win.status_jobs._rows
    if win._export_worker is None and "pcm" not in win._job_state and list(out2.rglob("*.wav")):
        break
assert seen_pcm, "a 'Preparing audio' bar shows while the stereo audio is decoded"
w = read_wav(next(out2.rglob("Husk*.wav")))
assert (w["channels"], w["bits"], w["rate"]) == (2, 24, 44100) and w["info"] == {"INAM": "Second line"} and w["tags"] is None
assert not media.export_pcm_path(episode, 0, 2, 44100, 24).exists(), "temporary decode removed"
print("ok   stereo 24-bit export: audio prepared in the background, files written, temporary decode removed")

# --- tags can't hold path characters
box = win.editor.tag_boxes["character"]
box.lineEdit().clear()
QTest.keyClicks(box.lineEdit(), 'Al/a:s*t?"o<r>|\\')
assert box.lineEdit().text() == "Alastor", box.lineEdit().text()
print("ok   the tag box refuses characters a path can't hold")

win.project.save()
assert Project.from_file(win.project.path).export_settings["bit_depth"] == 24
win.close()
print("EXPORT UI OK")
