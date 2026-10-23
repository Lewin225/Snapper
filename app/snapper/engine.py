"""Optional engines (WhisperX for transcripts, audio-separator for vocal isolation): which Python runs each one, what is
missing from it, and installing it either into the system Python or into a private environment just for Snapper.

An engine is a set of Python packages (PyTorch and friends are several GB), so it lives outside the app. For each engine
Snapper looks for a Python in this order: the one the user chose, the one named by the engine's environment variable, the
developer's own environment, the private one Snapper installs under its data folder, and the system Python."""
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

IN_FLATPAK = Path("/.flatpak-info").exists()


@dataclass
class Engine:
    key: str                         # settings / folder name
    title: str                       # shown to the user
    modules: dict[str, str]          # importable module -> the name shown in the checklist
    gpu_packages: list[str]          # pip requirements for a GPU install (installed together)
    cpu_packages: list[str]          # ... for a CPU-only install
    cpu_pip_args: list[str]          # extra pip arguments for the CPU install (e.g. PyTorch's CPU-only wheel index)
    env_var: str                     # names a Python to use (overrides the search)
    dev_env: str                     # the developer's own environment, if present
    download_note: dict[str, str]    # what installing costs, per device, shown before it starts
    after_note: str                  # what else happens on first use
    min_free_gb: int
    purpose: str                     # one sentence: what it is for
    no_deps_packages: list[str] = field(default_factory=list)   # installed first with --no-deps (the rest are then its dependencies)

    @property
    def folder(self) -> Path:
        return media.DATA_ROOT / "engines" / self.key

    @property
    def required(self) -> list[str]:
        return list(self.modules)

    def pip_packages(self, device: str = "gpu") -> list[str]:
        override = os.environ.get(f"SNAPPER_{self.key.upper()}_PACKAGES", "").split()   # tests install a stand-in
        return override or list(self.gpu_packages if device == "gpu" else self.cpu_packages)

    def pip_args(self, device: str = "gpu") -> list[str]:
        return [] if device == "gpu" or os.environ.get(f"SNAPPER_{self.key.upper()}_PACKAGES") else list(self.cpu_pip_args)


def has_nvidia() -> bool:
    """Whether an NVIDIA GPU (driver) is present, which decides the preselected install type."""
    return bool(shutil.which("nvidia-smi")) or Path("/proc/driver/nvidia").exists() or Path("/dev/nvidia0").exists()


def default_device() -> str:
    return "gpu" if has_nvidia() else "cpu"


# PyTorch's own wheel index serves CPU-only builds (about 0.2 GB instead of several GB with the CUDA libraries)
CPU_TORCH = ["--index-url", "https://download.pytorch.org/whl/cpu", "--extra-index-url", "https://pypi.org/simple"]


WHISPERX = Engine(
    key="whisperx", title="WhisperX",
    modules={"whisperx": "WhisperX", "torch": "PyTorch", "torchaudio": "torchaudio"},
    gpu_packages=["whisperx==3.8.6", "torch==2.8.0", "torchaudio==2.8.0"],
    cpu_packages=["whisperx==3.8.6", "torch==2.8.0", "torchaudio==2.8.0"], cpu_pip_args=CPU_TORCH,
    env_var="SNAPPER_WX_PYTHON", dev_env="~/envs/wx",
    download_note={"gpu": "about 5 GB (PyTorch with its CUDA libraries)", "cpu": "about 1 GB (CPU-only PyTorch)"},
    after_note="The first transcript then downloads the speech model (about 3 GB). On a CPU, transcribing is many times slower.",
    min_free_gb=12, purpose="writes transcripts")

# audio-separator 0.47.1's own requirements, except `diffq`: that is only imported by the Demucs models, which Snapper does not
# use (BS-Roformer and MDX are), and it has no wheel for Python 3.13 on Linux, so installing it needs a C++ compiler that a Flatpak
# does not have. So audio-separator goes in with --no-deps and these are installed beside it.
_SEPARATOR_DEPS = ['audioop-lts>=0.2.1; python_version >= "3.13"', "beartype<0.19.0,>=0.18.5", "einops>=0.7", "julius>=0.2",
                   "librosa>=0.10", "ml_collections", "numpy>=2", "onnx-weekly", "onnx2torch-py313>=1.6", "packaging",
                   "pydub>=0.25", "pyyaml", "requests>=2", "resampy>=0.4", "rotary-embedding-torch<0.7.0,>=0.6.1",
                   "samplerate==0.1.0", "scipy<2.0.0,>=1.13.0", "six>=1.16", "soundfile>=0.12", "torch<3,>=2.3", "tqdm"]

