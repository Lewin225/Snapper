import locale
import os
import sys
from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from .main_window import MainWindow


def dark(app: QApplication):
    app.setStyle("Fusion")
    p = QPalette()
    for role, col in ((QPalette.Window, "#25272b"), (QPalette.WindowText, "#e6e6e6"), (QPalette.Base, "#1b1d20"),
                      (QPalette.AlternateBase, "#25272b"), (QPalette.Text, "#e6e6e6"), (QPalette.Button, "#2f3237"),
                      (QPalette.ButtonText, "#e6e6e6"), (QPalette.Highlight, "#3a78c2"),
                      (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, "#2f3237"),
                      (QPalette.ToolTipText, "#e6e6e6"), (QPalette.PlaceholderText, "#8a8f98")):
        p.setColor(role, QColor(col))
    app.setPalette(p)


def main():
    # File dialogs go through the desktop portal (the system's own dialog). Inside a Flatpak sandbox this is the only
    # way to reach files outside the app's own folders; elsewhere it just gives the native look. The user can override.
    os.environ.setdefault("QT_QPA_PLATFORMTHEME", "xdgdesktopportal")
    app = QApplication(sys.argv)
    locale.setlocale(locale.LC_NUMERIC, "C")  # mpv requires it
    dark(app)
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
