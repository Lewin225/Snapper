"""Locks the pointer while a drag is on, on native Wayland (zwp_pointer_constraints_v1 + zwp_relative_pointer_v1).

Qt cannot move the pointer on Wayland, so a drag would stop at the edge of the screen. With the pointer locked it stays put, the
compositor reports how far the mouse moved instead, and when the lock ends the compositor puts the pointer back at the position
the drag began (the cursor position hint). Qt does not offer the window's wl_surface to Python, so it is found through Qt's own
library, with checks at every step; if anything is not as expected the lock is simply not available and a drag is an ordinary one.

Everything here talks to libwayland-client directly with ctypes; the protocol objects are described by hand because the
generated protocol code is not part of any library."""
from __future__ import annotations

import ctypes
import os
import sys
import threading
from typing import Optional

from PySide6.QtGui import QGuiApplication

c_void_p, c_char_p, c_int, c_uint32 = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_uint32


def debug(message: str):
    """What the lock is doing, on stderr, when SNAPPER_LOCK_DEBUG is set (for finding out why a compositor does not play along)."""
    if os.environ.get("SNAPPER_LOCK_DEBUG"):
        print(f"[pointer lock] {message}", file=sys.stderr, flush=True)


class _Message(ctypes.Structure):
    _fields_ = [("name", c_char_p), ("signature", c_char_p), ("types", ctypes.POINTER(c_void_p))]


class _Interface(ctypes.Structure):
    _fields_ = [("name", c_char_p), ("version", c_int), ("method_count", c_int), ("methods", ctypes.POINTER(_Message)),
                ("event_count", c_int), ("events", ctypes.POINTER(_Message))]


def _messages(items, keep):
    """items: [(name, signature, [type interface or None per argument])] as a C array of wl_message."""
    arr = (_Message * max(len(items), 1))()
    for i, (name, sig, types) in enumerate(items):
        t = (c_void_p * max(len(types), 1))(*[ctypes.addressof(x) if x is not None else None for x in types])
        keep.append(t)
        arr[i] = _Message(name.encode(), sig.encode(), ctypes.cast(t, ctypes.POINTER(c_void_p)))
    keep.append(arr)
    return arr


class _Protocol:
    """The wl_interface descriptions of the three protocol objects used, and libwayland's functions."""

    def __init__(self):
        self.lib = lib = ctypes.CDLL("libwayland-client.so.0")
        self.keep: list = []
        iface = lambda name, ver: _Interface(name.encode(), ver, 0, None, 0, None)
        self.constraints, self.locked = iface("zwp_pointer_constraints_v1", 1), iface("zwp_locked_pointer_v1", 1)
        self.rel_manager, self.rel_pointer = iface("zwp_relative_pointer_manager_v1", 1), iface("zwp_relative_pointer_v1", 1)
        surface = _Interface.in_dll(lib, "wl_surface_interface")
        pointer = _Interface.in_dll(lib, "wl_pointer_interface")
        region = _Interface.in_dll(lib, "wl_region_interface")
        k = self.keep

        def fill(i, methods, events):
            m, e = _messages(methods, k), _messages(events, k)
            i.method_count, i.methods, i.event_count, i.events = len(methods), ctypes.cast(m, ctypes.POINTER(_Message)), len(events), ctypes.cast(e, ctypes.POINTER(_Message))

        fill(self.constraints, [("destroy", "", []), ("lock_pointer", "noo?ou", [self.locked, surface, pointer, region, None]),
                                ("confine_pointer", "noo?ou", [self.locked, surface, pointer, region, None])], [])
        fill(self.locked, [("destroy", "", []), ("set_cursor_position_hint", "ff", [None, None]), ("set_region", "?o", [region])],
             [("locked", "", []), ("unlocked", "", [])])
        fill(self.rel_manager, [("destroy", "", []), ("get_relative_pointer", "no", [self.rel_pointer, pointer])], [])
        fill(self.rel_pointer, [("destroy", "", [])], [("relative_motion", "uuffff", [None] * 6)])
        mf = lib.wl_proxy_marshal_flags
        mf.restype, mf.argtypes = c_void_p, None   # variadic: every argument is passed as an explicit ctypes value
        lib.wl_proxy_get_version.restype, lib.wl_proxy_get_version.argtypes = c_uint32, [c_void_p]
        lib.wl_proxy_create_wrapper.restype, lib.wl_proxy_create_wrapper.argtypes = c_void_p, [c_void_p]
        lib.wl_proxy_wrapper_destroy.argtypes = [c_void_p]
        lib.wl_display_create_queue.restype, lib.wl_display_create_queue.argtypes = c_void_p, [c_void_p]
        lib.wl_event_queue_destroy.argtypes = [c_void_p]
        lib.wl_proxy_set_queue.argtypes = [c_void_p, c_void_p]
        lib.wl_display_roundtrip_queue.argtypes = [c_void_p, c_void_p]
        lib.wl_display_flush.argtypes = [c_void_p]
        lib.wl_proxy_add_listener.argtypes = [c_void_p, c_void_p, c_void_p]
        lib.wl_proxy_destroy.argtypes = [c_void_p]
        lib.wl_proxy_get_class.restype, lib.wl_proxy_get_class.argtypes = c_char_p, [c_void_p]
        self.surface_if, self.pointer_if = surface, pointer
        self.registry_if = _Interface.in_dll(lib, "wl_registry_interface")

    def call(self, proxy, opcode, iface, version, flags, *args):
        return self.lib.wl_proxy_marshal_flags(c_void_p(proxy), c_uint32(opcode), None if iface is None else ctypes.byref(iface),
                                               c_uint32(version), c_uint32(flags), *args)


