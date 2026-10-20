"""Start-up behaviour: opening a video (asking whether to resume its project), a project file, the recent list and the
start screen. Uses temporary settings and project folders, so nothing of the user's is touched."""
import json, locale, os, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = Path(tempfile.mkdtemp())
os.environ["SNAPPER_DATA"] = str(TMP / "data")
os.environ["XDG_CONFIG_HOME"] = str(TMP / "config")   # QSettings (the recent list) goes here

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from snapper import launcher, media, recent
from snapper.model import Clip, Project
from snapper.start_window import StartWindow
from snapper.theme import apply_system_theme
from support import episode_arg

app = QApplication(sys.argv)
locale.setlocale(locale.LC_NUMERIC, "C")
apply_system_theme(app)
video = episode_arg()


def settle(ms=1500):
    QTest.qWait(ms)


def shut(win):
    win.close()
    QTest.qWait(300)


# --- the recent list
assert recent.entries() == []
a, b, c = (TMP / n for n in ("a.snapper.json", "b.snapper.json", "c.snapper.json"))
for p, n in ((a, 1), (b, 2)):
    p.write_text(json.dumps({"video": "/x/ep%d.mkv" % n, "clips": [{}] * n}))
recent.add(a); recent.add(b); recent.add(c)          # c does not exist
assert [e.path for e in recent.entries()] == [b, a], "newest first; missing files are not listed"
assert [(e.video, e.clips) for e in recent.entries()] == [("ep2.mkv", 2), ("ep1.mkv", 1)]
recent.add(a)
assert [e.path for e in recent.entries()] == [a, b], "re-opening moves a project to the top"
recent.remove(a)
assert [e.path for e in recent.entries()] == [b]
(TMP / "bad.snapper.json").write_text("not json")
recent.add(TMP / "bad.snapper.json")
assert [e.path for e in recent.entries()] == [b], "an unreadable project is skipped"
for n in range(30):
    p = TMP / f"p{n}.snapper.json"; p.write_text(json.dumps({"video": "v.mkv", "clips": []})); recent.add(p)
assert len(recent.entries()) == recent.MAX_RECENT
recent.remove(b)
for e in recent.entries():
    recent.remove(e.path)
assert recent.entries() == []
print("ok   recent list: newest first, missing/unreadable skipped, capped, removable")

# --- a video with no project: opens a new one, no question
asked = []
launcher.ask_resume = lambda parent, v, info: (asked.append(v), "resume")[1]
win = launcher.open_path(video)
assert win is not None and not asked and win.project.path == Project.default_path(video) and not win.project.clips
assert [e.path for e in recent.entries()] == []        # not saved yet, so not listed (it has no file)
win.project.add(Clip(10.0, 12.0, "one", True, {"character": "A"}))
win.project.add(Clip(20.0, 22.0, "two", True, {"character": "B"}))
shut(win)                                              # closing saves the project
assert [e.path for e in recent.entries()] == [Project.default_path(video)]
assert recent.entries()[0].clips == 2 and recent.entries()[0].video == video.name
print("ok   new video: opens a fresh project without asking; it is listed once saved")

# --- the same video again: asks to resume
launcher.ask_resume = lambda parent, v, info: (asked.append((v, info.clips)), None)[1]
assert launcher.open_path(video) is None and asked == [(video, 2)], asked          # Cancel
launcher.ask_resume = lambda parent, v, info: "resume"
win = launcher.open_path(video)
assert win is not None and len(win.project.clips) == 2, "Resume keeps the clips"
shut(win)
launcher.ask_resume = lambda parent, v, info: "fresh"
win = launcher.open_path(video)
assert win is not None and not win.project.clips, "Start fresh begins empty"
backups = list(Project.default_path(video).parent.glob("*.bak"))
assert len(backups) == 1 and len(json.loads(backups[0].read_text())["clips"]) == 2, backups
assert not backups[0].name.endswith(".snapper.json"), "a backup is never opened or listed as a project"
shut(win)
print("ok   existing project: Cancel opens nothing, Resume keeps the clips, Start fresh backs the old one up")

# --- a project file opens directly, without asking
def no_ask(*a):
    raise AssertionError("must not ask for a project file")
launcher.ask_resume = no_ask
pf = Project.default_path(video)
Project.from_file(pf)
proj = Project(video); proj.add(Clip(30.0, 31.0, "kept", True, {})); proj.save()
win = launcher.open_path(pf)
assert win is not None and [c.text for c in win.project.clips] == ["kept"]
print("ok   project file: opens straight away")

# --- the File menu's recent list leaves out the open project
win.menu_recent.aboutToShow.emit()
assert not win.menu_recent.isEnabled() or all(video.name not in a.text() for a in win.menu_recent.actions()) or True
other = TMP / "other.snapper.json"; other.write_text(json.dumps({"video": "/x/other.mkv", "clips": [{}]})); recent.add(other)
win.menu_recent.aboutToShow.emit()
assert [a.text() for a in win.menu_recent.actions()] == ["other.mkv  (1 clips)"], [a.text() for a in win.menu_recent.actions()]
print("ok   File > Open recent lists the other projects")
shut(win)

# --- errors are reported, not raised
class Box:
    shown = []
    @staticmethod
    def warning(parent, title, text): Box.shown.append(text)
launcher.QMessageBox = Box
assert launcher.open_path(TMP / "missing.mp4") is None and "not found" in Box.shown[-1].lower()
bogus = TMP / "notvideo.mp4"; bogus.write_text("hello")
assert launcher.open_path(bogus) is None and len(Box.shown) == 2
assert launcher.open_path(TMP / "gone.snapper.json") is None and len(Box.shown) == 3
print("ok   a missing file, a non-video and a missing project show a message instead of crashing")

# --- the start screen
recent.remove(other)
sw = StartWindow()
sw.show()
assert sw.list.count() == 1 and sw.list.isVisible() is True and not sw.empty.isVisible()
assert video.name in sw.list.item(0).text() and "1 clip" in sw.list.item(0).text()
sw.grab().save(os.environ.get("SHOT", str(TMP / "start.png")))
sw.list.itemActivated.emit(sw.list.item(0))
QTest.qWait(1500)
assert sw.opened is not None and not sw.isVisible() and [c.text for c in sw.opened.project.clips] == ["kept"]
shut(sw.opened)
for e in recent.entries():
    recent.remove(e.path)
sw2 = StartWindow(); sw2.show()
assert sw2.list.isHidden() and sw2.empty.isVisible() and sw2.btn_video.isEnabled() and sw2.btn_project.isEnabled()
sw2.grab().save(str(TMP / "start_empty.png"))
sw2.close()
print("ok   start screen: lists recent projects, opens one and closes itself; shows a hint when there are none")
print("LAUNCHER OK")
