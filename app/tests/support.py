"""Helpers shared by the GUI tests."""
from PySide6.QtTest import QTest


def wait_until_ready(win, timeout_ms: int = 30000, settle_ms: int = 3000):
    """Waits for the video to load, then leaves mpv alone for a moment so the test starts from a quiet player.
    Deliberately does not play/pause anything: that would be visible and would disturb what the test measures."""
    waited = 0
    while not win.player.duration:
        QTest.qWait(100)
        waited += 100
        assert waited < timeout_ms, "video never loaded"
    QTest.qWait(settle_ms)
