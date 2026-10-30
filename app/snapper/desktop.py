"""Opening exported files with the desktop: through Qt, which uses the desktop portal inside a Flatpak sandbox."""
import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QUrl
from PySide6.QtDBus import QDBusConnection, QDBusInterface
from PySide6.QtGui import QDesktopServices


DOC_ROOT = "/run/flatpak/doc/"   # where a sandbox sees what the file chooser portal granted (the host sees it elsewhere)


def host_path(path: Path) -> Optional[Path]:
    """The path the desktop outside the sandbox knows `path` by: the path itself when it is not behind the document portal,
    else the portal's own answer (an extended attribute of its mount, on the file or on the nearest folder above it that was
    granted), or None when the portal does not say."""
    if not str(path).startswith(DOC_ROOT):
        return path
    here, rest = path, Path()
    while str(here).startswith(DOC_ROOT):
        try:
            return Path(os.fsdecode(os.getxattr(here, "user.document-portal.host-path"))) / rest
        except OSError:
            here, rest = here.parent, Path(here.name) / rest
    return None


def mount_path(path: Path) -> Path:
    """`path` as the host sees the document portal's mount: a real folder, but the portal's copy of it, not the user's own."""
    p = str(path)
    return Path(f"/run/user/{os.getuid()}/doc/" + p[len(DOC_ROOT):]) if p.startswith(DOC_ROOT) else path


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