_GLOBAL = ctypes.CFUNCTYPE(None, c_void_p, c_void_p, c_uint32, c_char_p, c_uint32)
_REMOVE = ctypes.CFUNCTYPE(None, c_void_p, c_void_p, c_uint32)
_MOTION = ctypes.CFUNCTYPE(None, c_void_p, c_void_p, c_uint32, c_uint32, c_int, c_int, c_int, c_int)
_STATE = ctypes.CFUNCTYPE(None, c_void_p, c_void_p)


def _window_surface(window) -> Optional[int]:
    """The wl_surface of a QWindow, through Qt's own library (see the module docstring); None if anything is not as expected."""
    import shiboken6
    gui = ctypes.CDLL("libQt6Gui.so.6")
    wl = ctypes.CDLL("libQt6WaylandClient.so.6")
    libc = ctypes.CDLL(None)

    class Dl(ctypes.Structure):
        _fields_ = [("fname", c_char_p), ("fbase", c_void_p), ("sname", c_char_p), ("saddr", c_void_p)]
    libc.dladdr.argtypes = [c_void_p, ctypes.POINTER(Dl)]

    def in_wayland_plugin(addr):
        d = Dl()
        return bool(addr) and bool(libc.dladdr(addr, ctypes.byref(d))) and d.fname is not None and b"libQt6WaylandClient" in d.fname

    handle = gui._ZNK7QWindow6handleEv
    handle.restype, handle.argtypes = c_void_p, [c_void_p]
    plat = handle(shiboken6.getCppPointer(window)[0])    # the QPlatformWindow, a base of the QWaylandWindow
    if not plat:
        return None
    vptr = c_void_p.from_address(plat).value
    if not in_wayland_plugin(vptr):
        return None
    top = plat + ctypes.c_ssize_t.from_address(vptr - 16).value   # the ABI keeps the distance to the whole object in the vtable
    if not in_wayland_plugin(c_void_p.from_address(top).value) or ctypes.c_ssize_t.from_address(c_void_p.from_address(top).value - 16).value != 0:
        return None
    f = wl._ZNK15QtWaylandClient14QWaylandWindow9wlSurfaceEv
    f.restype, f.argtypes = c_void_p, [c_void_p]
    surface = f(top)
    libwl = ctypes.CDLL("libwayland-client.so.0")
    libwl.wl_proxy_get_class.restype, libwl.wl_proxy_get_class.argtypes = c_char_p, [c_void_p]
    return surface if surface and libwl.wl_proxy_get_class(surface) == b"wl_surface" else None


