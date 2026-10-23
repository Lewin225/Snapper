"""Vocal isolation end to end, with the real audio-separator model: the Audio menu, the engine check, isolating a 100 s excerpt
in windows (with crossfaded seams), cancelling, the per-clip Original/Isolated switch (waveform, playback track, V key),
saving it in the project, and exporting a clip that is cut from the isolated audio.

Needs an audio-separator environment (SNAPPER_SEP_PYTHON, default ~/envs/sep) and, the first time, network access to
download the model (kept in SNAPPER_MODELS_DIR, default ~/.cache/snapper-models)."""
import atexit, locale, os, shutil, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
WORK = Path(tempfile.mkdtemp())
atexit.register(shutil.rmtree, WORK, ignore_errors=True)
os.environ["SNAPPER_DATA"] = str(WORK / "data")
os.environ["SNAPPER_CACHE"] = str(WORK / "cache")
os.environ["XDG_CONFIG_HOME"] = str(WORK / "config")
os.environ.setdefault("SNAPPER_SEP_PYTHON", str(Path.home() / "envs/sep/bin/python"))
os.environ.setdefault("SNAPPER_MODELS_DIR", str(Path.home() / ".cache/snapper-models"))

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from snapper import engine, isolation, media
from snapper.export import ExportSettings, read_wav
from snapper.main_window import MainWindow
from snapper.model import Clip, Project
from snapper.theme import apply_system_theme
from support import VIDEO, shot_arg, wait_until_ready

shot = shot_arg("snapper_isolation.png")
app = QApplication(sys.argv)
locale.setlocale(locale.LC_NUMERIC, "C")
apply_system_theme(app)
assert Path(os.environ["SNAPPER_SEP_PYTHON"]).exists(), "needs an audio-separator environment (see the docstring)"

# a 100 s excerpt: two windows' worth, so there is a crossfaded seam to check
episode = WORK / "excerpt.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-ss", "20", "-t", "100", "-i", str(VIDEO), "-map", "0:v", "-map", "0:a", "-c", "copy",
                str(episode)], check=True)
win = MainWindow(episode)
win.show()
wait_until_ready(win)
while not media.audio_path(episode, 0).exists():
    QTest.qWait(200)
QTest.qWait(500)

