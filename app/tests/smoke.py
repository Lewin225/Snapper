"""End-to-end smoke test (needs the display/GL environment from run.sh): drives the real window.

usage: python tests/smoke.py EPISODE.mkv SUBTITLES.srt SCREENSHOT.png
"""
import locale
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os, tempfile
os.environ.setdefault("SNAPPER_DATA", tempfile.mkdtemp())   # tests never touch the real projects

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from snapper import media
from snapper.theme import apply_system_theme
from snapper.main_window import MainWindow
from snapper.transcript import Transcript, parse_srt

from support import episode_arg, shot_arg
episode, shot = episode_arg(), shot_arg('snapper_smoke.png')
app = QApplication(sys.argv)
locale.setlocale(locale.LC_NUMERIC, "C")
apply_system_theme(app)
import os
if not os.environ.get("SMOKE_KEEP_CACHE"):
    shutil.rmtree(media.cache_dir(episode), ignore_errors=True)  # force the audio + proxy jobs to run
win = MainWindow(episode)
proj = win.project.path   # in the (temporary) app data folder
win.show()
import time as _t
_t0 = _t.time()
win.player.paused_changed.connect(lambda p: print(f"     [{_t.time() - _t0:5.1f}s] paused -> {p}", flush=True))
_orig_toggle = win.player.toggle
def _logged_toggle():
    print(f"     [{_t.time() - _t0:5.1f}s] toggle() called (a Space key reached the window)", flush=True)
    _orig_toggle()
win.player.toggle = _logged_toggle


def wait(cond, what, ms=180000):
    t = 0
    while not cond():
        QTest.qWait(100)
        t += 100
        if t > ms:
            raise SystemExit(f"FAIL timeout waiting for {what}")
    print(f"ok   {what}")


def key(k, mod=Qt.NoModifier):
    QTest.keyClick(win, k, mod)
    QTest.qWait(150)


wait(lambda: win.player.duration > 0, "video loaded")
print("     after load: pos", round(win.player.pos, 2), "paused", win.player.paused)
wait(lambda: win.editor.wave.samples is not None, "audio decoded + waveform ready")
print("     before proxy: pos", round(win.player.pos, 2), "paused", win.player.paused)
wait(lambda: media.proxy_path(episode).exists(), "scrub proxy generated")
print("     proxy done: pos", round(win.player.pos, 2), "paused", win.player.paused)
QTest.qWait(1500)
print("ok   proxy swapped in; pos", round(win.player.pos, 2))

lines = parse_srt(media.extract_subtitle(episode, 0).read_text(encoding="utf-8"))   # the embedded track
win.set_transcript(Transcript(lines))
assert len(win.transcript().lines) >= 10, "subtitle parse"
print("ok   subtitles parsed:", len(win.transcript().lines), "lines")

# click a transcript line -> pending selection
i = win.transcript().index_at(15.0)
win.transcript_panel.line_selected.emit(i)
QTest.qWait(300)
c = win.editor.clip
assert c.id is None and c.start is not None and c.end is not None, "line click should set a range"
line_start = c.start
print(f"ok   line click -> {c.start:.2f}-{c.end:.2f} text={c.text!r}")

win.editor.set_tag("character", "voice1")
key(Qt.Key_Return)
assert len(win.project.clips) == 1 and win.project.clips[0].tags == {"character": "voice1"}, "commit"
assert win.editor.clip.tags.get("character") == "voice1" and win.editor.clip.start is None, "sticky tags, range cleared"
print("ok   commit created clip; character stays set; range cleared")

# cut by hand: seek, I, play a bit, O
win.player.seek(40.0)
QTest.qWait(500)
key(Qt.Key_I)
win.player.seek(42.4)
for _ in range(50):   # poll instead of a fixed wait: mpv in a test window can be slow to finish a seek
    QTest.qWait(100)
    if abs(win.player.pos - 42.4) < 0.05:
        break
