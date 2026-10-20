import locale
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from . import launcher
from .start_window import StartWindow
from .theme import apply_system_theme


def main():
    # File dialogs go through the desktop portal (the system's own dialog). Inside a Flatpak sandbox this is the only
    # way to reach files outside the app's own folders; elsewhere it just gives the native look. The user can override.
    os.environ.setdefault("QT_QPA_PLATFORMTHEME", "xdgdesktopportal")
    app = QApplication(sys.argv)
    app.setApplicationName("snapper")
    locale.setlocale(locale.LC_NUMERIC, "C")  # mpv requires it
    apply_system_theme(app)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    # A project file opens straight away; a video opens (asking whether to resume) its project; nothing, or a
    # cancelled question, shows the start screen with the recent projects.
    window = launcher.open_path(Path(args[0])) if args else None
    if window is None:
        window = StartWindow()
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
