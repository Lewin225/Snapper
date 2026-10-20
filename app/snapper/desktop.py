"""Opening exported files with the desktop: through Qt, which uses the desktop portal inside a Flatpak sandbox."""
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtDBus import QDBusConnection, QDBusInterface
from PySide6.QtGui import QDesktopServices


def open_file(path: Path) -> bool:
    """Opens the file in the system's default application for it."""
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def show_in_folder(path: Path) -> bool:
    """Opens the folder containing the file, with the file selected when the file manager supports that
    (org.freedesktop.FileManager1), otherwise just the folder."""
    bus = QDBusConnection.sessionBus()
    if bus.isConnected():
        fm = QDBusInterface("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                            "org.freedesktop.FileManager1", bus)
        if fm.isValid():
            reply = fm.call("ShowItems", [QUrl.fromLocalFile(str(path)).toString()], "")
            if reply.type() != reply.MessageType.ErrorMessage:
                return True
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