assert abs(win.player.pos - 42.4) < 0.05, f"cached position is stale after a seek: {win.player.pos}"
key(Qt.Key_O)
c = win.editor.clip
assert abs(c.start - 40.0) < 0.1 and abs(c.end - 42.4) < 0.1, (c.start, c.end)
print(f"ok   I/O keys -> {c.start:.3f}-{c.end:.3f} auto-text={c.text!r}")
key(Qt.Key_1)
assert c.tags["character"] == "voice1"
key(Qt.Key_Return)
assert len(win.project.clips) == 2

# select-to-edit then nudge via waveform edit
win.clips.clip_selected.emit(win.project.clips[0])
QTest.qWait(300)
assert win.editor.clip is win.project.clips[0]
win.on_wave_edited(win.editor.clip.start + 0.2, win.editor.clip.end)
assert abs(win.project.clips[0].start - (line_start + 0.2)) < 0.01, win.project.clips[0].start
win.project.rename_value("character", "voice1", "Alastor")
assert all(c.tags["character"] == "Alastor" for c in win.project.clips)
print("ok   edit existing clip; global rename voice1 -> Alastor")

win.clips.proxy.set_filter("character", "Alastor")
assert win.clips.proxy.rowCount() == 2
win.clips.proxy.set_filter("character", "nobody")
assert win.clips.proxy.rowCount() == 0
win.clips.proxy.set_filter("character", None)
print("ok   tag filter")

# transport / snipping buttons
from PySide6.QtWidgets import QPushButton
btn = {b.text(): b for b in win.findChildren(QPushButton)}
win.edit(win.pending)
win.player.seek(60.0); QTest.qWait(500)
btn["Set In (I)"].click(); win.player.seek(63.0); QTest.qWait(500); btn["Set Out (O)"].click()
c = win.editor.clip
assert abs(c.start - 60.0) < 0.1 and abs(c.end - 63.0) < 0.1, (c.start, c.end)
btn["Deselect clip (Esc)"].click()
assert win.editor.clip.start is None and win.editor.wave.sel_in is None, "clear selection"
win.clips.clip_selected.emit(win.project.clips[0])
assert win.editor.clip.id is not None
btn["Deselect clip (Esc)"].click()
assert win.editor.clip is win.pending and len(win.project.clips) == 2, "clear leaves stored clip untouched"
btn["Set In (I)"].click(); win.play_from_in(); QTest.qWait(800)   # no button any more
assert not win.player.paused
assert "Pause" in win.btn_play.text(), win.btn_play.text()
win.btn_play.click(); QTest.qWait(300)
assert win.player.paused and "Play" in win.btn_play.text()
win.volume.setValue(30); assert abs(win.player.mpv.volume - 30) < 0.5
btn["■ Stop"].click(); QTest.qWait(300)
btn["Deselect clip (Esc)"].click()
print("ok   transport buttons, clear selection, volume")

# real WhisperX transcription through the background job
win.start_transcription()
wait(lambda: win.transcript_job is None, "WhisperX transcription finished", 400000)
tr = win.transcript()
nwords = sum(len(l["words"]) for l in tr.lines)
assert len(tr.lines) >= 8 and nwords >= 20, (len(tr.lines), nwords)
print(f"ok   WhisperX transcript: {len(tr.lines)} lines, {nwords} words")
starts = [l["start"] for l in tr.lines]
assert starts == sorted(starts)
dups = sum(1 for a, b in zip(tr.lines, tr.lines[1:]) if a["text"] == b["text"] and abs(a["start"] - b["start"]) < 1)
assert dups == 0, f"{dups} duplicated lines at window seams"
print("ok   no duplicate lines at window seams")

win.edit(win.pending)
win.set_range(27.4, 29.8)   # "I've had smaller." is spoken here
print("     word-based text for 27.4-29.8:", repr(win.editor.clip.text))
assert win.editor.clip.text, "text from words"
assert win.editor.wave.word_source(26.0, 31.0), "words reach the waveform"
QTest.qWait(500)
win.grab().save(shot)
win.project.save()
print("saved project:", proj, "clips:", len(Path(proj).read_text().split('"id"')) - 1)
win.close()
print("SMOKE PASSED")