SEPARATOR = Engine(
    key="separator", title="audio-separator",
    modules={"audio_separator": "audio-separator", "torch": "PyTorch", "onnxruntime": "ONNX Runtime"},
    no_deps_packages=["audio-separator==0.47.1"],
    gpu_packages=_SEPARATOR_DEPS + ["onnxruntime-gpu>=1.17"], cpu_packages=_SEPARATOR_DEPS + ["onnxruntime>=1.17"],
    cpu_pip_args=CPU_TORCH,
    env_var="SNAPPER_SEP_PYTHON", dev_env="~/envs/sep",
    download_note={"gpu": "about 5 GB (PyTorch and ONNX Runtime with their CUDA libraries)",
                   "cpu": "about 1 GB (CPU-only PyTorch and ONNX Runtime)"},
    after_note="The first time, it downloads the audio model (about 0.7 GB). On a CPU, processing is very slow.",
    min_free_gb=12, purpose="separates the dialogue from music and effects")

ENGINES = {e.key: e for e in (WHISPERX, SEPARATOR)}


def python_in(env_dir: Path) -> Path:
    return env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def system_python() -> Optional[Path]:
    """The Python on PATH, if it is the machine's (inside a Flatpak, python3 is the sandbox's, not the user's)."""
    if IN_FLATPAK:
        return None
    found = shutil.which("python3")
    return Path(found) if found else None


@dataclass
class EngineStatus:
    engine: Engine
    python: Optional[Path]                     # the interpreter that was checked (None: there is none)
    source: str = ""                           # chosen / environment / developer / snapper / system
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
            return "There is no Python environment for it yet."
        if self.error:
            return self.error
        return ("Missing: " + ", ".join(self.engine.modules[m] for m in self.missing) + "." if self.missing
                else "Ready.")


def _settings_key(engine: Engine) -> str:
    return f"engine/{engine.key}/python"


def chosen_python(engine: Engine) -> Optional[Path]:
    v = QSettings("snapper", "snapper").value(_settings_key(engine), "")
    return Path(v) if v else None


def set_chosen_python(engine: Engine, path: Optional[Path]):
    QSettings("snapper", "snapper").setValue(_settings_key(engine), str(path) if path else "")


def candidates(engine: Engine) -> list[tuple[str, Path]]:
    """The interpreters to try, best first. A chosen one, or one named by the environment variable, is authoritative."""
    if (c := chosen_python(engine)) is not None:
        return [("chosen", c)]
    if os.environ.get(engine.env_var):
        return [("environment", Path(os.environ[engine.env_var]))]
    out = [("developer", python_in(Path(engine.dev_env).expanduser())), ("snapper", python_in(engine.folder))]
    if (sp := system_python()) is not None:
        out.append(("system", sp))
    return out


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
            try:
                ver = md.version(m.replace("_", "-") + "-gpu")
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


