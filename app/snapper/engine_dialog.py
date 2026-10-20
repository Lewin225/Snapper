"""Shown when "Generate using WhisperX" is used and the engine is not ready: says what is missing and offers to install
it just for Snapper, or to use an installation the user made themselves."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                               QPushButton, QStackedLayout, QVBoxLayout, QWidget)

from . import engine

LABELS = {"whisperx": "WhisperX", "torch": "PyTorch", "torchaudio": "torchaudio"}


def pick_python(parent) -> Optional[Path]:
    """Lets the user choose the Python interpreter of their own WhisperX installation (a function so tests can answer)."""
    path, _ = QFileDialog.getOpenFileName(parent, "Choose the Python that has WhisperX installed", str(Path.home()),
                                          "All files (*)")
    return Path(path) if path else None


class EngineDialog(QDialog):
    def __init__(self, status: engine.EngineStatus, parent=None):
        super().__init__(parent)
        self.setWindowTitle("WhisperX is not ready")
        self.setMinimumWidth(560)
        self.status = status
        self.installer: Optional[engine.EngineInstaller] = None

        self.intro = QLabel("Snapper uses <b>WhisperX</b> to write transcripts. It runs in a separate Python "
                            "environment, and this computer doesn't have a complete one yet.")
        self.intro.setWordWrap(True)
        self.grid = QGridLayout()
        self.grid.setColumnStretch(2, 1)
        self.verdict = QLabel()
        self.verdict.setWordWrap(True)
        self.note = QLabel("You can keep working without it: <i>Transcript → Load from video</i> and <i>Load subtitles "
                           "file…</i> need nothing extra.")
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
        self.btn_own = QPushButton("Use my own installation…")
        self.btn_cancel = QPushButton("Not now")
        self.btn_install.clicked.connect(self.install)
        self.btn_own.clicked.connect(self.use_own)
        self.btn_cancel.clicked.connect(self.reject)
        self.install_hint = QLabel()
        self.install_hint.setWordWrap(True)
        self.install_hint.setStyleSheet("color: gray;")

        # page 0: choices; page 1: installing
        choices = QWidget()
        cl = QVBoxLayout(choices)
        cl.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(self.btn_install)
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
        for mod in engine.REQUIRED:
            ver = st.versions.get(mod)
            rows.append((LABELS.get(mod, mod), ver or "", ver is not None))
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
        free = engine.free_gb(engine.ENGINE_DIR.parent)
        self.install_hint.setText(
            f"Installing downloads about 5 GB (PyTorch with its CUDA libraries) into Snapper's own data folder, needs a "
            f"network connection, and leaves nothing in your system Python. The first transcript then downloads the "
            f"speech model (about 3 GB). {free:.0f} GB free.")

    # --- install separately
    def install(self):
        self.installer = engine.EngineInstaller(self)
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
            engine.set_chosen_python(None)   # use the one just installed
            self.accept()
        else:
            self.show_status(engine.current())
            if message != "Cancelled.":
                QMessageBox.warning(self, "Installation failed", message)

    # --- use an installation the user made
    def use_own(self):
        path = pick_python(self)
        if path is None:
            return
        st = engine.check(path, "chosen")
        self.show_status(st)
        if st.ok:
            engine.set_chosen_python(path)
            self.accept()

    def reject(self):
        if self.installer and self.pages.currentIndex() == 1:
            return   # use Cancel installation, so a half-installed environment is cleaned up
        super().reject()


def ensure_engine(parent=None) -> Optional[engine.EngineStatus]:
    """The ready engine, after asking the user to set one up if needed; None if there is none (they said no)."""
    status = engine.current()
    if status.ok:
        return status
    dlg = EngineDialog(status, parent)
    if dlg.exec() != QDialog.Accepted:
        return None
    status = engine.current()
    return status if status.ok else None
