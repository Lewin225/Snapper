import locale
import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from . import system_check


def main():
    # File dialogs go through the desktop portal (the system's own dialog). Inside a Flatpak sandbox this is the only
    # way to reach files outside the app's own folders; elsewhere it just gives the native look. The user can override.
    os.environ.setdefault("QT_QPA_PLATFORMTHEME", "xdgdesktopportal")
    if sys.platform == "darwin":   # mpv's renderer needs OpenGL 3.2 or newer; macOS gives Qt the old 2.1 unless a core profile is asked for
        fmt = QSurfaceFormat()
        fmt.setVersion(4, 1)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        QSurfaceFormat.setDefaultFormat(fmt)   # before the application exists
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("snapper")
    # On Wayland the window is matched to its launcher entry (name and icon) by this id, which is the Flatpak's app id; where
    # Snapper is not installed as an application the bundled icon is used instead.
    app.setDesktopFileName("io.github.Lewin225.Snapper")
    app.setWindowIcon(QIcon.fromTheme("io.github.Lewin225.Snapper", QIcon(str(Path(__file__).with_name("snapper.svg")))))
    locale.setlocale(locale.LC_NUMERIC, "C")  # mpv requires it
    if missing := system_check.missing_requirements():   # before anything imports the player (which needs libmpv)
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Snapper cannot start", system_check.problem_text(missing))
        return 1
    from . import launcher
    from .start_window import StartWindow
    from .theme import apply_system_theme
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
