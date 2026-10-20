import locale
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from .main_window import MainWindow
from .theme import apply_system_theme


def main():
    # File dialogs go through the desktop portal (the system's own dialog). Inside a Flatpak sandbox this is the only
    # way to reach files outside the app's own folders; elsewhere it just gives the native look. The user can override.
    os.environ.setdefault("QT_QPA_PLATFORMTHEME", "xdgdesktopportal")
    app = QApplication(sys.argv)
    locale.setlocale(locale.LC_NUMERIC, "C")  # mpv requires it
    apply_system_theme(app)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else QFileDialog.getOpenFileName(None, "Open episode")[0]
    if not path:
        return 0
    try:
        win = MainWindow(Path(path))
    except Exception as e:
        QMessageBox.critical(None, "Snapper", str(e))
        return 1
    if os.environ.get("SNAPPER_SIZE"):  # e.g. 1500x950, for checking the layout at a given window size
        w, h = os.environ["SNAPPER_SIZE"].split("x")
        win.resize(int(w), int(h))
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
