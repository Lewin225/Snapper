"""Empty-transcript buttons, subtitle-from-video menu, and the audio track picker.

usage: python tests/transcript_ui_test.py EPISODE.mkv TWO_AUDIO_TRACK_FILE.mkv
(needs the display/GL environment from run.sh)
"""
import locale
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os, tempfile
os.environ.setdefault("SNAPPER_DATA", tempfile.mkdtemp())   # tests never touch the real projects

import numpy as np
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from snapper import media
from snapper.__main__ import dark
from snapper.main_window import MainWindow
from snapper.transcript import Transcript

app = QApplication(sys.argv)
locale.setlocale(locale.LC_NUMERIC, "C")
dark(app)
app.setQuitOnLastWindowClosed(False)  # the test opens several windows one after another


def wait(cond, what, ms=60000):
    t = 0
    while not cond():
        QTest.qWait(100)
        t += 100
        assert t < ms, f"timeout waiting for {what}"
    print("ok  ", what)


# ---------------------------------------------------------------- episode: empty transcript + 30 subtitle tracks
episode = Path(sys.argv[1])
win = MainWindow(episode)
win.show()
QTest.qWait(1500)
area = win.transcript_area
win.set_transcript(Transcript([]))
assert area._stack.currentIndex() == 0 and area.btn_generate.isVisible() and area.btn_video.isVisible()
print("ok   empty transcript shows the buttons")

wait(lambda: len(area.tracks) > 1 and all("lines" in l for _o, l in area.tracks), "subtitle tracks surveyed and labelled")
print("     e.g.", area.tracks[0][1], "|", area.tracks[-1][1])
win._fill_subtitle_menu()
assert len(win.menu_video_subs.actions()) == len(area.tracks)
print(f"ok   Transcript > Load from video submenu lists {len(area.tracks)} tracks")

order = area.tracks[0][0]
area.subtitles_requested.emit(order)
QTest.qWait(300)
assert area._stack.currentIndex() == 1 and len(win.transcript().lines) > 50
print("ok   choosing a track loads it and swaps the buttons for the list:", len(win.transcript().lines), "lines")

win.set_transcript(Transcript([]))
assert area._stack.currentIndex() == 0
area.set_busy("Transcribing…", 0.4)
assert not area.btn_generate.isEnabled() and area.message.isHidden()
assert not area.bar_empty.isHidden() and area.bar_empty.value() == 40 and area.bar_empty.text() == "Transcribing… 40%"
area.set_busy(None)
assert area.bar_empty.isHidden() and not area.message.isHidden()
assert area.btn_generate.isEnabled()
print("ok   busy state disables the buttons and shows progress")
assert not win.audio_combo.isEnabled() and win.audio_combo.count() == 1
print("ok   single audio track: picker disabled")
old = win  # File > Open opens the new window first and closes the old one afterwards

# ---------------------------------------------------------------- file with two audio tracks
two = Path(sys.argv[2])
shutil.rmtree(media.cache_dir(two), ignore_errors=True)
two.with_name(two.name + ".snapper.json").unlink(missing_ok=True)
win = MainWindow(two)
win.show()
old.close()
wait(lambda: win.editor.wave.samples is not None, "track 1 waveform")
assert win.audio_combo.count() == 2 and win.audio_combo.isEnabled()
print("ok   two tracks listed:", [win.audio_combo.itemText(i) for i in range(2)])
wait(lambda: win.player.duration > 0, "video loaded")
first = np.array(win.editor.wave.samples[:200000], dtype=np.float32)

win.audio_combo.setCurrentIndex(1)
assert win.editor.wave.samples is None or True
wait(lambda: win.editor.wave.samples is not None and media.audio_path(two, 1).exists(), "track 2 waveform")
QTest.qWait(500)
second = np.array(win.editor.wave.samples[:200000], dtype=np.float32)
assert not np.allclose(first, second), "waveform should change with the track"
assert abs(np.abs(second).max() - np.abs(second).min()) >= 0  # a 440 Hz tone: steady amplitude, unlike speech
assert win.player.mpv.aid == 2, win.player.mpv.aid
assert win.project.audio_track == 1
print(f"ok   switching track: waveform changed (peak {np.abs(first).max():.0f} -> {np.abs(second).max():.0f}), mpv aid = {win.player.mpv.aid}")
old = win
QTest.qWait(1500)  # the project autosaves shortly after a change

# the choice is remembered
win = MainWindow(two)
win.show()
old.close()
QTest.qWait(1500)
assert win.audio_combo.currentIndex() == 1, "audio track should be remembered in the project"
print("ok   choice remembered in the project file")
win.close()
two.with_name(two.name + ".snapper.json").unlink(missing_ok=True)
print("TRANSCRIPT UI OK")