def check(engine: Engine, python: Path, source: str = "") -> EngineStatus:
    """Asks an interpreter which of the engine's packages it has."""
    if not python.is_file() or not os.access(python, os.X_OK):
        return EngineStatus(engine, python, source, error=f"{python} is not a Python interpreter I can run.")
    try:
        # -E: ignore PYTHON* variables; the user's own site-packages (pip install --user) must stay visible
        r = subprocess.run([str(python), "-E", "-c", _PROBE % (engine.required,)], capture_output=True, text=True,
                           timeout=120)
        data = json.loads(r.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as e:
        return EngineStatus(engine, python, source, error=f"{python} could not be checked ({type(e).__name__}).")
    return EngineStatus(engine, python, source, data["python"], data["versions"], data["gpu"])


def current(engine: Engine) -> EngineStatus:
    """The first environment that is complete; failing that the one closest to complete; failing that, none at all."""
    best: Optional[EngineStatus] = None
    for source, path in candidates(engine):
        if path.is_file():
            st = check(engine, path, source)
            if st.ok:
                return st
            if best is None or len(st.missing) < len(best.missing) or best.error:
                best = st if not st.error or best is None else best
        elif source in ("chosen", "environment"):   # the user pointed at something that is not there
            return EngineStatus(engine, path, source, error=f"{path} does not exist.")
    return best or EngineStatus(engine, None)


def free_gb(path: Path) -> float:
    p = path
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free / 1e9


class EngineInstaller(QObject):
    """Installs an engine's packages in the background, either into a new private environment under Snapper's data
    folder (target "private") or into the system Python's user site (target "system", `pip install --user`).
    A private install that fails or is cancelled is removed completely, so a half-installed environment is never left."""
    progress = Signal(str)       # the latest line of output
    stage = Signal(str)          # what it is doing
    done = Signal(bool, str)     # ok, message

    def __init__(self, engine: Engine, target: str = "private", device: str = "gpu", parent=None,
                 break_system: bool = False):
        super().__init__(parent)
        assert target in ("private", "system") and device in ("gpu", "cpu")
        self.engine, self.target, self.device = engine, target, device
        self.break_system = break_system     # install into a Python its distribution marks as externally managed (PEP 668)
        self.pep668 = False                  # set when the install was refused for that reason
        self._proc: Optional[QProcess] = None
        self._tail: list[str] = []
        self._cancelled = False
        self._step = 0
        self._nodeps_done = False
        self._python: Optional[Path] = None

    def start(self):
        free = free_gb(self.engine.folder.parent)
        need = self.engine.min_free_gb if self.device == "gpu" else 4
        if free < need and not os.environ.get(f"SNAPPER_{self.engine.key.upper()}_PACKAGES"):
            self.done.emit(False, f"Not enough free disk space: {free:.0f} GB free, about {need} GB needed.")
            return
        if self.target == "system":
            self._python = system_python()
            if self._python is None:
                self.done.emit(False, "There is no system Python to install into.")
                return
            self._step = 1          # nothing to create
        else:
            shutil.rmtree(self.engine.folder, ignore_errors=True)   # a leftover from an earlier attempt
            self.engine.folder.parent.mkdir(parents=True, exist_ok=True)
            self._python = python_in(self.engine.folder)
        self._next()

    def _run(self, program: str, args: list[str]):
        self._proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        tmp = self.engine.folder.parent / "tmp"       # pip unpacks big wheels here: on disk, not in a RAM-backed /tmp
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
            self._run(sys.executable, ["-m", "venv", str(self.engine.folder)])
        elif self._step == 2:
            where = "your system Python" if self.target == "system" else "Snapper's environment"
            self.stage.emit(f"Downloading and installing {self.engine.title} into {where} (this takes a while)…")
            args = ["-m", "pip", "install", "--no-cache-dir", "--progress-bar", "off", "--no-input"]
            if self.target == "system":
                args.append("--user")        # into ~/.local, never into the system's own folders
                if self.break_system:
                    args.append("--break-system-packages")
            packages = self.engine.pip_packages(self.device)
            if self.engine.no_deps_packages and not self._nodeps_done and packages == list(
                    self.engine.gpu_packages if self.device == "gpu" else self.engine.cpu_packages):
                self._nodeps_done = True
                self._step = 1              # when this pip run is over, _next comes back here for the dependencies
                self._run(str(self._python), args + ["--no-deps"] + self.engine.no_deps_packages)
                return
            self._run(str(self._python), args + self.engine.pip_args(self.device) + packages)
        elif self._step == 3:
            self.stage.emit("Checking the installation…")
            st = check(self.engine, self._python, self.target if self.target == "system" else "snapper")
            if not st.ok:
                self._fail(st.summary())
                return
            shutil.rmtree(self.engine.folder.parent / "tmp", ignore_errors=True)
            if self.target == "system":
                set_chosen_python(self.engine, self._python)   # the system Python is not otherwise remembered
            else:
                set_chosen_python(self.engine, None)
            self.done.emit(True, f"{self.engine.title} is installed.")

    def _read(self):
        for line in bytes(self._proc.readAll()).decode(errors="replace").replace("\r", "\n").splitlines():
            if "externally-managed-environment" in line:   # pip's first line; the tail below would lose it
                self.pep668 = True
            if line.strip():
                self._tail = (self._tail + [line.strip()])[-12:]
                self.progress.emit(line.strip())

    def _finished(self, code, _status):
        if self._cancelled:
            return
        if code != 0:
            if self.pep668:
                self._fail("Your system Python is managed by your distribution's package manager, which refuses pip "
                           "installs (PEP 668).")
            else:
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
        if self.target == "private":   # a system install is pip's to keep or roll back
            shutil.rmtree(self.engine.folder, ignore_errors=True)
        shutil.rmtree(self.engine.folder.parent / "tmp", ignore_errors=True)
