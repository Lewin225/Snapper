"""Startup check for libmpv/ffmpeg (with the install command for the distribution) and the ffmpeg encoders that only the
scrub proxy (libx264) and MP3 export (libmp3lame) need, checked when those are used."""
import os, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SNAPPER_DATA", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from snapper import system_check
from snapper.theme import apply_system_theme
from snapper.main_window import MainWindow
from snapper.export import ExportSettings
from support import episode_arg, wait_until_ready

app = QApplication(sys.argv)
apply_system_theme(app)

# --- what is missing, and what to tell the user
assert system_check.missing_requirements() == [], "this environment has everything"
real_which = system_check.shutil.which
system_check.shutil.which = lambda name: None if name in ("ffmpeg", "ffprobe") else real_which(name)
assert system_check.missing_requirements() == ["ffmpeg", "ffprobe"]
system_check.shutil.which = real_which
sys.modules["mpv"], real_mpv = None, sys.modules["mpv"]
assert system_check.missing_requirements() == ["libmpv"]
sys.modules["mpv"] = real_mpv
for ids, cmd in ((("fedora",), "sudo dnf install mpv-libs ffmpeg"), (("ubuntu", "debian"), "sudo apt install libmpv2 ffmpeg"),
                 (("arch",), "sudo pacman -S mpv ffmpeg"), (("something",), "Install mpv's library")):
    system_check._os_release = lambda ids=ids: set(ids)
    assert cmd in system_check.install_hint(["libmpv", "ffmpeg"]), (ids, system_check.install_hint(["libmpv", "ffmpeg"]))
system_check._os_release = lambda: {"fedora"}
assert system_check.install_hint(["ffprobe"]).startswith("sudo dnf install ffmpeg") and "RPM Fusion" in system_check.install_hint(["ffmpeg"])
del system_check._os_release
import importlib; importlib.reload(system_check)
assert system_check.has_encoder("libx264") and system_check.has_encoder("libmp3lame") and not system_check.has_encoder("nonsense")
assert system_check.backend_dir("speech_backend").is_dir() and system_check.backend_dir("isolation_backend").is_dir()
print("ok   missing libmpv/ffmpeg are named, with the install command for the distribution; encoders are detected; backends found")

# --- startup: a message and a clean exit, no window
from snapper import __main__ as entry
shown = []
real_critical, real_missing = QMessageBox.critical, system_check.missing_requirements
QMessageBox.critical = staticmethod(lambda parent, title, text: shown.append((title, text)))
system_check.missing_requirements = lambda: ["libmpv", "ffmpeg"]
assert entry.main() == 1 and shown and "libmpv" in shown[0][1] and "ffmpeg" in shown[0][1] and "Snapper cannot start" == shown[0][0]
QMessageBox.critical, system_check.missing_requirements = real_critical, real_missing
print("ok   starting without libmpv/ffmpeg shows what to install and exits")

# --- an ffmpeg without libmp3lame / libx264, found out when they are used
win = MainWindow(episode_arg())
win.show()
wait_until_ready(win)
warned = []
QMessageBox.warning = staticmethod(lambda parent, title, text, *a, **k: warned.append((title, text)))
real_enc = system_check.encoders
system_check.encoders = lambda: frozenset({"pcm_s16le"})
win.project.set_export_settings(ExportSettings(output_dir=tempfile.mkdtemp(), format="mp3").to_json())
win.project.add(__import__("snapper.model", fromlist=["Clip"]).Clip(10.0, 12.0, "x", True, {}))
win.export_clips(force=True)
assert warned and "libmp3lame" in warned[0][1] and "WAV" in warned[0][1] and win.exporter.state(win.project.clips[0]) != "queued"
win.project.set_export_settings(ExportSettings(output_dir=tempfile.mkdtemp(), format="wav").to_json())
warned.clear()
win.export_clips(force=True)
assert not warned, "WAV export does not need it"
print("ok   MP3 export without libmp3lame says so (WAV still works)")

from snapper.export_dialog import ExportSettingsDialog
dlg = ExportSettingsDialog(win.project, win)
assert not warned, "opening the dialog does not warn"
dlg.format.setCurrentIndex(dlg.format.findData("mp3"))
dlg.format.activated.emit(dlg.format.currentIndex())
assert warned and "libmp3lame" in warned[-1][1] and dlg.format.toolTip()
print("ok   choosing MP3 in the export settings warns when this ffmpeg cannot write it")
system_check.encoders = real_enc

win.project.proxy_enabled = False
win._proxy_job = None
win.project.proxy_enabled = True
system_check.encoders = lambda: frozenset()
from snapper import media as _m
media_pp = _m.proxy_path(win.media_path)
media_pp.unlink(missing_ok=True)
win._use_proxy_or_original()
assert win._proxy_job is None and "libx264" in win.statusBar().currentMessage() and "original video" in win.statusBar().currentMessage()
print("ok   without libx264 there is no proxy job: a message, and the original video is used")
win.close()
print("SYSTEM CHECK OK")