def wait(cond, what, ms=400000):
    for _ in range(ms // 100):
        if cond():
            return
        QTest.qWait(100)
    raise AssertionError("timed out: " + what)

# --- before: nothing isolated, the switch explains itself
iso_btn, orig_btn = win.editor.source_btns["isolated"], win.editor.source_btns["original"]
assert orig_btn.isChecked() and not iso_btn.isChecked() and not win.isolated_ready()
assert "No isolated audio yet" in iso_btn.toolTip()
audio_menu = next(a.menu() for a in win.menuBar().actions() if a.text() == "&Audio")
assert [a.text() for a in audio_menu.actions()] == ["Isolate vocals using audio-separator", "Load custom audio replacement…", "Cancel isolation",
                                                     "Isolation model…", "Remove isolated audio"], [a.text() for a in audio_menu.actions()]
win._update_audio_menu()
assert win.act_isolate.isEnabled() and not win.act_isolate_cancel.isEnabled() and not win.act_isolate_remove.isEnabled()
print("ok   Audio menu: Isolate vocals using audio-separator / Cancel / model / Remove; the Isolated button says there is none yet")

# --- asking for isolated audio that doesn't exist offers to make it (declined: nothing happens)
asked = []
win._ask_isolate_now = lambda: (asked.append(1), False)[1]
iso_btn.click()
assert asked and win.editor.clip.source == "original" and win.isolation_job is None and orig_btn.isChecked()
print("ok   clicking Isolated with no isolated audio asks to isolate; declining leaves the clip on Original")

# --- the engine dialog is what appears when audio-separator is missing
good = os.environ["SNAPPER_SEP_PYTHON"]
os.environ["SNAPPER_SEP_PYTHON"] = str(WORK / "none" / "python")
from snapper import engine_dialog
shown = []
real_ensure = engine_dialog.ensure_engine
engine_dialog.ensure_engine = lambda eng, parent=None: (shown.append(eng.key), None)[1]
win.start_isolation()
assert shown == ["separator"] and win.isolation_job is None and "audio-separator is not set up" in win.statusBar().currentMessage()
engine_dialog.ensure_engine = real_ensure
os.environ["SNAPPER_SEP_PYTHON"] = good
print("ok   without audio-separator, Isolate asks via the engine dialog and does nothing if declined")

# --- isolate (real model)
win.start_isolation()
wait(lambda: win.isolation_job is not None, "isolation started (after the audio is decoded)", 60000)
assert "isolation" in win._job_state
mpv_aid = lambda: win.player.mpv.aid
audio_tracks = lambda: sum(1 for t in win.player.mpv.track_list if t["type"] == "audio")

# --- usable as soon as the first window is done; playback returns to the original beyond the finished part
wait(lambda: win._iso_live_done > 0, "the first window finished", 240000)
upto = win.isolated_upto()
assert 30 < upto < 100 and not win.isolated_ready() and win.isolated_usable()
assert iso_btn.isEnabled() and audio_tracks() == 2, "the growing file is added to the player as an extra audio track"
win.player.seek(10.0); QTest.qWait(600)
iso_btn.click(); QTest.qWait(600)
assert win.editor.clip.source == "isolated" and iso_btn.isChecked() and "so far" in iso_btn.toolTip() and mpv_aid() == 2
win.player.seek(95.0); QTest.qWait(1200)
assert mpv_aid() == 1 and orig_btn.isChecked() and win.editor.clip.source == "isolated", "beyond the finished part: original plays"
win.player.seek(10.0); QTest.qWait(1200)
assert mpv_aid() == 2 and iso_btn.isChecked(), "and back inside it: isolated again"
print(f"ok   usable while still being made (done to {upto:.0f} s): Isolated plays inside it, the original beyond it, and back")
win.player.play_range(upto - 4.0, None)    # playing across the boundary switches by itself
QTest.qWait(500)
assert mpv_aid() == 2
for _ in range(100):
    QTest.qWait(100)
    if win.player.pos > upto - 0.5:
        break
QTest.qWait(600)
assert mpv_aid() == 1 and orig_btn.isChecked(), (win.player.pos, mpv_aid())
win.player.stop()
print("ok   playing across the end of the finished part falls back to the original on its own")
waiting = win.project.add(Clip(12.0, 14.0, "waiting", True, {"character": "Z"}, source="isolated"))
win.project.set_export_settings(ExportSettings(output_dir=str(WORK / "out_wait"), name_template="w{n}").to_json())
(WORK / "out_wait").mkdir()
win._confirm_moves = lambda *a, **k: None
win.export_clips(force=True)
assert win.exporter.state(waiting) == "none" and "will export when the isolation has finished" in win.statusBar().currentMessage()
win.project.remove(waiting)
orig_btn.click(); win.player.seek(0.0); QTest.qWait(500)
print("ok   a clip that needs isolated audio waits for the isolation to finish instead of failing")
wait(lambda: win.isolation_job is None and win.isolated_ready() and media.audio_path(episode, 0, True).exists(), "isolation finished")
QTest.qWait(500)
iso_wav = media.isolated_pcm_path(episode, 0)
stereo = media.open_pcm(media.export_pcm_path(episode, 0, 2, 44100, 16), 2, 16)
assert iso_wav.stat().st_size == 44 + stereo.shape[0] * 4, (iso_wav.stat().st_size, stereo.shape)
wav = read_wav(iso_wav)
assert (wav["frames"].shape[0], wav["frames"].shape[1]) == (stereo.shape[0], 2)
quiet = float(np.sqrt((wav["frames"].astype(np.float32) ** 2).mean())) / float(np.sqrt((stereo.astype(np.float32) ** 2).mean()))
print(f"ok   isolated {stereo.shape[0] / 44100:.1f} s in windows; the output is the same length; level {quiet:.2f} of the original")
assert 0.05 < quiet < 1.0, "dialogue only: quieter than the full mix but not silent"
seam = wav["frames"][int(40 * 44100):int(45 * 44100), 0].astype(np.float32) / 32768
body = wav["frames"][int(10 * 44100):int(30 * 44100), 0].astype(np.float32) / 32768
assert np.abs(np.diff(seam)).max() <= max(np.abs(np.diff(body)).max() * 1.2, 0.05), "a click at the crossfaded seam"
print("ok   no click at the crossfaded window seam")
assert win.isolated_ready() and iso_btn.isEnabled() and "Only the dialogue" in iso_btn.toolTip()
assert "isolation" not in win._job_state and "Vocals isolated" in win.statusBar().currentMessage()

# --- the per-clip switch
rms = lambda a: float(np.sqrt((np.asarray(a, dtype=np.float32) ** 2).mean()))
before = rms(win.editor.wave.samples)
assert not win.editor.wave.show_iso and win.editor.wave.iso_samples is not None, "loaded, but only shown for a clip that uses it"
assert mpv_aid() == 1
iso_btn.click()
QTest.qWait(1500)
assert win.editor.clip.source == "isolated" and iso_btn.isChecked() and win.editor.wave.show_iso
assert rms(win.editor.wave.iso_samples) < before * 0.9, (rms(win.editor.wave.iso_samples), before)
assert rms(win.editor.wave.samples) == before, "the original stays as it was; the isolated audio is drawn over it"
assert mpv_aid() == 2, f"the isolated audio is the video's extra track, got aid={mpv_aid()}"
print("ok   Isolated: the waveform switches to the dialogue-only audio and mpv plays the extra audio track")
win.handle_key(type("K", (), {"key": lambda s: Qt.Key_V, "modifiers": lambda s: Qt.NoModifier})())
QTest.qWait(1000)
assert win.editor.clip.source == "original" and mpv_aid() == 1 and not win.editor.wave.show_iso
win.handle_key(type("K", (), {"key": lambda s: Qt.Key_V, "modifiers": lambda s: Qt.NoModifier})())
QTest.qWait(1000)
assert win.editor.clip.source == "isolated"
print("ok   V flips between Original and Isolated")

# --- a clip remembers its source; the next new clip inherits the choice
win.set_range(30.0, 33.0)
clip = win.project.add(Clip(30.0, 33.0, "isolated line", True, {"character": "A"}, source="isolated"))
assert clip.source == "isolated"
win.set_range(40.0, 42.0)
win.commit()
c2 = win.project.clips[-1]
assert c2.source == "isolated", "a new clip is cut from the audio that was last chosen"
orig_clip = win.project.add(Clip(50.0, 52.0, "original line", True, {"character": "B"}))
win.edit(orig_clip)
QTest.qWait(800)
assert orig_btn.isChecked() and mpv_aid() == 1 and not win.editor.wave.show_iso, "selecting a clip shows its own source"
win.edit(clip)
QTest.qWait(800)
assert iso_btn.isChecked() and mpv_aid() == 2 and win.editor.wave.show_iso
print("ok   each clip remembers Original/Isolated; selecting it switches waveform and audio; new clips inherit the last choice")

# --- saved in the project
win.project.save()
back = Project.from_file(win.project.path)
assert [c.source for c in back.clips] == ["isolated", "isolated", "original"], [c.source for c in back.clips]
print("ok   the choice is saved in the project")

# --- export follows the source: the isolated clip's file is the isolated audio, the other one is the original
out = WORK / "out"
out.mkdir()
win.project.set_export_settings(ExportSettings(output_dir=str(out), name_template="c{n}").to_json())
win._confirm_moves = lambda *a, **k: None
win.export_clips(force=True)
wait(lambda: all(win.exporter.state(c) == "done" for c in win.project.clips), "export finished", 120000)
iso_mono = media.open_pcm(media.audio_path(episode, 0, True), 1, 16)
orig_mono = media.open_pcm(media.audio_path(episode, 0), 1, 16)
for c, ref in ((clip, iso_mono), (c2, iso_mono), (orig_clip, orig_mono)):
    got = read_wav(Path(c.export_path))["frames"]
    i0, i1 = int(round(c.start * 44100)), int(round(c.end * 44100))
    assert np.array_equal(got, ref[i0:i1]), f"{c.text}: not the {c.source} audio"
assert not np.array_equal(iso_mono[int(30 * 44100):int(33 * 44100)], orig_mono[int(30 * 44100):int(33 * 44100)])
print("ok   export: isolated clips are written from the isolated audio, original ones from the original (sample-exact)")
sig_before = win.exporter.current_signature(clip)
win.on_source_requested("original")   # (the isolated clip is the one being edited) switching it marks it changed
win.exporter._sig.clear()
assert win.exporter.current_signature(clip) != sig_before and win.exporter.state(clip) == "changed"
win.on_source_requested("isolated")
print("ok   switching a clip's source marks it Changed for export")

# --- cancelling keeps the existing isolated audio and leaves nothing behind
win._confirm_reisolate = lambda: True
size_before = iso_wav.stat().st_size
win.start_isolation()
wait(lambda: win.isolation_job is not None, "job started", 20000)
wait(lambda: win._iso_live_done > 0, "the first window finished", 240000)
wv = win.editor.wave
assert wv.show_iso and wv.iso_upto and wv.iso_upto > 30 and wv.iso_samples is win._iso_live, "the overlay fills in as windows finish"
assert np.abs(win._iso_live[:int(wv.iso_upto * 44100)]).max() > 0 and not win._iso_live[int(50 * 44100):].any(), "filled up to the finished part only"
view_pm = wv._render_peaks(0.0, 40.0, 800, 130)      # the overlay is drawn: pixels of the second colour appear in the finished part
img = view_pm.toImage()
iso_col = wv.iso_color().rgb()
assert any(img.pixelColor(x, y).rgb() & 0xFFFFFF == iso_col & 0xFFFFFF for x in range(0, 800, 7) for y in range(18, 130)), "no isolated peaks drawn"
print(f"ok   while isolating, the isolated waveform fills in over the original (done up to {wv.iso_upto:.0f} s)")
win.cancel_isolation()
QTest.qWait(500)
assert win.isolation_job is None and "isolation" not in win._job_state and win._iso_live is None
assert wv.iso_samples is not None and wv.iso_upto is None, "back to the finished isolated audio"
assert iso_wav.exists() and iso_wav.stat().st_size == size_before and not Path(str(iso_wav) + ".tmp").exists()
print("ok   cancelling keeps the earlier isolated audio and removes the partial file")

# --- removing the isolated audio puts its clips back on the original
import PySide6.QtWidgets as QtW
QtW.QMessageBox.question = staticmethod(lambda *a, **k: QtW.QMessageBox.Yes)
win.remove_isolation()
QTest.qWait(500)
assert not win.isolated_ready() and not iso_wav.exists() and not media.audio_path(episode, 0, True).exists()
assert all(c.source == "original" for c in win.project.clips) and win.editor.clip.source == "original"
assert orig_btn.isChecked() and mpv_aid() == 1
print("ok   Remove isolated audio: files deleted, clips back on Original")

# --- a custom replacement: any audio file made elsewhere, placed at time 0, padded/cut to the episode's length
tone = WORK / "custom.flac"
subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=90:sample_rate=22050", "-ac", "1", str(tone)], check=True)
picked, mismatch = {"p": tone}, []
win._pick_audio_file = lambda: picked["p"]
win._confirm_length_mismatch = lambda f, e: (mismatch.append((round(f), round(e))), False)[1]
win.load_custom_audio()
assert mismatch == [(90, 100)] and not win.isolated_ready(), "a 90 s file for a 100 s episode asks first; declining does nothing"
win._confirm_length_mismatch = lambda f, e: (mismatch.append(1), True)[1]
win.load_custom_audio()
wait(lambda: win.isolated_ready() and media.audio_path(episode, 0, True).exists() and "replacement" in win.statusBar().currentMessage(), "custom audio adopted", 60000)
frames = media.open_pcm(media.export_pcm_path(episode, 0, 2, 44100, 16), 2, 16).shape[0]
custom = read_wav(media.isolated_pcm_path(episode, 0))["frames"]
assert custom.shape == (frames, 2), (custom.shape, frames)
head, tail = custom[:int(80 * 44100)].astype(np.float32), custom[int(91 * 44100):].astype(np.float32)
assert np.sqrt((head ** 2).mean()) > 1000 and np.abs(tail).max() == 0, "the tone, then silence where the file ended"
assert abs(int(win.editor.wave.samples[int(10 * 44100)])) >= 0 and win.isolated_ready()
orig_btn.click(); iso_btn.click()
QTest.qWait(1200)
assert win.editor.clip.source == "isolated" and mpv_aid() == 2 and win.editor.wave.show_iso
w = np.asarray(win.editor.wave.iso_samples, dtype=np.float32)
assert np.sqrt((w[:int(80 * 44100)] ** 2).mean()) > 1000, "the waveform now shows the custom audio"
print("ok   Load custom audio replacement: any audio file becomes the Isolated audio, placed at 0 and padded to the episode's exact length")
picked["p"] = WORK / "excerpt.mp4.srt"
(WORK / "excerpt.mp4.srt").write_text("not audio")
warned = []
QtW.QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2]))
win._confirm_replace_audio = lambda: True
win.load_custom_audio()
assert warned and "not an audio file" in warned[0] and win.isolated_ready()
print("ok   a file that is not audio is refused and the existing audio is kept")
win.grab().save(shot)
win.close()
print("ISOLATION OK")
