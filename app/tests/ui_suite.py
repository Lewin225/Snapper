"""The basic window tests (clip editor, typing, layout, Play Clip and playhead motion) in ONE window: the video is loaded
once, and each test starts from a freshly reset window (support.reset). Each test is also runnable on its own.

usage: python tests/ui_suite.py [EPISODE.mkv]   (needs the display/GL environment from run.sh)
"""
import os
import runpy
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
os.environ.setdefault("SNAPPER_DATA", tempfile.mkdtemp())   # tests never touch the real projects

import support

TESTS = ["editor_test", "typing_test", "layout_test", "play_clip_test", "waveform_drag_test"]

app = support.application()
win = support.window()
support.SHARED = win
failed = []
for name in TESTS:
    print(f"=== {name}", flush=True)
    support.reset(win)
    try:
        runpy.run_path(str(HERE / f"{name}.py"), run_name="__main__")
    except BaseException:
        traceback.print_exc()
        print(f"FAILED: {name}", flush=True)
        failed.append(name)
win.close()
if failed:
    print("UI SUITE FAILED: " + ", ".join(failed))
    sys.exit(1)
print("UI SUITE OK")
