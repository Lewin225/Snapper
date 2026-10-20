"""The WhisperX engine: checking what is missing, installing one for Snapper (with a tiny stand-in package, so nothing
big is downloaded), cancelling/failing cleanly, the dialog, and what "Generate using WhisperX" does without one."""
import locale, os, shutil, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = Path(tempfile.mkdtemp())
os.environ["SNAPPER_DATA"] = str(TMP / "data")
os.environ["XDG_CONFIG_HOME"] = str(TMP / "config")
os.environ.pop("SNAPPER_WX_PYTHON", None)

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from snapper import engine, engine_dialog
from snapper.theme import apply_system_theme
from support import episode_arg

app = QApplication(sys.argv)
locale.setlocale(locale.LC_NUMERIC, "C")
apply_system_theme(app)
DEV = Path.home() / "envs/wx/bin/python"
real_home = Path.home()


def wait_for(signal_owner, signal_name, start, timeout_ms=240000):
    """Runs `start()` and waits for the signal; returns its arguments."""
    got = []
    loop = QEventLoop()
    getattr(signal_owner, signal_name).connect(lambda *a: (got.append(a), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)
    QTimer.singleShot(0, start)
    loop.exec()
    assert got, "timed out"
    return got[0]


# --- checking an interpreter
engine.REQUIRED = ["numpy", "PySide6", "no_such_module_xyz"]
st = engine.check(Path(sys.executable), "chosen")
assert st.python_version and st.versions["numpy"] and st.versions["PySide6"] and st.versions["no_such_module_xyz"] is None
assert st.missing == ["no_such_module_xyz"] and not st.ok and st.gpu is None and "no_such_module_xyz" in st.summary()
nothing = engine.check(TMP / "nope" / "python")
assert nothing.error and not nothing.ok
print("ok   an interpreter is checked module by module:", {k: v for k, v in st.versions.items()})

# --- finding the engine
engine.REQUIRED = ["whisperx", "torch", "torchaudio"]
os.environ["SNAPPER_WX_PYTHON"] = str(TMP / "missing" / "python")
cur = engine.current()
assert not cur.ok and cur.source == "environment" and "does not exist" in cur.summary()
os.environ.pop("SNAPPER_WX_PYTHON")
if DEV.exists():
    cur = engine.current()
    assert cur.ok and cur.source == "developer" and cur.versions["whisperx"] and cur.versions["torch"] and cur.versions["torchaudio"], cur
    print("ok   the developer environment is found and complete:", {k: v for k, v in cur.versions.items()}, "GPU", cur.gpu)
Path.home = classmethod(lambda cls: TMP / "home")          # no developer environment from here on
cur = engine.current()
assert cur.python is None and "no Python environment" in cur.summary()
print("ok   nothing set up: reported as such")

# --- installing for Snapper only (stand-in package)
engine.PACKAGES, engine.REQUIRED = ["tqdm"], ["tqdm"]
inst = engine.EngineInstaller()
stages = []
inst.stage.connect(stages.append)
ok, message = wait_for(inst, "done", inst.start)
assert ok, message
py = engine.python_in(engine.ENGINE_DIR)
cur = engine.current()
assert py.exists() and cur.ok and cur.source == "snapper" and cur.versions["tqdm"], cur
assert stages[0].startswith("Creating") and any(s.startswith("Downloading") for s in stages) and stages[-1].startswith("Checking")
assert not (engine.ENGINE_DIR.parent / "tmp").exists(), "pip's scratch folder is removed"
print("ok   installed into Snapper's own folder:", cur.python, cur.versions)
shutil.rmtree(engine.ENGINE_DIR)

# --- cancelling and failing leave nothing behind
inst = engine.EngineInstaller()
lines = []
inst.stage.connect(lines.append)
res = []
inst.done.connect(lambda ok, msg: res.append((ok, msg)))
inst.start()
for _ in range(600):
    QTest.qWait(50)
    if any(s.startswith("Downloading") for s in lines):
        break
inst.cancel()
QTest.qWait(300)
assert res and res[-1] == (False, "Cancelled.") and not engine.ENGINE_DIR.exists(), (res, engine.ENGINE_DIR.exists())
engine.PACKAGES = ["definitely-not-a-real-package-xyz-123"]
inst = engine.EngineInstaller()
ok, message = wait_for(inst, "done", inst.start)
assert not ok and "failed" in message and not engine.ENGINE_DIR.exists(), message
print("ok   cancelled and failed installs are cleaned up; the failure shows pip's last lines")
engine.PACKAGES = ["tqdm"]

# --- the dialog
engine.PACKAGES, engine.REQUIRED = ["tqdm"], ["whisperx", "torch", "torchaudio"]
Path.home = classmethod(lambda cls: real_home)
checked = engine.check(Path(sys.executable), "chosen")
dlg = engine_dialog.EngineDialog(checked)
dlg.show()
texts = [w.text() for w in dlg.findChildren(QLabel)]
assert "Missing: whisperx, torch, torchaudio." in texts and texts.count("missing") == 3 and "WhisperX" in texts and "PyTorch" in texts
assert dlg.btn_install.text().startswith("Install separately") and dlg.btn_own.text().startswith("Use my own")
assert any("Load from video" in t for t in texts), "tells the user subtitles work without it"
dlg.grab().save(os.environ.get("SHOT", str(TMP / "engine_dialog.png")))
# "use my own" with an interpreter that lacks things: stays open and says what is missing
engine_dialog.pick_python = lambda parent: Path(sys.executable)
dlg.use_own()
assert dlg.result() != QDialog.Accepted and dlg.isVisible() and engine.chosen_python() is None
# ... and with a complete one: accepted and remembered
if DEV.exists():
    engine_dialog.pick_python = lambda parent: DEV
    dlg.use_own()
    assert dlg.result() == QDialog.Accepted and engine.chosen_python() == DEV
    cur = engine.current()
    assert cur.ok and cur.source == "chosen"
    engine.set_chosen_python(None)
dlg.close()
print("ok   dialog: lists what is missing; 'use my own' rejects an incomplete one and remembers a complete one")

# --- the button: no engine -> asks, and carries on without it if declined
from snapper.main_window import MainWindow
os.environ["SNAPPER_WX_PYTHON"] = str(TMP / "missing" / "python")
win = MainWindow(episode_arg())
win.show()
QTest.qWait(2500)
asked = []
engine_dialog.ensure_engine = lambda parent=None: (asked.append(1), None)[1]
win.start_transcription()
assert asked and win.transcript_job is None and "WhisperX is not set up" in win.statusBar().currentMessage()
if DEV.exists():
    engine_dialog.ensure_engine = lambda parent=None: engine.check(DEV, "developer")
    win.start_transcription()
    assert win.transcript_job is not None, "with a ready engine the job starts"
    win.transcript_job.kill()
    QTest.qWait(500)
win.close()
print("ok   'Generate using WhisperX': asks when the engine is missing, does nothing if declined, starts when ready")
print("ENGINE OK")
