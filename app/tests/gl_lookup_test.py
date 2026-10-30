"""Where mpv's renderer gets its OpenGL functions from: Qt's own context first, EGL if Qt gives nothing, nothing without either."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from snapper import player


class Ctx:
    def __init__(self, table): self.table, self.asked = table, []
    def getProcAddress(self, name): self.asked.append(name); return self.table.get(name, 0)


class Egl:
    def __init__(self): self.asked = []
    def eglGetProcAddress(self, name): self.asked.append(name); return 0xE61


egl = Egl()
player._egl = egl
ctx = Ctx({b"glClear": 0x1234})
assert player.gl_proc_address(ctx, b"glClear") == 0x1234 and egl.asked == [], "Qt's answer is used, EGL is not asked"
assert player.gl_proc_address(ctx, b"glOnlyInEgl") == 0xE61 and egl.asked == [b"glOnlyInEgl"], "Qt gives nothing: EGL is asked"
assert player.gl_proc_address(None, b"glClear") == 0xE61, "no context yet: EGL"
print("ok   Qt's context first, EGL as the fallback")

player._egl = False   # no libEGL (macOS)
assert player.gl_proc_address(ctx, b"glClear") == 0x1234 and player.gl_proc_address(ctx, b"glMissing") is None and player.gl_proc_address(None, b"x") is None
print("ok   without libEGL: Qt's answer, else nothing")

player._egl = None    # the real lookup: loads libEGL where it exists, and is only ever asked once
first = player._egl_lib()
assert player._egl_lib() is first and player._egl in (False, first)
print("ok   libEGL is loaded once, or found missing without an error")
print("GL LOOKUP OK")
