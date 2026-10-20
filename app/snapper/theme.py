"""Matches the app to the system theme.

With a real KDE/GNOME platform theme (the KDE Flatpak runtime) Qt already styles everything, so nothing is forced.
Otherwise (a plain Qt install, such as the dev container) the palette is built from the user's KDE colour scheme
(`kdeglobals`), falling back to Qt's own light/dark palette for the desktop's colour-scheme preference. Changes to
either are picked up while the app runs.
"""
from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QFileSystemWatcher
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

# QPalette role -> (kdeglobals section, key)
_ROLES = {
    QPalette.Window: ("Colors:Window", "BackgroundNormal"), QPalette.WindowText: ("Colors:Window", "ForegroundNormal"),
    QPalette.Base: ("Colors:View", "BackgroundNormal"), QPalette.AlternateBase: ("Colors:View", "BackgroundAlternate"),
    QPalette.Text: ("Colors:View", "ForegroundNormal"), QPalette.Button: ("Colors:Button", "BackgroundNormal"),
    QPalette.ButtonText: ("Colors:Button", "ForegroundNormal"), QPalette.Highlight: ("Colors:Selection", "BackgroundNormal"),
    QPalette.HighlightedText: ("Colors:Selection", "ForegroundNormal"),
    QPalette.ToolTipBase: ("Colors:Tooltip", "BackgroundNormal"), QPalette.ToolTipText: ("Colors:Tooltip", "ForegroundNormal"),
    QPalette.Link: ("Colors:View", "ForegroundLink"), QPalette.LinkVisited: ("Colors:View", "ForegroundVisited"),
}

_watcher: Optional[QFileSystemWatcher] = None


def kdeglobals_path() -> Path:
    if os.environ.get("SNAPPER_KDEGLOBALS"):  # for a dev container whose home is not the desktop user's
        return Path(os.environ["SNAPPER_KDEGLOBALS"])
    return Path(os.environ.get("XDG_CONFIG_HOME") or "~/.config").expanduser() / "kdeglobals"


def _color(text: str) -> Optional[QColor]:
    try:
        r, g, b = (int(x) for x in text.split(",")[:3])
        return QColor(r, g, b)
    except ValueError:
        return None


def palette_from_kdeglobals(path: Path) -> Optional[QPalette]:
    """The user's KDE colour scheme as a QPalette, or None when it cannot be read."""
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str  # keys are case-sensitive
    try:
        cp.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        return None
    pal = QPalette(QGuiApplication.palette())
    found = 0
    for role, (section, key) in _ROLES.items():
        c = _color(cp.get(section, key, fallback=""))
        if c is not None:
            pal.setColor(role, c)
            found += 1
    if not found:
        return None
    win, text = pal.color(QPalette.Window), pal.color(QPalette.WindowText)
    pal.setColor(QPalette.Light, win.lighter(125))
    pal.setColor(QPalette.Midlight, win.lighter(110))
    pal.setColor(QPalette.Mid, win.darker(130))
    pal.setColor(QPalette.Dark, win.darker(165))
    pal.setColor(QPalette.Shadow, QColor(0, 0, 0))
    ph = QColor(text)
    ph.setAlpha(140)
    pal.setColor(QPalette.PlaceholderText, ph)
    off = QColor((win.red() + text.red()) // 2, (win.green() + text.green()) // 2, (win.blue() + text.blue()) // 2)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, off)
    return pal


def apply_system_theme(app: QApplication):
    """Call once after creating the QApplication."""
    global _watcher
    if "kde" in os.environ.get("QT_QPA_PLATFORMTHEME", "").lower():
        return  # the KDE platform theme supplies style and colours itself
    # Breeze when the Qt install has it (the KDE Flatpak runtime), otherwise Fusion with the colours of the KDE scheme
    app.setStyle("Breeze" if "Breeze" in QStyleFactory.keys() else "Fusion")

    def refresh():
        pal = palette_from_kdeglobals(kdeglobals_path())
        app.setPalette(pal if pal is not None else QPalette())  # QPalette() = Qt's palette for the colour scheme
        if _watcher is not None and str(kdeglobals_path()) not in _watcher.files() and kdeglobals_path().exists():
            _watcher.addPath(str(kdeglobals_path()))  # editors replace the file, which drops the watch

    _watcher = QFileSystemWatcher(app)
    _watcher.fileChanged.connect(lambda _p: refresh())
    app.styleHints().colorSchemeChanged.connect(lambda _s: refresh())
    refresh()
