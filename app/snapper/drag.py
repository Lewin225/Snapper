"""Endless dragging. While a drag is on, the pointer is put back where the drag began after every move, so
movement is read as "how far since last time" and never runs out against the edge of the screen (a mouse with a ball or a
small pad can scrub as far as it likes). Where the pointer cannot be moved by the program (a native Wayland window) the warp
fails once, is noticed, and the drag carries on as an ordinary one."""
from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QWidget

IGNORE_AFTER_WARP = 4   # events to wait for the one that reports the pointer back at the anchor (older ones are stale)


def _warp(pos: QPoint) -> bool:
    """Puts the pointer at `pos` (screen coordinates); False if the platform did not let it (or SNAPPER_NO_WARP is set: the
    tests drive the app with made-up mouse events and must not move the real pointer)."""
    if os.environ.get("SNAPPER_NO_WARP"):
        return False
    QCursor.setPos(pos)
    return QCursor.pos() == pos


class RelativeDrag:
    def __init__(self, widget: QWidget, warp: Optional[Callable[[QPoint], bool]] = None):
        self.widget = widget
        self.warp = warp or _warp
        self.active = False
        self.warping = False

    def start(self, anchor: QPointF, current: Optional[QPointF] = None):
        """The drag begins with the pointer at `anchor` (and now at `current`, if it has moved since). The pointer stays
        visible, as the left-right arrow."""
        self.anchor = anchor.toPoint()
        self.last = (current or anchor).toPoint()
        self.active, self.warping, self._stale = True, True, 0
        self._sync: Optional[bool] = None   # whether a warp is answered by a report of the pointer at the anchor
        self.widget.setCursor(Qt.SizeHorCursor)

    def step(self, pos: QPointF) -> tuple[int, int]:
        """The pointer was reported at `pos`: how far it moved since the previous report."""
        p = pos.toPoint()
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
            if self.warping:
                self.warp(self.anchor)
            self.widget.unsetCursor()
        self.active = False
