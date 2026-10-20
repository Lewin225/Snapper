"""Progress display: status-bar job bars, the proxy banner, and the transcript progress strip."""
import locale, os, sys, tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp())
os.environ["SNAPPER_CACHE"] = str(root / "cache")   # empty cache: the proxy and audio jobs really run
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SNAPPER_DATA", str(root / "data"))
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from snapper.__main__ import dark
from snapper.main_window import MainWindow
from snapper.transcript import Transcript

episode, shot = Path(sys.argv[1]), sys.argv[2]
app = QApplication(sys.argv)
locale.setlocale(locale.LC_NUMERIC, "C")
dark(app)
win = MainWindow(episode)
win.resize(1500, 844)
win.show()

seen_proxy_bar = seen_banner = False
for _ in range(600):
    QTest.qWait(100)
    if "proxy" in win.status_jobs._rows:
        seen_proxy_bar = True
    if not win.proxy_banner.isHidden() and "Generating scrub proxy" in win.proxy_banner.text():
        if not seen_banner:
            win.grab().save(shot.replace(".png", "_proxy.png"))
        seen_banner = True
    if win._on_proxy:
        break
assert seen_proxy_bar, "a labelled bar for the proxy job shows in the status bar"
assert seen_banner, "the banner above the video explains that the proxy is being generated"
assert win._on_proxy and "ready" in win.proxy_banner.text() and not win.proxy_banner.isHidden()
assert "proxy" not in win.status_jobs._rows
print("ok   proxy: status-bar bar and banner while generating; 'ready' banner when done; bar removed")
QTest.qWait(4500)
assert win.proxy_banner.isHidden()
print("ok   the 'ready' banner hides itself")

# transcript strip: with lines already shown, the progress sits above the list
win.set_transcript(Transcript([{"start": 1.0, "end": 2.0, "text": "hello there", "words": []}]))
win.transcript_area.set_busy("Transcribing…", 0.25)
assert not win.transcript_area.bar_list.isHidden() and win.transcript_area.bar_list.text() == "Transcribing… 25%"
win.grab().save(shot.replace(".png", "_transcribing.png"))
win.transcript_area.set_busy(None)
assert win.transcript_area.bar_list.isHidden()
print("ok   transcript progress strip over the list")
win.close()
print("PROGRESS OK")
