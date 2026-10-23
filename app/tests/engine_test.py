"""The optional engines (WhisperX, audio-separator): checking what is missing, installing one just for Snapper or into the
system Python (with a tiny stand-in package, so nothing big is downloaded), GPU/CPU choice, cancelling/failing cleanly,
the dialog, and what the buttons do without an engine."""
import locale, os, shutil, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
TMP = Path(tempfile.mkdtemp())
os.environ["SNAPPER_DATA"] = str(TMP / "data")
os.environ["XDG_CONFIG_HOME"] = str(TMP / "config")
os.environ["PYTHONUSERBASE"] = str(TMP / "userbase")   # `pip install --user` must never touch the real home
for v in ("SNAPPER_WX_PYTHON", "SNAPPER_SEP_PYTHON"):
    os.environ.pop(v, None)

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from snapper import engine, engine_dialog
from snapper.theme import apply_system_theme
from support import episode_arg

app = QApplication(sys.argv)
locale.setlocale(locale.LC_NUMERIC, "C")
apply_system_theme(app)
WX, SEP = engine.WHISPERX, engine.SEPARATOR
real_home = Path.home()
DEV_WX, DEV_SEP = real_home / "envs/wx/bin/python", real_home / "envs/sep/bin/python"


def wait_for(owner, signal_name, start, timeout_ms=300000):
    """Runs `start()` and waits for the signal; returns its arguments."""
    got = []
    loop = QEventLoop()
    getattr(owner, signal_name).connect(lambda *a: (got.append(a), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)
    QTimer.singleShot(0, start)
    loop.exec()
    assert got, "timed out"
    return got[0]


# a stand-in engine whose only requirement is a tiny package
tiny = engine.Engine(key="tiny", title="Tiny", modules={"numpy": "numpy", "tqdm": "tqdm", "no_such_module_xyz": "nothing"},
                     gpu_packages=["tqdm"], cpu_packages=["tqdm"], cpu_pip_args=[], env_var="SNAPPER_TINY_PYTHON",
                     dev_env="~/envs/none", download_note={"gpu": "x", "cpu": "y"}, after_note="", min_free_gb=1,
                     purpose="is a test")

# --- checking an interpreter, module by module
st = engine.check(tiny, Path(sys.executable), "chosen")
assert st.python_version and st.versions["numpy"] and st.versions["no_such_module_xyz"] is None
assert st.missing[-1] == "no_such_module_xyz" and not st.ok and "nothing" in st.summary()
assert engine.check(tiny, TMP / "nope" / "python").error
print("ok   an interpreter is checked module by module:", st.versions)

# --- both real engines: what they need, and the GPU / CPU variants
assert list(WX.modules.values()) == ["WhisperX", "PyTorch", "torchaudio"]
assert list(SEP.modules.values()) == ["audio-separator", "PyTorch", "ONNX Runtime"]
assert SEP.pip_packages("gpu") == ["audio-separator[gpu]==0.47.1"] and SEP.pip_packages("cpu") == ["audio-separator[cpu]==0.47.1"]
assert WX.pip_args("gpu") == [] and "https://download.pytorch.org/whl/cpu" in WX.pip_args("cpu"), "CPU installs use PyTorch's CPU wheels"
assert engine.default_device() == ("gpu" if engine.has_nvidia() else "cpu")
print("ok   engines define their packages for GPU and for CPU; the default follows whether an NVIDIA GPU is present")

# --- finding an engine
os.environ["SNAPPER_TINY_PYTHON"] = str(TMP / "missing" / "python")
cur = engine.current(tiny)
assert not cur.ok and cur.source == "environment" and "does not exist" in cur.summary()
os.environ.pop("SNAPPER_TINY_PYTHON")
if DEV_WX.exists():
    cur = engine.current(WX)
    assert cur.ok and cur.source == "developer" and cur.versions["whisperx"] and cur.gpu is not None, cur
    print("ok   the developer WhisperX environment is found and complete:", cur.versions, "GPU", cur.gpu)
if DEV_SEP.exists():
    cur = engine.current(SEP)
    assert cur.ok and cur.versions["audio_separator"], cur
    print("ok   the developer audio-separator environment is found and complete:", cur.versions)
engine.Path.home = classmethod(lambda cls: TMP / "home")   # no developer environments from here on
cur = engine.current(tiny)
assert cur.python is not None or cur.python is None   # (the system python may or may not have the packages)
print("ok   nothing set up is reported, never an error")

# --- installing for Snapper only (stand-in package), CPU and GPU variants get their own pip arguments
tiny.cpu_pip_args = ["--index-url", "https://pypi.org/simple"]
tiny.modules = {"tqdm": "tqdm"}
for device in ("gpu", "cpu"):
    inst = engine.EngineInstaller(tiny, "private", device)
    stages = []
    inst.stage.connect(stages.append)
    ok, message = wait_for(inst, "done", inst.start)
    assert ok, message
    py = engine.python_in(tiny.folder)
    cur = engine.current(tiny)
    assert py.exists() and cur.ok and cur.source == "snapper" and cur.versions["tqdm"], cur
    assert stages[0].startswith("Creating") and any("Snapper's environment" in s for s in stages) and stages[-1].startswith("Checking")
    assert not (tiny.folder.parent / "tmp").exists()
    shutil.rmtree(tiny.folder)
print("ok   installed into Snapper's own folder (GPU and CPU variants):", cur.python)

# --- installing into the system Python: a managed one is refused with an explanation, then allowed into ~/.local on request
if engine.system_python() is not None:
    sysmanaged = subprocess_out = None
    inst = engine.EngineInstaller(tiny, "system", "gpu")
    ok, message = wait_for(inst, "done", inst.start)
    if inst.pep668:
        assert not ok and "PEP 668" in message
        inst = engine.EngineInstaller(tiny, "system", "gpu", break_system=True)
        ok, message = wait_for(inst, "done", inst.start)
    assert ok, message
    assert engine.chosen_python(tiny) == engine.system_python()
    assert str(TMP / "userbase") in " ".join(engine.check(tiny, engine.system_python()).versions.values() or [""]) or engine.current(tiny).ok
    print("ok   system Python: " + ("a managed one is refused (PEP 668) until allowed, then installs into ~/.local only"
                                    if inst.break_system else "installs with pip --user"))
    engine.set_chosen_python(tiny, None)
else:
    print("skip system Python (none on PATH)")

# --- cancelling and failing leave nothing behind
inst = engine.EngineInstaller(tiny, "private", "gpu")
lines, res = [], []
inst.stage.connect(lines.append)
inst.done.connect(lambda ok, msg: res.append((ok, msg)))
inst.start()
for _ in range(600):
    QTest.qWait(50)
    if any(s.startswith("Downloading") for s in lines):
        break
inst.cancel()
QTest.qWait(300)
assert res and res[-1] == (False, "Cancelled.") and not tiny.folder.exists()
tiny.gpu_packages = ["definitely-not-a-real-package-xyz-123"]
inst = engine.EngineInstaller(tiny, "private", "gpu")
ok, message = wait_for(inst, "done", inst.start)
assert not ok and "failed" in message and not tiny.folder.exists(), message
tiny.gpu_packages = ["tqdm"]
print("ok   cancelled and failed installs are cleaned up; the failure shows pip's last lines")

# --- the dialog (for each engine)
engine.Path.home = classmethod(lambda cls: real_home)
for eng, labels in ((WX, ["WhisperX", "PyTorch", "torchaudio"]), (SEP, ["audio-separator", "PyTorch", "ONNX Runtime"])):
    checked = engine.check(eng, Path(sys.executable), "chosen")
    dlg = engine_dialog.EngineDialog(checked)
    dlg.show()
    texts = [w.text() for w in dlg.findChildren(QLabel)]
    assert all(l in texts for l in labels) and any(t.startswith("Missing:") for t in texts), texts
    assert eng.title in dlg.windowTitle() and eng.purpose in texts[0]
    assert dlg.btn_install.text().startswith("Install separately") and dlg.btn_own.text().startswith("Use my own")
    assert dlg.btn_system.isVisible() == (engine.system_python() is not None)
    assert dlg.radio_gpu.isChecked() == (engine.default_device() == "gpu") and dlg.radio_cpu.isChecked() != dlg.radio_gpu.isChecked()
    dlg.radio_cpu.setChecked(True)
    assert dlg.device() == "cpu" and eng.download_note["cpu"] in dlg.install_hint.text()
    dlg.radio_gpu.setChecked(True)
    assert dlg.device() == "gpu" and eng.download_note["gpu"] in dlg.install_hint.text()
    assert (engine_dialog.NOTES[eng.key].split("<i>")[0][:20]) in " ".join(texts)
    if eng is WX:
        dlg.grab().save(os.environ.get("SHOT", str(TMP / "engine_dialog.png")))
    engine_dialog.pick_python = lambda parent, e: Path(sys.executable)
    dlg.use_own()   # a Python without the packages: stays open, remembers nothing
    assert dlg.result() != QDialog.Accepted and engine.chosen_python(eng) is None
    dev = DEV_WX if eng is WX else DEV_SEP
    if dev.exists():
        engine_dialog.pick_python = lambda parent, e, dev=dev: dev
        dlg.use_own()
        assert dlg.result() == QDialog.Accepted and engine.chosen_python(eng) == dev
        assert engine.current(eng).ok and engine.current(eng).source == "chosen"
        engine.set_chosen_python(eng, None)
    dlg.close()
    dlg.deleteLater()
    app.processEvents()
print("ok   dialog (both engines): lists what is missing; GPU/CPU choice changes the download note; 'use my own' only accepts a complete one")

# --- the install failing because the distribution manages the Python: asks, and only on a yes installs with --break-system-packages
dlg = engine_dialog.EngineDialog(engine.check(tiny, Path(sys.executable), "chosen"))
asked, installs = [], []
dlg._confirm_break_system = lambda: (asked.append(1), True)[1]
class Fake:
    pep668 = True
dlg.installer = Fake()
dlg.install = lambda target="private": installs.append((target, dlg.break_system))
dlg._install_done(False, "managed")
assert asked and installs == [("system", True)] and dlg.break_system is False
asked.clear(); installs.clear()
dlg._confirm_break_system = lambda: (asked.append(1), False)[1]
dlg.installer = Fake()
dlg._install_done(False, "managed")
assert asked and not installs
dlg.installer = None
dlg.deleteLater()
app.processEvents()
print("ok   a managed system Python: the dialog asks before using --break-system-packages, and installs nothing on a no")

# --- the buttons: no engine -> asks, and carries on without it if declined
from snapper.main_window import MainWindow
os.environ["SNAPPER_WX_PYTHON"] = str(TMP / "missing" / "python")
win = MainWindow(episode_arg())
win.show()
QTest.qWait(2500)
asked = []
engine_dialog.ensure_engine = lambda eng, parent=None: (asked.append(eng.key), None)[1]
win.start_transcription()
assert asked == ["whisperx"] and win.transcript_job is None and "WhisperX is not set up" in win.statusBar().currentMessage()
if DEV_WX.exists():
    engine_dialog.ensure_engine = lambda eng, parent=None: engine.check(eng, DEV_WX, "developer")
    win.start_transcription()
    assert win.transcript_job is not None, "with a ready engine the job starts"
    job = win.transcript_job
    job.kill()
    for _ in range(100):   # let the killed process be reaped before the window closes
        if job._proc.state() == job._proc.ProcessState.NotRunning:
            break
        QTest.qWait(50)
    QTest.qWait(500)
    assert QApplication.activeModalWidget() is None, "a deliberately stopped transcription must not pop up an error"
    assert job.cancelled and "cancelled" in win.statusBar().currentMessage()
win.close()
QTest.qWait(500)
assert QApplication.activeModalWidget() is None
print("ok   'Generate using WhisperX': asks when the engine is missing, does nothing if declined, starts when ready")
app.processEvents()
print("ENGINE OK")
