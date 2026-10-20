"""System theme: the palette follows the user's KDE colour scheme and updates live."""
import os, sys, tempfile
from pathlib import Path

cfg = Path(tempfile.mkdtemp())
os.environ["XDG_CONFIG_HOME"] = str(cfg)
os.environ.pop("QT_QPA_PLATFORMTHEME", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from snapper.theme import apply_system_theme, palette_from_kdeglobals

def scheme(window, view, text, sel):
    return (f"[Colors:Window]\nBackgroundNormal={window}\nForegroundNormal={text}\n"
            f"[Colors:View]\nBackgroundNormal={view}\nForegroundNormal={text}\nBackgroundAlternate={window}\n"
            f"[Colors:Button]\nBackgroundNormal={window}\nForegroundNormal={text}\n"
            f"[Colors:Selection]\nBackgroundNormal={sel}\nForegroundNormal=255,255,255\n")

(cfg / "kdeglobals").write_text(scheme("239,240,241", "255,255,255", "35,38,41", "239,117,184"))
app = QApplication(sys.argv)
apply_system_theme(app)
pal = app.palette()
assert pal.color(QPalette.Window).getRgb()[:3] == (239, 240, 241) and pal.color(QPalette.Highlight).getRgb()[:3] == (239, 117, 184)
assert pal.color(QPalette.Text).getRgb()[:3] == (35, 38, 41)
print("ok   palette built from the KDE colour scheme (light)")

(cfg / "kdeglobals").write_text(scheme("42,46,50", "27,30,32", "252,252,252", "61,174,233"))
for _ in range(30):
    QTest.qWait(100)
    if app.palette().color(QPalette.Window).getRgb()[:3] == (42, 46, 50):
        break
assert app.palette().color(QPalette.Window).getRgb()[:3] == (42, 46, 50), "changing the scheme updates a running app"
print("ok   colour scheme changed while running: palette follows")

(cfg / "kdeglobals").unlink()
assert palette_from_kdeglobals(cfg / "kdeglobals") is None
os.environ["QT_QPA_PLATFORMTHEME"] = "kde"
app.setPalette(QPalette())
before = app.palette().color(QPalette.Window).name()
apply_system_theme(app)
assert app.palette().color(QPalette.Window).name() == before
print("ok   no kdeglobals -> Qt's own palette; a real KDE platform theme is left alone")
print("THEME OK")
