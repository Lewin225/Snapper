"""Endless dragging: movement is read as "how far since last time" and never runs out against the edge of the screen (a
mouse with a ball or a small pad can scrub as far as it likes). On native Wayland the pointer is locked for the drag
(wayland_lock.py), the compositor reports the movement and puts the pointer back where the drag began; elsewhere (X11) the
pointer is put back where the drag began after every move. Where neither works the warp fails once, is noticed, and the drag
carries on as an ordinary one."""
from __future__ import annotations

import os
import time
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QWidget

LOCK_WAIT = 0.4         # seconds the compositor has to grant the lock before the drag carries on without it
IGNORE_AFTER_WARP = 4   # events to wait for the one that reports the pointer back at the anchor (older ones are stale)


def _warp(pos: QPoint) -> bool:
    """Puts the pointer at `pos` (screen coordinates); False if the platform did not let it (or SNAPPER_NO_WARP is set: the
    tests drive the app with made-up mouse events and must not move the real pointer)."""
    if os.environ.get("SNAPPER_NO_WARP"):
        return False
    QCursor.setPos(pos)
    return QCursor.pos() == pos


class RelativeDrag:
    def __init__(self, widget: QWidget, warp: Optional[Callable[[QPoint], bool]] = None,
                 on_move: Optional[Callable[[float, float], None]] = None):
        self.widget = widget
        self.warp = warp or _warp
        self.on_move = on_move          # called with the movement while the pointer is locked (no mouse events come then)
        self.active = False
        self.warping = False
        self.locked = False             # the compositor has granted the lock: movement comes from it, not from mouse events
        self._lock = None               # a lock has been asked for (it may not have been granted yet)
        self._poll = QTimer(widget, interval=4, timeout=self.flush)

    def start(self, anchor: QPointF, current: Optional[QPointF] = None, press: Optional[QPointF] = None):
        """The drag begins with the pointer at `anchor` (and now at `current`, if it has moved since); `press` is the same
        place in the widget's own coordinates. The pointer stays visible, as the left-right arrow."""
        self.anchor = anchor.toPoint()
        self.last = (current or anchor).toPoint()
        self.active, self.warping, self._stale = True, True, 0
        self._sync: Optional[bool] = None   # whether a warp is answered by a report of the pointer at the anchor
        self.widget.setCursor(Qt.SizeHorCursor)
        self.locked, self._lock = False, None
        if press is not None and self.on_move is not None and not os.environ.get("SNAPPER_NO_LOCK"):
            from .wayland_lock import PointerLock
            lock = PointerLock.get()
            window = self.widget.window()
            if lock is not None and window.windowHandle() is not None:
                where = self.widget.mapTo(window, press.toPoint())
                if lock.begin(window.windowHandle(), where.x(), where.y()):
                    self._lock, self._asked = lock, time.monotonic()
                    self._poll.start()    # until the lock is granted the drag goes on as an ordinary one

    def flush(self):
        """Hands over the movement the compositor has reported (locked pointer only), and watches the lock itself: it counts
        once the compositor says it is granted, and a lock that is refused, taken back or never answered is dropped, the drag
        carrying on as an ordinary one."""
        lock = self._lock
        if lock is None:
            return
        state = lock.lock_state
        if not self.locked and state == "locked":
            self.locked = True
        elif state == "unlocked" or (not self.locked and time.monotonic() - self._asked > LOCK_WAIT):
            from .wayland_lock import debug
            debug(f"given up ({state or 'no answer'})")
            self._drop_lock(restore=False)
            return
        if self.locked and self.on_move is not None:
            dx, dy = lock.take()
            if dx or dy:
                self.on_move(dx, dy)

    def _drop_lock(self, restore: bool):
        self._poll.stop()
        self._lock.end(restore=restore)
        self._lock, self.locked = None, False
        self.warping, self._stale = False, 0
        self.last = None    # the next report of the pointer starts afresh
    def step(self, pos: QPointF) -> tuple[int, int]:
        """The pointer was reported at `pos`: how far it moved since the previous report."""
        if self.locked:
            return 0, 0
        p = pos.toPoint()
        if self.last is None:
            self.last = p
            return 0, 0
        if not self.warping:
            d, self.last = p - self.last, p
            return d.x(), d.y()
        if self._stale:   # a warp is on its way: reports from before it landed describe movement already counted
            if p == self.anchor:
                self._stale, self._sync, self.last = 0, True, p
            elif self._stale >= IGNORE_AFTER_WARP:
                self._stale, self._sync = 0, False   # no such report comes on this platform: stop waiting for it
            else:
                self._stale += 1
                return 0, 0
        d = p - self.last
        if p != self.anchor:
            if self.warp(self.anchor):
                self.last, self._stale = QPoint(self.anchor), (0 if self._sync is False else 1)
            else:
                self.warping, self.last = False, p   # not allowed here: an ordinary drag from now on
        else:
            self.last = p
        return d.x(), d.y()

    def finish(self):
        """The drag is over: the pointer goes back to where it began and shows again."""
        if self.active:
            if self._lock is not None:
                self.flush()
                if self._lock is not None:
                    self._poll.stop()
                    self._lock.end(restore=self.locked)   # the compositor shows the pointer where the drag began
                    self._lock, self.locked = None, False
            elif self.warping:
                self.warp(self.anchor)
            self.widget.unsetCursor()
        self.active = False
