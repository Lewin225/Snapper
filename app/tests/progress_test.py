"""Progress display: status-bar job bars, the proxy banner, and the transcript progress strip."""
import locale, os, sys, tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp())
os.environ["SNAPPER_CACHE"] = str(root / "cache")   # empty cache: the proxy and audio jobs really run
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SNAPPER_DATA", str(root / "data"))
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from snapper.theme import apply_system_theme
from snapper.main_window import MainWindow
from snapper.transcript import Transcript

from support import episode_arg, shot_arg
episode, shot = episode_arg(), shot_arg('snapper_progress.png')
app = QApplication(sys.argv)
locale.setlocale(locale.LC_NUMERIC, "C")
apply_system_theme(app)
win = MainWindow(episode)
win.resize(1500, 844)
win.show()

seen_proxy_bar = seen_banner = False
checked_layout = False
for _ in range(600):
    QTest.qWait(100)
    if "proxy" in win.status_jobs._rows:
        seen_proxy_bar = True
    if not win.proxy_banner.isHidden() and "Generating scrub proxy" in win.proxy_banner.text():
        if not seen_banner:
            win.grab().save(shot.replace(".png", "_proxy.png"))
        seen_banner = True
    jb = win.status_jobs
    if len(jb._rows) >= 2 and not checked_layout:   # several jobs: packed together, not spread across the bar
        checked_layout = True
        QTest.qWait(200)
        rows = sorted((r[0] for r in jb._rows.values()), key=lambda w: w.x())
        gaps = [b.x() - (a.x() + a.width()) for a, b in zip(rows, rows[1:])]
        assert all(g <= 30 for g in gaps) and jb.width() <= jb.sizeHint().width() + 2, (gaps, jb.width(), jb.sizeHint())
        assert jb._cancel.isVisible() and jb._anim.state() == jb._anim.State.Running, "pulse and cancel button while busy"
        win.grab().save(shot.replace(".png", "_jobs.png"))
    if win._on_proxy:
        break
assert seen_proxy_bar, "a labelled bar for the proxy job shows in the status bar"
assert seen_banner, "the banner above the video explains that the proxy is being generated"
assert win._on_proxy and "ready" in win.proxy_banner.text() and not win.proxy_banner.isHidden()
assert "proxy" not in win.status_jobs._rows
assert checked_layout, "two jobs ran together"
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
# cancel background work: stops a running job without reporting a failure, and the pulse and button go away
from snapper import media
long = media.FfmpegJob(["-f", "lavfi", "-i", "sine=duration=3000", "-f", "null"], 3000, root / "never.out")
failures = []
win._run_job(long, "pcm", lambda: None, lambda err: failures.append(err))
QTest.qWait(500)
assert "pcm" in win.status_jobs._rows and win.status_jobs._cancel.isVisible()
win.status_jobs._cancel.click()
for _ in range(100):
    if not win._job_state:
        break
    QTest.qWait(100)
assert not win._job_state and not win.status_jobs._rows and win.status_jobs._cancel.isHidden()
assert win.status_jobs._anim.state() != win.status_jobs._anim.State.Running
assert failures == ["cancelled"] and "failed" not in win.statusBar().currentMessage() and not win.jobs
print("ok   Cancel background work stops the job quietly; the pulse and button disappear")
win.close()
print("PROGRESS OK")
