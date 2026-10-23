"""A project keeps the video path, transcript, clips, selected clip and proxy setting, and reopens from its file."""
import locale, os, shutil, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SNAPPER_DATA", tempfile.mkdtemp())
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from snapper import media
from snapper.theme import apply_system_theme
from snapper.main_window import MainWindow
from snapper.model import Project
from snapper.transcript import Transcript, parse_srt
from support import episode_arg, wait_until_ready

episode = episode_arg()
app = QApplication(sys.argv)
locale.setlocale(locale.LC_NUMERIC, "C")
apply_system_theme(app)

win = MainWindow(episode)
win.show()
wait_until_ready(win)
assert win.project.path.parent == Path(os.environ["SNAPPER_DATA"]) / "projects", win.project.path
assert not list(episode.parent.glob("*.snapper.json")), "nothing is written next to the video"
print("ok   project file lives in the app data folder, not beside the video")

win.set_transcript(Transcript(parse_srt(media.extract_subtitle(episode, 0).read_text(encoding="utf-8", errors="replace"))), persist=True)
n_lines = len(win.transcript().lines)
win.set_range(40.0, 42.4, "hello there")
win.editor.set_tag("character", "Alastor")
win.commit()
win.set_range(50.0, 52.0, "second")
win.commit()
clip2 = win.project.clips[1]
win.edit(clip2)
assert win.project.selected_clip == clip2.id
win.act_proxy.setChecked(False)
assert win.project.proxy_enabled is False and not win._on_proxy
QTest.qWait(1200)   # autosave
d = Project.from_file(win.project.path)
assert d.media == episode.resolve() and d.proxy_enabled is False and d.selected_clip == clip2.id
assert len(d.clips) == 2 and len(d.transcript) == n_lines and d.transcript[0]["text"]
print(f"ok   saved: video path, {len(d.clips)} clips, selected clip, transcript ({n_lines} lines), proxy off")

proj_file = win.project.path
win2 = MainWindow(proj_file)   # reopen from the project file itself
win2.show()
win.close()
wait_until_ready(win2)
assert win2.media_path.resolve() == episode.resolve()
assert len(win2.transcript().lines) == n_lines
assert win2.editor.clip.id == clip2.id and abs(win2.editor.clip.start - 50.0) < 1e-6, "selected clip restored"
assert win2.act_proxy.isChecked() is False and not win2._on_proxy and win2._proxy_job is None
print("ok   reopened from the project file: transcript, clips, selected clip and proxy setting restored")

win2.act_proxy.setChecked(True)
QTest.qWait(500)
assert win2.project.proxy_enabled and (win2._proxy_job is not None or win2._on_proxy)
print("ok   proxy turned back on: uses the cached proxy or starts generating it")

# a moved video: the project's relative path is tried first
copy_dir = Path(tempfile.mkdtemp())
moved = copy_dir / "v" / episode.name
moved.parent.mkdir()
os.symlink(episode.resolve(), moved)
pf = copy_dir / "p.snapper.json"
shutil.copy(proj_file, pf)
import json
d = json.loads(pf.read_text()); d["video"] = "/nonexistent/old/place.mkv"; d["video_rel"] = f"v/{episode.name}"
pf.write_text(json.dumps(d))
assert Project.from_file(pf).media.name == episode.name and Project.from_file(pf).media.exists()
print("ok   a moved video is found again through the relative path")

# --- where you left off: the playhead, the open clip, or the clip that was being cut and is not in the library yet
def reopen(old):
    old.project.save()
    w = MainWindow(proj_file)
    w.show()
    old.close()          # (the new window is up first: the last window closing would end the application)
    wait_until_ready(w, settle_ms=1500)
    QTest.qWait(1000)    # the saved position is gone back to
    return w

win2.edit(win2.project.clips[1])                  # a saved clip is open and the playhead is somewhere else
win2.player.seek(150.0)
QTest.qWait(1200)
win3 = reopen(win2)
assert win3.editor.clip.id == clip2.id and abs(win3.player.now() - 150.0) < 0.6, (win3.editor.clip.id, win3.player.now())
print("ok   reopened: the same clip is open and the video is where it was left (not at the clip's start)")

win3.deselect_clip()                              # a clip being cut, not saved to the library yet
win3.set_range(200.0, 203.5, "half done")
win3.editor.set_tag("character", "Zed")
win3.player.seek(230.0)
QTest.qWait(1200)
assert win3.project.clips and win3.editor.clip.id is None
win4 = reopen(win3)
c = win4.editor.clip
assert c.id is None and c.start == 200.0 and c.end == 203.5 and c.text == "half done" and c.tags.get("character") == "Zed", c
assert abs(win4.player.now() - 230.0) < 0.6 and len(win4.project.clips) == 2
assert abs(win4.editor.wave.sel_in - 200.0) < 1e-6
print("ok   reopened: the clip being cut (range, text, tags) and the playhead come back")

win4.deselect_clip()                              # nothing to restore: a clean start
win4.set_range(None, None, "")
win4.pending.tags.clear()
win4.player.seek(0.2)
QTest.qWait(1200)
win5 = reopen(win4)
assert win5.editor.clip.start is None and win5.player.now() < 1.0 and win5.project.pending is None
print("ok   with nothing in progress, a reopened project starts clean")
win5.close()
print("PROJECT OK")
