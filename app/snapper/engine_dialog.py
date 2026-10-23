"""Shown when an optional tool (WhisperX, audio-separator) is used and is not ready: says what is missing and offers to
install it (for a GPU or only a CPU) just for Snapper or into the system Python, or to use an installation the user made."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                               QPushButton, QRadioButton, QStackedLayout, QVBoxLayout, QWidget)

from . import engine

def pick_python(parent, engine: engine.Engine) -> Optional[Path]:
    """Lets the user choose the Python interpreter of their own installation (a function so tests can answer)."""
    path, _ = QFileDialog.getOpenFileName(parent, f"Choose the Python that has {engine.title} installed", str(Path.home()),
                                          "All files (*)")
    return Path(path) if path else None


NOTES = {
    "whisperx": "You can keep working without it: <i>Transcript → Load from video</i> and <i>Load subtitles file…</i> need nothing extra.",
    "separator": "You can keep working without it: everything else uses the original audio.",
}


class EngineDialog(QDialog):
    def __init__(self, status: engine.EngineStatus, parent=None):
        super().__init__(parent)
        self.eng = status.engine
        self.setWindowTitle(f"{self.eng.title} is not ready")
        self.setMinimumWidth(560)
        self.status = status
        self.installer: Optional[engine.EngineInstaller] = None

        self.intro = QLabel(f"Snapper uses <b>{self.eng.title}</b>, which {self.eng.purpose}. It runs in a separate Python "
                            "environment, and this computer doesn't have a complete one yet.")
        self.intro.setWordWrap(True)
        self.grid = QGridLayout()
        self.grid.setColumnStretch(2, 1)
        self.verdict = QLabel()
        self.verdict.setWordWrap(True)
        self.note = QLabel(NOTES.get(self.eng.key, ""))
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: gray;")
        self.flatpak_note = QLabel("Snapper is running in a sandbox, so it can only use an installation it can reach: "
                                   "the one it installs for itself, or one in a folder you give it access to. A system "
                                   "Python on the host is not visible from inside.")
        self.flatpak_note.setWordWrap(True)
        self.flatpak_note.setStyleSheet("color: gray;")
        self.flatpak_note.setVisible(engine.IN_FLATPAK)

        self.btn_install = QPushButton("Install separately, just for Snapper")
        self.btn_install.setDefault(True)
        self.btn_system = QPushButton("Install into my system Python")
        self.btn_system.setVisible(engine.system_python() is not None)
        self.btn_system.setToolTip("pip install --user into the Python on your PATH: " +
                                   str(engine.system_python()))
        self.btn_system.clicked.connect(lambda: self.install("system"))
        self.break_system = False
        self.btn_own = QPushButton("Use my own installation…")
        gpu_hint = "detected" if engine.has_nvidia() else "none detected"
        self.radio_gpu = QRadioButton(f"GPU (NVIDIA CUDA, {gpu_hint}): fast, larger download")
        self.radio_cpu = QRadioButton("CPU only: smaller download, much slower")
        (self.radio_gpu if engine.default_device() == "gpu" else self.radio_cpu).setChecked(True)
        self.radio_gpu.toggled.connect(lambda _: self.show_status(self.status))
        self.btn_cancel = QPushButton("Not now")
        self.btn_install.clicked.connect(lambda: self.install("private"))
        self.btn_own.clicked.connect(self.use_own)
        self.btn_cancel.clicked.connect(self.reject)
        self.install_hint = QLabel()
        self.install_hint.setWordWrap(True)
        self.install_hint.setStyleSheet("color: gray;")

        # page 0: choices; page 1: installing
        choices = QWidget()
        cl = QVBoxLayout(choices)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.radio_gpu)
        cl.addWidget(self.radio_cpu)
        row = QHBoxLayout()
        row.addWidget(self.btn_install)
        row.addWidget(self.btn_system)
        row.addWidget(self.btn_own)
        row.addStretch(1)
        row.addWidget(self.btn_cancel)
        cl.addLayout(row)
        cl.addWidget(self.install_hint)
        busy = QWidget()
        bl = QVBoxLayout(busy)
        bl.setContentsMargins(0, 0, 0, 0)
        self.stage = QLabel()
        self.stage.setStyleSheet("font-weight: bold;")
        self.stage.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.log = QLabel()
        self.log.setStyleSheet("color: gray;")
        self.log.setWordWrap(True)
        self.log.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.btn_stop = QPushButton("Cancel installation")
        self.btn_stop.clicked.connect(self._stop)
        for w in (self.stage, self.bar, self.log):
            bl.addWidget(w)
        stop_row = QHBoxLayout()
        stop_row.addStretch(1)
        stop_row.addWidget(self.btn_stop)
        bl.addLayout(stop_row)
        self.pages = QStackedLayout()
        self.pages.addWidget(choices)
        self.pages.addWidget(busy)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        for w in (self.intro,):
            lay.addWidget(w)
        lay.addLayout(self.grid)
        lay.addWidget(self.verdict)
        lay.addLayout(self.pages)
        lay.addWidget(self.note)
        lay.addWidget(self.flatpak_note)
        self.show_status(status)

    # --- what is there
    def show_status(self, st: engine.EngineStatus):
        self.status = st
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        rows = [("Python", st.python_version and f"{st.python_version}  ({st.python})" or
                 (str(st.python) if st.python else ""), bool(st.python_version))]
        for mod, label in self.eng.modules.items():
            ver = st.versions.get(mod)
            rows.append((label, ver or "", ver is not None))
        for i, (name, detail, ok) in enumerate(rows):
            mark = QLabel("✓" if ok else "✗")
            mark.setStyleSheet("color: %s; font-weight: bold;" % ("#2e9e5b" if ok else "#d04437"))
            self.grid.addWidget(mark, i, 0)
            self.grid.addWidget(QLabel(name), i, 1)
            d = QLabel(detail if ok else ("missing" if st.python and not st.error else "not found"))
            d.setStyleSheet("color: gray;")
            self.grid.addWidget(d, i, 2)
        if st.python_version and st.gpu is not None:
            gpu = QLabel("GPU"); gpu.setStyleSheet("font-weight: normal;")
            self.grid.addWidget(QLabel("✓" if st.gpu else "–"), len(rows), 0)
            self.grid.addWidget(gpu, len(rows), 1)
            self.grid.addWidget(QLabel("PyTorch can use the GPU" if st.gpu else "PyTorch cannot see a GPU; transcribing "
                                       "would run on the CPU, much more slowly"), len(rows), 2)
        self.verdict.setText(st.summary() if not st.ok else "Everything WhisperX needs is installed.")
        free = engine.free_gb(self.eng.folder.parent)
        self.install_hint.setText(
            f"Installing downloads {self.eng.download_note[self.device()]} and needs a network connection. "
            f"<i>Separately</i> keeps it in Snapper's own data folder and leaves your system Python alone. {self.eng.after_note} "
            f"{free:.0f} GB free.")
        self.install_hint.setTextFormat(Qt.RichText)

    # --- install separately
    def _confirm_break_system(self) -> bool:
        return QMessageBox.question(
            self, "System Python is managed",
            "Your system Python belongs to your distribution's package manager, which refuses pip installs.\n\n"
            "Snapper can install anyway, into your home folder (~/.local), not the system's own folders. That is "
            "usually harmless, but it can clash with packages your distribution provides.\n\nInstall anyway? "
            "('Install separately, just for Snapper' avoids the question.)") == QMessageBox.Yes

    def device(self) -> str:
        return "gpu" if self.radio_gpu.isChecked() else "cpu"

    def install(self, target: str = "private"):
        self.installer = engine.EngineInstaller(self.eng, target, self.device(), self,
                                                break_system=target == "system" and self.break_system)
        self.installer.stage.connect(self.stage.setText)
        self.installer.progress.connect(lambda line: self.log.setText(line[:200]))
        self.installer.done.connect(self._install_done)
        self.pages.setCurrentIndex(1)
        self.installer.start()

    def _stop(self):
        if self.installer:
            self.btn_stop.setEnabled(False)
            self.installer.cancel()

    def _install_done(self, ok: bool, message: str):
        self.btn_stop.setEnabled(True)
        self.pages.setCurrentIndex(0)
        if ok:
            self.accept()
        else:
            self.show_status(engine.current(self.eng))
            if self.installer is not None and self.installer.pep668 and not self.break_system:
                if self._confirm_break_system():   # the user may allow it, into ~/.local only
                    self.break_system = True
                    self.install("system")
                    self.break_system = False
            elif message != "Cancelled.":
                QMessageBox.warning(self, "Installation failed", message)

    # --- use an installation the user made
    def use_own(self):
        path = pick_python(self, self.eng)
        if path is None:
            return
        st = engine.check(self.eng, path, "chosen")
        self.show_status(st)
        if st.ok:
            engine.set_chosen_python(self.eng, path)
            self.accept()

    def reject(self):
        if self.installer and self.pages.currentIndex() == 1:
            return   # use Cancel installation, so a half-installed environment is cleaned up
        super().reject()


def ensure_engine(eng: engine.Engine, parent=None) -> Optional[engine.EngineStatus]:
    """The ready engine, after asking the user to set one up if needed; None if there is none (they said no)."""
    status = engine.current(eng)
    if status.ok:
        return status
    dlg = EngineDialog(status, parent)
    if dlg.exec() != QDialog.Accepted:
        return None
    status = engine.current(eng)
    return status if status.ok else None
