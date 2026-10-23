"""Vocal isolation (the dialogue without music and effects) with audio-separator, run as a background process in the
engine's own Python environment. The worker (isolation_backend/isolate_worker.py) reads and writes raw stereo PCM and writes a WAV with
sample N the same moment in both, so the isolated audio lines up with the original."""
from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QSettings, Signal

from . import media

ISOLATION_BACKEND_DIR = Path(__file__).resolve().parents[2] / "isolation_backend"

# (file name, what to tell the user). The first is the default: the best-scoring vocal separator audio-separator offers.
MODELS = [
    ("model_bs_roformer_ep_317_sdr_12.9755.ckpt", "BS-Roformer (best quality, GPU recommended)"),
    ("vocals_mel_band_roformer.ckpt", "MelBand Roformer (a little lighter)"),
    ("UVR-MDX-NET-Voc_FT.onnx", "MDX-Net Voc FT (fast, good on CPU)"),
]
DEFAULT_MODEL = MODELS[0][0]


def model() -> str:
    return str(QSettings("snapper", "snapper").value("isolation/model", DEFAULT_MODEL)) or DEFAULT_MODEL


def set_model(name: str):
    QSettings("snapper", "snapper").setValue("isolation/model", name)


def models_dir() -> Path:
    """Where audio-separator keeps the downloaded model files (kept with the app's data, not the prunable cache)."""
    if os.environ.get("SNAPPER_MODELS_DIR"):   # lets tests (and people with a shared model folder) reuse downloads
        return Path(os.environ["SNAPPER_MODELS_DIR"]).expanduser()
    return media.DATA_ROOT / "models" / "audio-separator"


class IsolationJob(QObject):
    """Runs the worker on one stereo PCM file; progress arrives as the windows complete."""
    progress = Signal(float)
    stage = Signal(str)
    done = Signal(bool, str)

    def __init__(self, python: Path, pcm_in: Path, wav_out: Path, model_name: str, window: float = 45.0,
                 overlap: float = 5.0, parent=None):
        super().__init__(parent)
        self._buf = b""
        self._err = b""
        self._saw_done = False
        self._worker_error = ""
        self._cancelled = False
        self.device = ""
        self._out = wav_out
        self._proc = QProcess(self)
        self._proc.setProgram(str(python))
        self._proc.setArguments(["-u", str(ISOLATION_BACKEND_DIR / "isolate_worker.py"), str(pcm_in), str(wav_out),
                                 "--model", model_name, "--model-dir", str(models_dir()),
                                 "--window", str(window), "--overlap", str(overlap)])
        self._proc.readyReadStandardOutput.connect(self._read)
        self._proc.readyReadStandardError.connect(self._read_err)
        self._proc.finished.connect(self._finished)
        self._proc.errorOccurred.connect(
            lambda e: self.done.emit(False, f"could not start {python}") if e == QProcess.FailedToStart else None)

    def start(self):
        self._proc.start()

    def kill(self):
        self._cancelled = True
        self._proc.kill()
        self._proc.waitForFinished(3000)
        Path(str(self._out) + ".tmp").unlink(missing_ok=True)

    def _read_err(self):
        self._err = (self._err + bytes(self._proc.readAllStandardError()))[-6000:]

    def _read(self):
        self._buf += bytes(self._proc.readAllStandardOutput())
        *complete, self._buf = self._buf.split(b"\n")
        for raw in complete:
            if not raw.startswith(b"@@"):
                continue
            msg = json.loads(raw[2:])
            if msg.get("done"):
                self._saw_done = True
            if "error" in msg:
                self._worker_error = msg["error"]
            if "device" in msg:
                self.device = msg["device"]
            if "stage" in msg:
                self.stage.emit(msg["stage"])
            if "progress" in msg:
                self.progress.emit(msg["progress"])

    def _finished(self, code, _status):
        if self._cancelled:
            return
        self._read()
        if code == 0 and self._saw_done and self._out.exists():
            self.done.emit(True, "")
        else:
            tail = self._worker_error or "\n".join(t for t in self._err.decode(errors="replace").splitlines()[-6:] if t.strip())
            self.done.emit(False, tail or f"the isolation process exited with code {code}")
