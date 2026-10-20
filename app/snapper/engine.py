"""The WhisperX engine: which Python environment runs it, what is missing from it, and installing one just for Snapper.

WhisperX needs PyTorch and friends (several GB), so it lives in its own environment rather than in the app. Snapper looks
for one in this order: the one the user chose, SNAPPER_WX_PYTHON, the developer's ~/envs/wx, and the one Snapper installs
itself under its data folder."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QSettings, Signal

from . import media

REQUIRED = os.environ.get("SNAPPER_ENGINE_REQUIRED", "whisperx torch torchaudio").split()   # importable module names
PACKAGES = os.environ.get("SNAPPER_ENGINE_PACKAGES", "whisperx==3.8.6 torch==2.8.0 torchaudio==2.8.0").split()
ENGINE_DIR = media.DATA_ROOT / "engines" / "whisperx"
MIN_FREE_GB = 12            # the environment (about 7 GB) plus pip's downloads
IN_FLATPAK = Path("/.flatpak-info").exists()


def python_in(env_dir: Path) -> Path:
    return env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


@dataclass
class EngineStatus:
    python: Optional[Path]                     # the interpreter that was checked (None: there is none)
    source: str = ""                           # where it came from: chosen / environment / developer / snapper
    python_version: str = ""
    versions: dict[str, Optional[str]] = field(default_factory=dict)   # module -> installed version, None if missing
    gpu: Optional[bool] = None                 # whether PyTorch can see a GPU (None: unknown)
    error: str = ""                            # why the interpreter could not be checked

    @property
    def missing(self) -> list[str]:
        return [m for m, v in self.versions.items() if v is None]

    @property
    def ok(self) -> bool:
        return self.python is not None and not self.error and not self.missing and bool(self.versions)

    def summary(self) -> str:
        """What is wrong, in a sentence."""
        if self.python is None:
            return "There is no Python environment for WhisperX yet."
        if self.error:
            return self.error
        return "Missing: " + ", ".join(self.missing) + "." if self.missing else "Ready."


def chosen_python() -> Optional[Path]:
    v = QSettings("snapper", "snapper").value("engine/python", "")
    return Path(v) if v else None


def set_chosen_python(path: Optional[Path]):
    QSettings("snapper", "snapper").setValue("engine/python", str(path) if path else "")


def candidates() -> list[tuple[str, Path]]:
    """The interpreters to try, best first. SNAPPER_WX_PYTHON is authoritative when set (and so is a chosen one)."""
    if (c := chosen_python()) is not None:
        return [("chosen", c)]
    if os.environ.get("SNAPPER_WX_PYTHON"):
        return [("environment", Path(os.environ["SNAPPER_WX_PYTHON"]))]
    return [("developer", Path.home() / "envs/wx/bin/python"), ("snapper", python_in(ENGINE_DIR))]


_PROBE = """
import importlib.metadata as md, importlib.util as u, json, sys
out = {"python": sys.version.split()[0], "versions": {}}
for m in %r:
    try:
        spec = u.find_spec(m)
    except Exception:
        spec = None
    ver = None
    if spec is not None:
        try:
            ver = md.version(m)
        except Exception:
            ver = "installed"
    out["versions"][m] = ver
gpu = None
if out["versions"].get("torch"):
    try:
        import torch
        gpu = bool(torch.cuda.is_available())
    except Exception:
        gpu = None
