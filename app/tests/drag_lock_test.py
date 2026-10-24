"""The pointer lock during a drag: it counts once the compositor grants it, and a refused, revoked or unanswered lock leaves an ordinary drag."""
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["SNAPPER_NO_WARP"] = "1"
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QWidget
from snapper import drag
from snapper import wayland_lock
app = QApplication(sys.argv)
class Fake:
    def __init__(s): s.lock_state=None; s.ended=[]; s.moves=[(3.0,1.0)]
    def begin(s,*a): return True
    def take(s): m,s.moves=(s.moves[0] if s.moves else (0,0)),[]; return m
    def end(s,restore=True): s.ended.append(restore)
def run(state_seq):
    fake = Fake(); wayland_lock.PointerLock.get = classmethod(lambda c: fake)
    w = QWidget(); w.show(); got = []
    d = drag.RelativeDrag(w, on_move=lambda dx, dy: got.append((dx, dy)))
    d.start(QPointF(50, 50), press=QPointF(5, 5))
    out = []
    for st in state_seq:
        fake.lock_state = st; d.flush(); out.append((d.locked, d._lock is not None))
    return d, fake, got, out
d, f, got, out = run([None, "locked"])
assert out == [(False, True), (True, True)] and got == [(3.0, 1.0)], (out, got)
assert d.step(QPointF(60, 50)) == (0, 0), "locked: mouse events are ignored"
d.finish(); assert f.ended == [True] and d._lock is None, f.ended
d, f, got, out = run([None, "unlocked"])
assert out[-1] == (False, False) and f.ended == [False], (out, f.ended)
assert d.step(QPointF(60, 50)) == (0, 0) and d.step(QPointF(65, 50)) == (5, 0), "after giving up: an ordinary drag"
d, f, got, out = run([None]); drag.LOCK_WAIT = 0.0; time.sleep(0.01); d.flush()
assert d._lock is None and f.ended == [False], "no answer in time: given up"
print("DRAG LOCK OK")
