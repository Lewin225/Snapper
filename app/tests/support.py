"""Helpers shared by the GUI tests."""
import sys
import tempfile
from pathlib import Path

from PySide6.QtTest import QTest

MEDIA = Path(__file__).parent / "media"
VIDEO = MEDIA / "overgrown.mp4"          # the default test video (CC BY 4.0), with a WhisperX subtitle track embedded
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