class PointerLock:
    """One per application. `begin(widget, x, y)` locks the pointer on the widget's window, `take()` gives the movement since
    the last call, `end()` unlocks and asks the compositor to show the pointer at (x, y) of the window again."""

    _instance: Optional["PointerLock"] = None
    _failed = False

    @classmethod
    def get(cls) -> Optional["PointerLock"]:
        """The lock for this application, or None where it cannot be used (not Wayland, no such protocol, anything unexpected)."""
        if cls._failed:
            return None
        if cls._instance is None:
            try:
                app = QGuiApplication.instance()
                if app is None or app.platformName() != "wayland":
                    raise RuntimeError("not a Wayland session")
                cls._instance = cls(app)
            except Exception as e:
                debug(f"not available: {e!r}")
                cls._failed = True
                return None
        return cls._instance

    def __init__(self, app):
        ni = app.nativeInterface()
        self.display, self.pointer = int(ni.display()), int(ni.pointer())   # wl_display* and wl_pointer*, as integers
        if not self.display or not self.pointer:
            raise RuntimeError("no display or pointer")
        self.p = p = _Protocol()
        self._callbacks: list = []
        self.dx = self.dy = 0.0
        self.lock_state = None   # "locked", "unlocked" or None
        self._mutex = threading.Lock()
        self.constraints = self.manager = None
        self._bind_globals()
        self.locked_obj = self.rel_obj = None
        self.surface = None

    def _bind_globals(self):
        p, lib = self.p, self.p.lib
        queue = lib.wl_display_create_queue(c_void_p(self.display))
        wrapper = lib.wl_proxy_create_wrapper(c_void_p(self.display))
        lib.wl_proxy_set_queue(wrapper, queue)
        registry = p.call(wrapper, 1, p.registry_if, 1, 0, None)   # wl_display.get_registry, on a queue of its own
        found: dict[str, tuple[int, int]] = {}

        def on_global(_d, _r, name, interface, version):
            found[interface.decode()] = (name, version)
        g_cb, r_cb = _GLOBAL(on_global), _REMOVE(lambda *a: None)   # held until the roundtrip below is over
        listener = (c_void_p * 2)(ctypes.cast(g_cb, c_void_p), ctypes.cast(r_cb, c_void_p))
        lib.wl_proxy_add_listener(c_void_p(registry), ctypes.cast(listener, c_void_p), None)
        lib.wl_display_roundtrip_queue(c_void_p(self.display), c_void_p(queue))
        try:
            for attr, iface in (("constraints", p.constraints), ("manager", p.rel_manager)):
                if iface.name.decode() not in found:
                    raise RuntimeError(f"{iface.name.decode()} is not offered by the compositor")
                name, _ = found[iface.name.decode()]
                proxy = p.call(registry, 0, iface, 1, 0, c_uint32(name), c_char_p(iface.name), c_uint32(1), None)   # wl_registry.bind
                lib.wl_proxy_set_queue(c_void_p(proxy), None)    # from here on Qt's own event thread delivers its events
                setattr(self, attr, proxy)
        finally:
            lib.wl_proxy_destroy(c_void_p(registry))
            lib.wl_proxy_wrapper_destroy(c_void_p(wrapper))
            lib.wl_event_queue_destroy(c_void_p(queue))

    def begin(self, window, anchor_x: float, anchor_y: float) -> bool:
        """Locks the pointer to the window's surface; (anchor_x, anchor_y) is where it comes back after the drag."""
        if self.locked_obj is not None:
            return False
        try:
            surface = _window_surface(window)
            if not surface:
                raise RuntimeError("no surface")
            p, lib = self.p, self.p.lib
            self.surface, self.anchor = surface, (anchor_x, anchor_y)
            self.dx = self.dy = 0.0
            self.lock_state = None
            # relative motion first, then the lock
            rel = p.call(self.manager, 1, p.rel_pointer, 1, 0, None, c_void_p(self.pointer))
            motion_cb = _MOTION(self._on_motion)
            listener = (c_void_p * 1)(ctypes.cast(motion_cb, c_void_p))
            lib.wl_proxy_add_listener(c_void_p(rel), ctypes.cast(listener, c_void_p), None)
            locked = p.call(self.constraints, 1, p.locked, 1, 0, None, c_void_p(surface), c_void_p(self.pointer), None, c_uint32(1))
            state_cbs = (_STATE(lambda *a: self._set_state("locked")), _STATE(lambda *a: self._set_state("unlocked")))
            llist = (c_void_p * 2)(*[ctypes.cast(cb, c_void_p) for cb in state_cbs])
            lib.wl_proxy_add_listener(c_void_p(locked), ctypes.cast(llist, c_void_p), None)
            self._callbacks = [motion_cb, listener, state_cbs, llist]
            self.rel_obj, self.locked_obj = rel, locked
            lib.wl_display_flush(c_void_p(self.display))
            debug(f"requested, anchor {anchor_x:.0f},{anchor_y:.0f}")
            return True
        except Exception as e:
            debug(f"request failed: {e!r}")
            self.end(restore=False)
            return False

    def _set_state(self, s):
        debug(s)
        with self._mutex:
            self.lock_state = s

    def _on_motion(self, _d, _rp, _hi, _lo, dx, dy, _udx, _udy):
        with self._mutex:   # wl_fixed_t: 24.8 fixed point
            self.dx += dx / 256.0
            self.dy += dy / 256.0

    def take(self) -> tuple[float, float]:
        """The pointer's movement (in surface pixels) since the last call."""
        with self._mutex:
            d, self.dx, self.dy = (self.dx, self.dy), 0.0, 0.0
        return d

    def end(self, restore: bool = True):
        """Unlocks. The pointer reappears at the anchor given to begin (when the compositor honours the hint)."""
        p = self.p
        if self.locked_obj is not None:
            if restore and self.surface:
                p.call(self.locked_obj, 1, None, 1, 0, c_int(int(self.anchor[0] * 256)),
                       c_int(int(self.anchor[1] * 256)))      # set_cursor_position_hint (wl_fixed_t arguments)
                p.call(self.surface, 6, None, p.lib.wl_proxy_get_version(c_void_p(self.surface)), 0)   # wl_surface.commit applies it
            p.call(self.locked_obj, 0, None, 1, 1)   # destroy (flags: WL_MARSHAL_FLAG_DESTROY)
        if self.rel_obj is not None:
            p.call(self.rel_obj, 0, None, 1, 1)
        p.lib.wl_display_flush(c_void_p(self.display))
        self.locked_obj = self.rel_obj = None
        self._callbacks = []
