"""Helpers shared by the GUI tests."""
import sys
import tempfile
from pathlib import Path

from PySide6.QtTest import QTest

MEDIA = Path(__file__).parent / "media"
VIDEO = MEDIA / "tears_of_steel.mp4"      # the default test video (CC BY 3.0), fetched by fetch_media.sh, with WhisperX subtitles embedded
TWO_AUDIO = MEDIA / "two_audio.mkv"      # a short file with two audio tracks (noise, then a 440 Hz tone)


def episode_arg() -> Path:
    """The video to test with: a .mp4/.mkv given on the command line, else the default. Arguments are recognised by
    their extension, so a stray path can never be mistaken for (and overwritten as) something else."""
    given = [a for a in sys.argv[1:] if a.lower().endswith((".mp4", ".mkv"))]
    return Path(given[0]) if given else VIDEO


def shot_arg(default_name: str = "snapper_test.png") -> str:
    """Where a test saves its screenshot: a .png given on the command line, else a file in the temp folder."""
    given = [a for a in sys.argv[1:] if a.lower().endswith(".png")]
    return given[0] if given else str(Path(tempfile.gettempdir()) / default_name)


def wait_until_ready(win, timeout_ms: int = 30000, settle_ms: int = 3000):
    """Waits for the video to load, then leaves mpv alone for a moment so the test starts from a quiet player.
    Deliberately does not play/pause anything: that would be visible and would disturb what the test measures."""
    waited = 0
    while not win.player.duration:
        QTest.qWait(100)
        waited += 100
        assert waited < timeout_ms, "video never loaded"
    QTest.qWait(settle_ms)


# --- one window for several tests -------------------------------------------------------------------------------------
# ui_suite.py runs the basic window tests one after another in a single process and a single window (starting a window,
# loading the video and letting mpv settle takes seconds each time). A test asks for its window with window() and gives it
# back with finish(); on its own, the same test creates and closes a window of its own.
SHARED = None


def application():
    """The QApplication (the one that exists already when tests share a process), set up the way the app does it."""
    import locale
    from PySide6.QtWidgets import QApplication
    from snapper.theme import apply_system_theme
    app = QApplication.instance() or QApplication(sys.argv)
    locale.setlocale(locale.LC_NUMERIC, "C")
    apply_system_theme(app)
    return app


def window(episode=None, settle_ms: int = 3000):
    """The shared window if there is one, else a new one showing `episode`, once its video has loaded."""
    if SHARED is not None:
        return SHARED
    from snapper.main_window import MainWindow
    win = MainWindow(episode or episode_arg())
    win.show()
    wait_until_ready(win, settle_ms=settle_ms)
    return win


def finish(win):
    """A test is done with its window: a shared one stays open for the next test."""
    if win is not SHARED:
        win.close()


def reset(win):
    """Puts a shared window back to how a new one starts: stopped, at the start, no clips, default tags and layout."""
    from snapper.model import Clip, STRING
    pl, pr = win.player, win.project
    pl._end = None
    pl._range_timer.stop()
    pl.mpv.pause = True
    pl.play_start = 0.0
    pl.seek(0.0)
    pr.clips.clear()
    pr.selected_clip = None
    pr._next_id = 1
    pr.tag_types[:] = ["character"]
    pr.tag_kinds.clear()
    pr.tag_kinds["character"] = STRING
    pr.tag_values.clear()
    pr.export_settings = None
    pr.auto_export = False
    pr.structure_changed.emit()
    win.pending = Clip()
    win.edit(win.pending)
    win.reset_layout()
    win.set_playhead_motion("smooth", save=False)
    QTest.qWait(300)