out["gpu"] = gpu
print(json.dumps(out))
"""


def check(python: Path, source: str = "") -> EngineStatus:
    """Asks an interpreter which of the required packages it has."""
    if not python.is_file() or not os.access(python, os.X_OK):
        return EngineStatus(python, source, error=f"{python} is not a Python interpreter I can run.")
    try:
        r = subprocess.run([str(python), "-I", "-c", _PROBE % (REQUIRED,)], capture_output=True, text=True, timeout=120)
        data = json.loads(r.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as e:
        return EngineStatus(python, source, error=f"{python} could not be checked ({type(e).__name__}).")
    return EngineStatus(python, source, data["python"], data["versions"], data["gpu"])


def current() -> EngineStatus:
    """The first environment that exists (and what it lacks), or a status with no Python at all."""
    first_missing = None
    for source, path in candidates():
        if path.is_file():
            st = check(path, source)
            if st.ok:
                return st
            first_missing = first_missing or st
        elif source in ("chosen", "environment"):   # the user pointed at something that is not there
            return EngineStatus(path, source, error=f"{path} does not exist.")
    return first_missing or EngineStatus(None)


def free_gb(path: Path) -> float:
    p = path
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free / 1e9


class EngineInstaller(QObject):
    """Creates ENGINE_DIR (an isolated virtual environment) and pip-installs the packages into it, in the background.
    Everything is removed again if it fails or is cancelled, so a half-installed environment is never left behind."""
    progress = Signal(str)       # the latest line of output
    stage = Signal(str)          # what it is doing
    done = Signal(bool, str)     # ok, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: Optional[QProcess] = None
        self._tail: list[str] = []
        self._cancelled = False
        self._step = 0

    def start(self):
        free = free_gb(ENGINE_DIR.parent)
        if free < MIN_FREE_GB and not os.environ.get("SNAPPER_ENGINE_PACKAGES"):
            self.done.emit(False, f"Not enough free disk space: {free:.0f} GB free, about {MIN_FREE_GB} GB needed.")
            return
        shutil.rmtree(ENGINE_DIR, ignore_errors=True)   # a leftover from an earlier attempt
        ENGINE_DIR.parent.mkdir(parents=True, exist_ok=True)
        self._next()

    def _run(self, program: str, args: list[str]):
        self._proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        tmp = ENGINE_DIR.parent / "tmp"       # pip unpacks big wheels here: on disk, not in a RAM-backed /tmp
        tmp.mkdir(parents=True, exist_ok=True)
        env.insert("TMPDIR", str(tmp))
        env.insert("PIP_DISABLE_PIP_VERSION_CHECK", "1")
        env.insert("PYTHONUNBUFFERED", "1")
        self._proc.setProcessEnvironment(env)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyRead.connect(self._read)
        self._proc.finished.connect(self._finished)
        self._proc.errorOccurred.connect(lambda e: self._fail(f"could not start {program}")
                                         if e == QProcess.FailedToStart else None)
        self._proc.start(program, args)

    def _next(self):
        self._step += 1
        if self._step == 1:
            self.stage.emit("Creating a Python environment for Snapper…")
            self._run(sys.executable, ["-m", "venv", str(ENGINE_DIR)])
        elif self._step == 2:
            self.stage.emit("Downloading and installing " + ", ".join(p.split("==")[0] for p in PACKAGES) +
                            " (this takes a while)…")
            self._run(str(python_in(ENGINE_DIR)), ["-m", "pip", "install", "--no-cache-dir", "--progress-bar", "off",
                                                   "--no-input", *PACKAGES])
        elif self._step == 3:
            self.stage.emit("Checking the installation…")
            st = check(python_in(ENGINE_DIR), "snapper")
            if not st.ok:
                self._fail(st.summary())
                return
            shutil.rmtree(ENGINE_DIR.parent / "tmp", ignore_errors=True)
            self.done.emit(True, "WhisperX is installed for Snapper.")

    def _read(self):
        for line in bytes(self._proc.readAll()).decode(errors="replace").replace("\r", "\n").splitlines():
            if line.strip():
                self._tail = (self._tail + [line.strip()])[-12:]
                self.progress.emit(line.strip())

    def _finished(self, code, _status):
        if self._cancelled:
            return
        if code != 0:
            self._fail("The installation failed:\n" + "\n".join(self._tail[-6:]))
        else:
            self._next()

    def _fail(self, message: str):
        self._cleanup()
        self.done.emit(False, message)

    def cancel(self):
        self._cancelled = True
        if self._proc is not None and self._proc.state() != QProcess.NotRunning:
            self._proc.kill()
            self._proc.waitForFinished(3000)
        self._cleanup()
        self.done.emit(False, "Cancelled.")

    def _cleanup(self):
        shutil.rmtree(ENGINE_DIR, ignore_errors=True)
        shutil.rmtree(ENGINE_DIR.parent / "tmp", ignore_errors=True)
