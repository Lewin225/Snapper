"""What Snapper needs from the system: libmpv and ffmpeg/ffprobe (checked at start), and the ffmpeg encoders some features
use (checked when the feature is used, since not every ffmpeg has them). Also where the two engine backends live."""
from __future__ import annotations

import functools
import shutil
import subprocess
from pathlib import Path
from typing import Optional

ENCODER_NEEDS = {
    "libx264": "the scrub proxy (fast scrubbing)",
    "libmp3lame": "exporting MP3",
}


def backend_dir(name: str) -> Path:
    """The folder of an engine backend script set ("speech_backend", "isolation_backend"): next to the app's folder in the
    repository and in the Flatpak, next to the snapper package when installed with pip."""
    here = Path(__file__).resolve()
    for base in (here.parents[2], here.parents[1]):
        if (base / name).is_dir():
            return base / name
    return here.parents[2] / name


def _os_release() -> set[str]:
    try:
        text = Path("/etc/os-release").read_text()
    except OSError:
        return set()
    ids: set[str] = set()
    for line in text.splitlines():
        if line.startswith(("ID=", "ID_LIKE=")):
            ids.update(line.split("=", 1)[1].strip().strip('"').split())
    return ids


def install_hint(missing: list[str]) -> str:
    """The command that installs the missing system packages, for this distribution when it is recognised."""
    ids = _os_release()
    want_mpv, want_ffmpeg = "libmpv" in missing, any(m in missing for m in ("ffmpeg", "ffprobe"))
    if ids & {"fedora", "rhel", "centos"}:
        pkgs = (["mpv-libs"] if want_mpv else []) + (["ffmpeg"] if want_ffmpeg else [])
        note = "\n(On Fedora, ffmpeg with MP3 and H.264 support comes from RPM Fusion: https://rpmfusion.org)" if want_ffmpeg else ""
        return "sudo dnf install " + " ".join(pkgs) + note
    if ids & {"debian", "ubuntu"}:
        return "sudo apt install " + " ".join((["libmpv2"] if want_mpv else []) + (["ffmpeg"] if want_ffmpeg else []))
    if ids & {"arch"}:
        return "sudo pacman -S " + " ".join((["mpv"] if want_mpv else []) + (["ffmpeg"] if want_ffmpeg else []))
    if ids & {"suse", "opensuse"}:
        return "sudo zypper install " + " ".join((["libmpv2"] if want_mpv else []) + (["ffmpeg"] if want_ffmpeg else []))
    return "Install " + " and ".join((["mpv's library (libmpv)"] if want_mpv else []) + (["ffmpeg"] if want_ffmpeg else [])) + \
        " with your distribution's package manager."


def missing_requirements() -> list[str]:
    """Names of what is missing from the system: "libmpv", "ffmpeg", "ffprobe" (empty when all is there)."""
    missing = []
    try:
        import mpv  # noqa: F401  (python-mpv loads libmpv when imported)
    except (OSError, ImportError):
        missing.append("libmpv")
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            missing.append(tool)
    return missing


def problem_text(missing: list[str]) -> str:
    names = {"libmpv": "libmpv (the video player library)", "ffmpeg": "ffmpeg", "ffprobe": "ffprobe (part of ffmpeg)"}
    return ("Snapper needs these, and they are not installed:\n\n  • " + "\n  • ".join(names[m] for m in missing) +
            "\n\n" + install_hint(missing))


@functools.lru_cache(maxsize=1)
def encoders() -> frozenset[str]:
    """The audio/video encoders this system's ffmpeg has."""
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    return frozenset(line.split()[1] for line in out.splitlines() if line.startswith(" ") and len(line.split()) > 1)


def has_encoder(name: str) -> bool:
    return name in encoders()


def missing_encoder_text(name: str) -> str:
    """Explains that this ffmpeg lacks an encoder a feature needs."""
    ids = _os_release()
    fix = ("On Fedora, install ffmpeg from RPM Fusion (https://rpmfusion.org), which includes it. " if ids & {"fedora", "rhel", "centos"}
           else "Install a full build of ffmpeg from your distribution (or use the Flatpak, which includes it). ")
    return f"Your ffmpeg was built without {name}, which {ENCODER_NEEDS.get(name, 'this feature')} needs. {fix}"
