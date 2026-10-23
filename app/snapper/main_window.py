"""Main window: wires the player, transcript, editor and clip list together."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import QEvent, QObject, QRegularExpression, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QRegularExpressionValidator
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSlider,
                               QSplitter, QTextEdit, QVBoxLayout, QWidget)

from . import media
from . import export as exporting
from .export_dialog import ExportSettingsDialog
from .pathnames import INVALID_HELP, VALID_INPUT_PATTERN, clean_tag
from . import engine, engine_dialog, isolation, launcher, recent
from .progress import JobBars, ProxyBanner
from .titles import section_title
from .clips_panel import ClipsPanel
from .editor import ClipEditor
from .model import INVALID_HELP_TEXT, Clip, Project
from .player import Player, VideoWidget
from .transcript import Transcript, TranscriptArea, TranscriptJob, TranscriptPanel, parse_srt

HWDEC = os.environ.get("SNAPPER_HWDEC", "auto-safe")
DESELECT_TIP = ("Deselect the current clip: clears the new clip's start/end markers, or stops editing a saved clip. "
                "A saved clip keeps its timings.")


def fmt(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:06.3f}"


def is_text_entry(w) -> bool:
    """True for widgets where typed letters are text, not shortcuts. An editable combo box reports itself, not
    its inner line edit, as the focus widget, so it has to be checked explicitly."""
    return isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)) or \
        (isinstance(w, QComboBox) and w.isEditable())


class KeyFilter(QObject):
    """Cutting keys work from anywhere in the window except while typing in a text field."""

    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.win = win

    def eventFilter(self, obj, ev):
        if ev.type() != QEvent.KeyPress or not isinstance(obj, QWidget) or obj.window() is not self.win:
            return False
        fw = QApplication.focusWidget()
        if is_text_entry(fw) or is_text_entry(obj):
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape):
                if ev.key() == Qt.Key_Escape and hasattr(fw or obj, "cancel_edit"):
                    (fw or obj).cancel_edit()  # Esc discards a typed value instead of applying it
                (fw or obj).clearFocus()  # leave the text field, keep the typed value
                self.win.setFocus()
                return True
            return False
        return self.win.handle_key(ev)


FALLBACK_MARGIN = 1.0   # seconds before the end of the isolated part at which playback returns to the original


class MainWindow(QMainWindow):
    def __init__(self, path: Path):
        """`path` is a video file, or a project file (which records its video)."""
        super().__init__()
        if ".snapper" in path.name:
            self.project = Project.from_file(path)
            media_path = self._find_video(self.project)
        else:
            media_path = path
            self.project = Project(path)
        self.setWindowTitle(f"Snapper — {media_path.name}")
        self.media_path = media_path
        self.info = media.probe(media_path)
        self.player = Player(self)
        self.pending = Clip()          # the new clip being cut; tags stay set between clips
        self.jobs: list = []
        self._cancelled: set = set()   # jobs stopped on purpose: their ending is not reported as a failure
        self._job_state: dict[str, Optional[float]] = {}   # running job -> fraction done (None = unknown)
        self._acc = Transcript()
        self.transcript_job: Optional[TranscriptJob] = None
        self._audio_job: Optional[media.FfmpegJob] = None
        self.sub_labels: dict[int, str] = {}
        self._proxy_job: Optional[media.FfmpegJob] = None
        self.exporter = exporting.ExportManager(self.project, self)
        self._auto_timer = QTimer(self, interval=700, singleShot=True, timeout=self._auto_export)
        self._spinner = QTimer(self, interval=150)   # animates the 'Exporting' marker in the library
        self._pcm_waiters: dict[Path, list] = {}   # decoded audio being prepared -> who is waiting for it
        self._on_proxy = False
        self.isolation_job: Optional[isolation.IsolationJob] = None
        self._iso_live: Optional[np.ndarray] = None  # mono waveform of the isolated audio while it is being made
        self._iso_live_done = 0                      # how many frames of it are filled in
        self._playing_iso = False                    # whether the isolated audio is the one being heard

        # --- widgets
        self.video = VideoWidget(self.player)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100000)
        self.time_label = QLabel()
        self.transcript_panel = TranscriptPanel()
        self.transcript_area = TranscriptArea(self.transcript_panel)
        self.editor = ClipEditor(self.project)
        self.editor.clip = self.pending
        self.clips = ClipsPanel(self.project)
        for w in (self.video, self.slider, self.transcript_panel):
            w.setFocusPolicy(Qt.NoFocus)

        video_box = QWidget()
        vl = QVBoxLayout(video_box)
        vl.setContentsMargins(8, 8, 8, 0)
        self.proxy_banner = ProxyBanner()
        vl.addWidget(section_title("Playback"))
        vl.addWidget(self.proxy_banner)
        vl.addWidget(self.video, 1)
        vl.addWidget(self.slider)
        controls = self._build_controls()
        vl.addLayout(controls)
        bottom = QHBoxLayout()
        bottom.addWidget(self.time_label, 1)
        bottom.addWidget(QLabel("Audio track"))
        self.audio_combo = QComboBox()
        self.audio_combo.setFocusPolicy(Qt.NoFocus)
        self.audio_combo.setToolTip("Which audio track is heard, shown in the waveform, transcribed and exported")
        bottom.addWidget(self.audio_combo)
        bottom.addSpacing(16)
        bottom.addWidget(QLabel("Volume"))
        bottom.addWidget(self.volume)
        bottom.addWidget(self.mute)
        vl.addLayout(bottom)
        self.top = top = QSplitter(Qt.Horizontal)
        top.addWidget(self.transcript_area)
        top.addWidget(video_box)
        self.left = left = QSplitter(Qt.Vertical)
        left.addWidget(top)
        left.addWidget(self.editor)
        self.root = root = QSplitter(Qt.Horizontal)
        root.addWidget(left)
        root.addWidget(self.clips)
        # Only the side panels may be collapsed. The video and the editor always keep a usable size.
        for sp in (top, left, root):
            sp.setChildrenCollapsible(False)
        top.setCollapsible(0, True)    # transcript
        top.setCollapsible(1, False)   # video
        left.setCollapsible(0, False)  # video + transcript row
        left.setCollapsible(1, False)  # editor
        root.setCollapsible(0, False)  # everything on the left
        root.setCollapsible(1, True)   # clip list
        video_box.setMinimumSize(max(360, controls.sizeHint().width()), 320)
        # (the editor's own layout decides its minimum height: title, waveform, values, tags and text rows)
        left.setMinimumWidth(640)
        self.transcript_area.setMinimumWidth(120)
        self.clips.setMinimumWidth(240)
        self._panes = {"transcript": (top, 0, 200), "clips": (root, 1, 500)}
        self.setCentralWidget(root)
        self.resize(1700, 950)
        self.reset_layout()
        st = QSettings("snapper", "snapper")
        for name, sp in (("top", top), ("left", left), ("root", root)):
            state = st.value(f"layout/{name}")
            if state:
                sp.restoreState(state)

        self.status_jobs = JobBars()
        self.statusBar().addPermanentWidget(self.status_jobs)
        self.status_jobs.cancel_requested.connect(self.cancel_background_work)
        self._build_menu()

        # --- wiring
        self.player.position.connect(self.on_position)
        self.player.paused_changed.connect(self._paused_changed)
        self.slider.sliderMoved.connect(lambda v: self.player.scrub(v / 100000 * self.duration()))
        self.slider.sliderReleased.connect(lambda: self.player.seek(self.slider.value() / 100000 * self.duration()))
        self.transcript_panel.line_selected.connect(self.on_line_selected)
        self.transcript_area.generate_requested.connect(self.start_transcription)
        self.transcript_area.subtitles_requested.connect(self.load_subtitle_track)
        self.transcript_area.file_requested.connect(self.load_subtitle_file)
        self.audio_combo.currentIndexChanged.connect(self.set_audio_track)
        self.editor.wave.word_source = lambda a, b: self.transcript().words_between(a, b)
        self.editor.wave.seek_requested.connect(lambda t: self.player.seek(t))
        self.editor.wave.selection_edited.connect(self.on_wave_edited)
        self.editor.range_edited.connect(self.on_wave_edited)
        self.editor.preview_requested.connect(self.player.scrub)
        self.editor.save_requested.connect(self.commit)
        self.editor.source_requested.connect(self.on_source_requested)
        self.editor.deselect_requested.connect(self.deselect_clip)
        self.editor.edited.connect(self.on_edited)
        self.editor.play_btn.clicked.connect(self.play_selection)
        self.editor.play_btn.setFocusPolicy(Qt.NoFocus)
        self.clips.clip_selected.connect(self.edit)
        self.clips.clip_play.connect(lambda c: self.player.play_range(c.start, c.end))
        self.clips.clip_delete.connect(self.delete_clip)
        self.clips.clip_duplicate.connect(self.duplicate_clip)
        self.clips.rename_requested.connect(self.rename_value)
        self.clips.export_requested.connect(self.export_clips)
        self.clips.export_settings_requested.connect(self.edit_export_settings)
        self.clips.auto_export_toggled.connect(self.set_auto_export)
        for sig in (self.project.clip_changed, self.project.structure_changed):
            sig.connect(lambda *_: self.project.auto_export and self._auto_timer.start())
        self.project.dirty.connect(self._update_export_state)
        self.clips.model.export_status = self.exporter.status
        self._spinner.timeout.connect(self.clips.model.tick)
        self.exporter.state_changed.connect(self._export_state_changed)
        self.exporter.progress.connect(self._export_progress)
        self.exporter.idle.connect(self._export_idle)
        self.project.structure_changed.connect(self._update_export_state)
        self.project.structure_changed.connect(self.on_structure_changed)
        self.project.value_renamed.connect(self._renamed)
        self.project.dirty.connect(self._schedule_save)
        self._save_timer = QTimer(self, singleShot=True, interval=800, timeout=self.project.save)
        self._key_filter = KeyFilter(self)
        QApplication.instance().installEventFilter(self._key_filter)

        self._start_media()
        self._update_export_state()
        self.setFocus()

    # ------------------------------------------------------------------ setup
    def _build_controls(self) -> QHBoxLayout:
        """Transport and snipping buttons under the video. All are mouse-only: keys keep working from anywhere."""
        def button(text, tip, slot):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _c=False: slot())
            b.setMinimumWidth(b.sizeHint().width())  # never clip a label; the video area keeps the row's width
            return b

        self.btn_play = button("▶ Play", "Play / pause (Space)", self.player.toggle)
        def group(*widgets):
            box = QWidget()
            lay = QHBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            for w in widgets:
                lay.addWidget(w)
            return box

        stop = button("■ Stop", "Stop and return to where playback started (S)", self.player.stop)
        set_in = button("Set In (I)", "Mark the in point at the playhead", self.set_in)
        set_out = button("Set Out (O)", "Mark the out point at the playhead", self.set_out)
        deselect = button("Deselect clip (Esc)", DESELECT_TIP, self.deselect_clip)
        transport, snip = group(self.btn_play, stop), group(set_in, set_out)
        transport.layout().addStretch(1)  # buttons keep their natural width; the spare room goes after them
        side = max(transport.sizeHint().width(), deselect.sizeHint().width())
        transport.setMinimumWidth(side)   # equal-width sides keep the Set In / Set Out group exactly centred
        deselect_box = group(deselect)
        deselect_box.layout().setAlignment(deselect, Qt.AlignRight)
        deselect_box.setMinimumWidth(side)
        row = QHBoxLayout()
        row.addWidget(transport, 1)
        row.addWidget(snip, 0)
        row.addWidget(deselect_box, 1)
        self.mute = button("Mute", "Mute / unmute preview audio", self.toggle_mute)
        self.mute.setFixedWidth(64)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(120)
        self.volume.setFocusPolicy(Qt.NoFocus)
        self.volume.setToolTip("Preview volume (does not affect exported audio)")
        self.volume.valueChanged.connect(self.set_volume)
        self.volume.setValue(int(QSettings("snapper", "snapper").value("volume", 80)))
        return row

    def _build_menu(self):
        m = self.menuBar()
        f = m.addMenu("&File")
        self._action(f, "&New Project (Open Video)…", self.open_dialog, QKeySequence.Open)
        self._action(f, "Open &project…", self.open_project_dialog)
        self.menu_recent = f.addMenu("Open &recent")
        self.menu_recent.aboutToShow.connect(self._fill_recent_menu)
        self._action(f, "Save project &as…", self.save_project_as)
        f.addSeparator()
        self._action(f, "&Quit", self.close, QKeySequence.Quit)
        t = m.addMenu("&Transcript")
        self.act_gen = self._action(t, "Generate using WhisperX", self.start_transcription)
        self.menu_video_subs = t.addMenu("Load from video")
        self.menu_video_subs.aboutToShow.connect(self._fill_subtitle_menu)
        self._action(t, "Load subtitles file…", self.load_subtitle_file)
        v = m.addMenu("&View")
        self._action(v, "Show / hide transcript", lambda: self.toggle_pane("transcript"), "F2")
        self._action(v, "Show / hide clip list", lambda: self.toggle_pane("clips"), "F3")
        self._action(v, "Reset layout", self.reset_layout)
        v.addSeparator()
        self.act_proxy = self._action(v, "Use scrub proxy (fast scrubbing)", lambda: None)
        self.act_proxy.setCheckable(True)
        self.act_proxy.setChecked(True)
        self.act_proxy.toggled.connect(self.set_proxy_enabled)
        g = m.addMenu("T&ags")
        self._action(g, "Add tag type…", self.add_tag_type)
        a = m.addMenu("&Audio")
        self.act_isolate = self._action(a, "Isolate vocals using audio-separator", self.start_isolation)
        self.act_custom_audio = self._action(a, "Load custom audio replacement…", self.load_custom_audio)
        self.act_isolate_cancel = self._action(a, "Cancel isolation", self.cancel_isolation)
        self.act_isolate_cancel.setEnabled(False)
        self._action(a, "Isolation model…", self.choose_isolation_model)
        self.act_isolate_remove = self._action(a, "Remove isolated audio", self.remove_isolation)
        a.aboutToShow.connect(self._update_audio_menu)
        e = m.addMenu("&Export")
        self.act_export = self._action(e, "Export new and changed clips", lambda: self.export_clips())
        self.act_export_all = self._action(e, "Re-export all clips", lambda: self.export_clips(force=True))
        self._action(e, "Export settings…", self.edit_export_settings)

    def reset_layout(self):
        self.top.setSizes([200, 800])
        self.left.setSizes([560, 300])
        self.root.setSizes([1100, 500])

    def toggle_pane(self, name: str):
        """Collapses a side panel, or restores it to its last size."""
        sp, i, default = self._panes[name]
        sizes = sp.sizes()
        if sizes[i] == 0:
            sizes[i] = getattr(self, f"_last_{name}", default)
            sizes[1 - i] = max(sizes[1 - i] - sizes[i], 1)
        else:
            setattr(self, f"_last_{name}", sizes[i])
            sizes[1 - i] += sizes[i]
            sizes[i] = 0
        sp.setSizes(sizes)

    def _find_video(self, project: Project) -> Path:
        """The project's video, asking the user to locate it when it has moved."""
        if project.media.is_file():
            return project.media
        found, _ = QFileDialog.getOpenFileName(self, f"Locate the video for this project ({project.media.name})",
                                               str(project.media.parent if project.media.parent.is_dir() else Path.home()))
        if not found:
            raise FileNotFoundError(f"Video not found: {project.media}")
        project.set_media(Path(found))
        return Path(found)

    def _action(self, menu, text, slot, shortcut=None) -> QAction:
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(shortcut)
        a.triggered.connect(lambda _c=False: slot())
        menu.addAction(a)
        return a

    def _start_media(self):
        media.purge_old_export_audio()
        self.exporter.verify_files()
        self._fill_audio_combo()
        self._sync_isolated()
        self._load_audio()
        self._survey_subtitles()
        self.act_proxy.setChecked(self.project.proxy_enabled)
        self._use_proxy_or_original(first=True)
        if self.project.transcript is not None:
            self.set_transcript(Transcript(self.project.transcript))
        else:
            tp = media.cache_dir(self.media_path) / "transcript.json"   # early builds kept it in the cache
            if tp.exists():
                self.set_transcript(Transcript.load(tp), persist=True)
        saved = next((c for c in self.project.clips if c.id == self.project.selected_clip), None)
        self.edit(saved or self.pending)
        self.transcript_area.refresh()

    # ------------------------------------------------------------------ scrub proxy
    def _use_proxy_or_original(self, first: bool = False):
        """Plays the proxy when enabled and present, generating it in the background if needed; else the original."""
        pp = media.proxy_path(self.media_path)
        start, paused = (None, True) if first else (self.player.now(), self.player.paused)
        if self.project.proxy_enabled and pp.exists():
            media.touch_proxy(pp)
            self._load_video(str(pp), "no", start, paused)
            self._on_proxy = True
        else:
            self._load_video(str(self.media_path), HWDEC, start, paused)
            self._on_proxy = False
            if self.project.proxy_enabled and not self._proxy_job:
                self._proxy_job = media.proxy_job(self.media_path, self.info.duration)
                self.proxy_banner.generating(0.0)
                self._run_job(self._proxy_job, "proxy", self._proxy_ready)
        for gone in media.prune_proxies(keep=pp):
            print(f"[cache] removed old proxy {gone}", flush=True)

    def _load_video(self, path: str, hwdec: str, start, paused: bool):
        if start is None:
            self.player.load(path, hwdec)
        else:
            self.player.load(path, hwdec, start=start, pause=paused)

    def set_proxy_enabled(self, on: bool):
        if on == self.project.proxy_enabled:
            return
        self.project.proxy_enabled = on
        self.project.dirty.emit()
        if not on and self._proxy_job:   # stop generating a proxy nobody wants
            job, self._proxy_job = self._proxy_job, None
            for sig in (job.done, job.progress):
                try:
                    sig.disconnect()
                except RuntimeError:
                    pass
            job.kill()
            self._job_state.pop("proxy", None)
            self._refresh_job_label()
            self.proxy_banner.clear()
        if on != self._on_proxy and (on or self._on_proxy):
            self._use_proxy_or_original()


    # ------------------------------------------------------------------ audio tracks
    def _fill_audio_combo(self):
        self.audio_combo.blockSignals(True)
        self.audio_combo.clear()
        for a in self.info.audio:
            ch = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}.get(a.get("channels", 0), f"{a.get('channels', '?')}ch")
            extra = " ".join(x for x in (a["lang"], a["title"]) if x)
            self.audio_combo.addItem(f"{a['order'] + 1}: {a['codec']} {ch}" + (f" — {extra}" if extra else ""))
        track = min(self.project.audio_track, max(len(self.info.audio) - 1, 0))
        self.project.audio_track = track
        self.audio_combo.setCurrentIndex(track)
        self.audio_combo.setEnabled(len(self.info.audio) > 1)
        self.audio_combo.blockSignals(False)
        self.player.set_audio_track(track)

    def set_audio_track(self, index: int):
        if index < 0 or index == self.project.audio_track:
            return
        self.project.audio_track = index
        self.project.dirty.emit()
        self.player.set_audio_track(index)
        self._sync_isolated()
        self._load_audio()

    def _load_audio(self):
        """Waveform data for the chosen audio track: from the cache, or decoded in the background."""
        track = self.project.audio_track
        if self._audio_job:  # a decode for the previous track is no longer wanted
            for sig in (self._audio_job.done, self._audio_job.progress):
                try:
                    sig.disconnect()  # so its 'failed' result is not reported
                except RuntimeError:
                    pass
            self._audio_job.kill()
            self._audio_job = None
            self._job_state.pop("audio", None)
            self._refresh_job_label()
        if media.audio_path(self.media_path, track).exists():
            self._audio_ready(track)
        elif self.info.audio:
            self.editor.wave.set_audio(None)
            job = media.audio_job(self.info, self.info.duration, track)
            self._audio_job = job
            self._run_job(job, "audio", lambda: self._audio_ready(track))

    # ------------------------------------------------------------------ subtitle tracks
    def _text_subtitles(self) -> list[dict]:
        return [t for t in self.info.subtitles if t["codec"] in media.TEXT_SUBTITLE_CODECS]

    def _survey_subtitles(self):
        """Extracts every text subtitle track once so each can be labelled by its content."""
        tracks = self._text_subtitles()
        self._refresh_subtitle_labels()
        missing = [t["order"] for t in tracks if not media.subtitle_path(self.media_path, t["order"]).exists()]
        if missing:
            job = media.SubtitleExtractJob(self.media_path, missing, self)
            self.jobs.append(job)
            self._job_state["subtitles"] = None
            self._refresh_job_label()

            def done(_ok, _err):
                if job in self.jobs:
                    self.jobs.remove(job)
                self._job_state.pop("subtitles", None)
                self._refresh_job_label()
                self._refresh_subtitle_labels()
            job.done.connect(done)
            job.start()

    def _refresh_subtitle_labels(self):
        """Label = language/title when tagged, else the line count and first line of the track."""
        for t in self._text_subtitles():
            head = f"{t['order'] + 1}: " + (" ".join(x for x in (t["lang"], t["title"]) if x) or "untagged")
            path = media.subtitle_path(self.media_path, t["order"])
            if path.exists():
                lines = parse_srt(path.read_text(encoding="utf-8", errors="replace"))
                head += f" · {len(lines)} lines" + (f" · “{lines[0]['text'][:36]}”" if lines else "")
            self.sub_labels[t["order"]] = head
        self.transcript_area.set_tracks([(o, l) for o, l in sorted(self.sub_labels.items())])

    def _fill_subtitle_menu(self):
        self.menu_video_subs.clear()
        if not self.sub_labels:
            self.menu_video_subs.addAction("(no text subtitle tracks in this file)").setEnabled(False)
        for order, label in sorted(self.sub_labels.items()):
            self.menu_video_subs.addAction(label, lambda o=order: self.load_subtitle_track(o))

    def load_subtitle_track(self, order: int):
        try:
            path = media.extract_subtitle(self.media_path, order)
        except Exception as e:  # ffmpeg missing or the track cannot be converted
            QMessageBox.warning(self, "Subtitles", f"Could not read subtitle track {order + 1}: {e}")
            return
        self.set_transcript(Transcript(parse_srt(path.read_text(encoding="utf-8", errors="replace"))), persist=True)

    def _run_job(self, job: media.FfmpegJob, name: str, on_ok, on_fail=None):
        self.jobs.append(job)
        state = self._job_state
        state[name] = 0.0
        self._refresh_job_label()
        job.progress.connect(lambda p: self._job_progress(name, p))

        def done(ok, err):
            state.pop(name, None)
            self._refresh_job_label()
            self._update_export_state()
            if job in self.jobs:
                self.jobs.remove(job)
            if ok:
                on_ok()
            else:
                if job in self._cancelled:
                    self._cancelled.discard(job)
                    err = "cancelled"
                else:
                    self.statusBar().showMessage(f"{name} failed: {err[:200]}", 10000)
                if on_fail:
                    on_fail(err[:200])
                if name == "proxy":
                    self._proxy_job = None
                    self.proxy_banner.clear()
        job.done.connect(done)
        job.start()

    def _job_progress(self, name, fraction):
        self._job_state[name] = fraction
        self._refresh_job_label()
        if name == "proxy" and self.project.proxy_enabled:
            self.proxy_banner.generating(fraction)

    def _refresh_job_label(self):
        self.status_jobs.update_jobs(self._job_state)

    def _audio_ready(self, track: int):
        if track == self.project.audio_track:  # ignore a decode that finished after the track was changed
            self.editor.wave.set_audio(media.open_audio(media.audio_path(self.media_path, track)))
            self._load_isolated_wave()

    def _load_isolated_wave(self):
        """The isolated audio's waveform, drawn over the original's (from its finished file; or, while the job is still
        running, from what has been filled in so far)."""
        path = media.audio_path(self.media_path, self.project.audio_track, True)
        if self.isolation_job is not None and self._iso_live is not None:
            self.editor.wave.set_isolated(self._iso_live, self._iso_live_done / media.RATE)
        elif path.exists() and self.isolated_ready():
            self.editor.wave.set_isolated(media.open_audio(path))
        else:
            self.editor.wave.set_isolated(None)
        self._show_isolated_overlay()

    def _show_isolated_overlay(self):
        """The isolated waveform is shown while it is being made, and for a clip that uses it."""
        self.editor.wave.set_show_isolated(self.isolation_job is not None or self._effective_source() == "isolated")

    # ------------------------------------------------------------------ audio source (original / isolated)
    def isolated_ready(self) -> bool:
        return media.has_isolated(self.media_path, self.project.audio_track)

    def isolated_upto(self) -> float:
        """How much of the isolated audio can be used, in seconds: all of it once finished, the finished part while it is
        still being made, otherwise none."""
        if self.isolated_ready():
            return float("inf")
        if self.isolation_job is not None and self._iso_live_done:
            return self._iso_live_done / media.RATE
        return 0.0

    def isolated_usable(self) -> bool:
        return self.isolated_upto() > 0

    def _effective_source(self) -> str:
        """The audio the current clip is cut from: its own choice, unless there is no isolated audio to use."""
        return "isolated" if self.editor.clip.source == "isolated" and self.isolated_usable() else "original"

    def _playing_isolated(self, t: float) -> bool:
        """Whether the isolated audio is what is heard at time t: the clip uses it and t is inside the part that exists
        (a little before its end, since mpv reads ahead)."""
        return self.editor.clip.source == "isolated" and t < self.isolated_upto() - FALLBACK_MARGIN

    def _sync_isolated(self):
        """Tells the player about this track's isolated audio (if any), and the editor whether it can be chosen."""
        track = self.project.audio_track
        path = media.isolated_pcm_path(self.media_path, track)
        if not path.exists() and self.isolation_job is not None and self._iso_live_done:
            path = self.isolation_job.tmp_path   # still being made: the finished part can be played already
        reload_needed = self.player.set_isolated(str(path) if path.exists() else None, len(self.info.audio))
        if reload_needed:
            self._use_proxy_or_original()
        self._apply_source()

    def _apply_source(self):
        """Makes playback and the waveform follow the clip being edited."""
        self._update_playing_source(force=True)
        self._show_isolated_overlay()

    def _update_playing_source(self, force: bool = False):
        """Plays the isolated audio where it exists and the original beyond it, switching as the playhead crosses the
        boundary (while it is still being made), and shows the one in use."""
        c = self.editor.clip
        want = self._playing_isolated(self.player.pos)
        if not force and want == self._playing_iso:
            return
        self._playing_iso = want
        self.player.use_isolated(want)
        usable = self.isolated_usable()
        note = ""
        if self.isolation_job is not None and not self.isolated_ready() and usable:
            done = self.isolated_upto()
            note = f"Isolated so far up to {int(done) // 60}:{int(done) % 60:02d}; beyond it the original plays."
        shown = "original" if c.source == "isolated" and usable and not want else c.source
        self.editor.show_source(shown, usable, note)

    def on_source_requested(self, source: str):
        c = self.editor.clip
        if source == "isolated" and not self.isolated_usable():
            self.editor.show_source(c.source, False)   # the button springs back until there is something to switch to
            if self._ask_isolate_now():
                self.start_isolation()
            return
        if source == c.source:
            return
        c.source = source
        self._apply_source()
        self.on_edited()

    def _ask_isolate_now(self) -> bool:
        return QMessageBox.question(self, "Isolate vocals",
                                    "There is no isolated audio for this episode yet.\n\nIsolate the vocals now with "
                                    "audio-separator? It runs in the background while you keep working.") == QMessageBox.Yes

    def _confirm_reisolate(self) -> bool:
        return QMessageBox.question(
            self, "Isolate vocals", "This track has been isolated already. Do it again with the model set now "
            f"({isolation.model()})? The current isolated audio stays until the new one is ready.") == QMessageBox.Yes

    def toggle_source(self):
        self.on_source_requested("original" if self.editor.clip.source == "isolated" else "isolated")

    # ------------------------------------------------------------------ vocal isolation
    def _update_audio_menu(self):
        running = self.isolation_job is not None
        self.act_isolate.setEnabled(not running)
        self.act_custom_audio.setEnabled(not running)
        self.act_isolate_cancel.setEnabled(running)
        self.act_isolate_remove.setEnabled(self.isolated_ready() and not running)

    def start_isolation(self):
        if self.isolation_job:
            return
        if not self.info.audio:
            QMessageBox.information(self, "Isolate vocals", "This video has no audio to isolate.")
            return
        status = engine_dialog.ensure_engine(engine.SEPARATOR, self)   # says what is missing and offers to install it
        if status is None:
            self.statusBar().showMessage("audio-separator is not set up. Everything else works on the original audio.", 8000)
            return
        track = self.project.audio_track
        if self.isolated_ready() and not self._confirm_reisolate():
            return
        self._with_pcm(track, 2, media.ISOLATED_RATE, 16,
                       lambda pcm_in: self._run_isolation(status, track, pcm_in),
                       lambda err: self.statusBar().showMessage(f"Could not prepare the audio: {err}", 10000))

    def _run_isolation(self, status, track: int, pcm_in: Path):
        out = media.isolated_pcm_path(self.media_path, track)
        job = isolation.IsolationJob(status.python, pcm_in, out, isolation.model(), parent=self)
        self.isolation_job = job
        self._iso_live = np.zeros(pcm_in.stat().st_size // 4, dtype=np.int16)   # filled in as windows finish
        self._iso_live_done = 0
        self.editor.wave.set_isolated(self._iso_live, 0.0)
        self._show_isolated_overlay()
        job.partial.connect(lambda upto: self._isolation_partial(job, upto))
        self._job_state["isolation"] = 0.0
        self._refresh_job_label()
        job.progress.connect(lambda p: self._job_progress("isolation", p))
        job.stage.connect(lambda text: self.statusBar().showMessage(text, 20000))

        def done(ok: bool, err: str):
            self.isolation_job = None
            self._iso_live = None
            self._job_state.pop("isolation", None)
            self._refresh_job_label()
            if not ok:
                self._iso_live_done = 0
                self._sync_isolated()        # drop the half-made track from the player
                self._load_isolated_wave()   # nothing (or the earlier version) to overlay any more
            if ok:
                self._adopt_isolated_audio(track, "Vocals isolated.")
            elif err:
                QMessageBox.warning(self, "Isolating vocals failed", err)
        job.done.connect(done)
        job.start()

    def _isolation_partial(self, job, upto: float):
        """A window finished: add its part of the isolated audio to the overlay (a rough mono mix; the exact one is
        built from the finished file)."""
        if job is not self.isolation_job or self._iso_live is None:
            return
        end = min(int(upto * media.RATE), len(self._iso_live))
        lo = self._iso_live_done
        if end <= lo:
            return
        stereo = np.fromfile(job.tmp_path, dtype="<i2", count=2 * (end - lo), offset=44 + 4 * lo).reshape(-1, 2)
        self._iso_live[lo:lo + len(stereo)] = ((stereo[:, 0].astype(np.int32) + stereo[:, 1]) // 2).astype(np.int16)
        self._iso_live_done = lo + len(stereo)
        self.editor.wave.set_isolated(self._iso_live, self._iso_live_done / media.RATE)
        if lo == 0:
            self._sync_isolated()   # the first finished window: the player can add the (growing) file as a track
        else:
            self._apply_source()    # the boundary moved

    def _adopt_isolated_audio(self, track: int, message: str):
        """The isolated (or custom) audio file for `track` is in place: build its waveform, then it can be chosen."""
        if track != self.project.audio_track:
            self.statusBar().showMessage(message, 8000)
            return
        media.audio_path(self.media_path, track, True).unlink(missing_ok=True)
        self._run_job(media.audio_job(self.info, self.info.duration, track, isolated=True), "audio",
                      lambda: self._isolation_ready(track, message))

    def _pick_audio_file(self) -> Optional[Path]:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load custom audio replacement", str(self.media_path.parent),
            "Audio files (*.wav *.flac *.mp3 *.ogg *.opus *.m4a *.aac *.mka *.wma);;All files (*)")
        return Path(path) if path else None

    def _confirm_length_mismatch(self, file_len: float, episode_len: float) -> bool:
        return QMessageBox.question(
            self, "Load custom audio replacement",
            f"The file is {file_len:.1f} s long but the episode is {episode_len:.1f} s.\n\nIt will be placed at the very "
            "start of the episode, padded with silence or cut at the end. If it doesn't line up with the episode, the "
            "clips will be cut from the wrong moments.\n\nUse it anyway?") == QMessageBox.Yes

    def load_custom_audio(self):
        """Uses an audio file made elsewhere (another model, a stem from a mixing tool…) in place of the isolated audio.
        It must line up with the episode: sample N of the file is taken to be the same moment as sample N of the video."""
        if self.isolation_job:
            QMessageBox.information(self, "Load custom audio replacement", "Wait for the isolation to finish, or cancel it first.")
            return
        src = self._pick_audio_file()
        if src is None:
            return
        length = media.audio_duration(src)
        if length <= 0:
            QMessageBox.warning(self, "Load custom audio replacement", f"{src.name} is not an audio file I can read.")
            return
        if abs(length - self.info.duration) > 1.0 and not self._confirm_length_mismatch(length, self.info.duration):
            return
        if self.isolated_ready() and not self._confirm_replace_audio():
            return
        track = self.project.audio_track

        def convert(pcm_in: Path):
            frames = pcm_in.stat().st_size // 4   # exactly as many frames as the original's stereo decode
            job = media.custom_audio_job(src, frames, self.info.duration, media.isolated_pcm_path(self.media_path, track))
            self._run_job(job, "pcm", lambda: self._adopt_isolated_audio(track, f"Using {src.name} as the replacement audio."),
                          lambda err: self.statusBar().showMessage(f"Could not use {src.name}: {err}", 10000))
        self._with_pcm(track, 2, media.ISOLATED_RATE, 16, convert,
                       lambda err: self.statusBar().showMessage(f"Could not prepare the audio: {err}", 10000))

    def _confirm_replace_audio(self) -> bool:
        return QMessageBox.question(self, "Load custom audio replacement",
                                    "This track already has isolated audio. Replace it with this file?") == QMessageBox.Yes

    def _isolation_ready(self, track: int, message: str = "Vocals isolated."):
        for f in media.cache_dir(self.media_path).glob(f"export_a{track}_iso_*.pcm"):   # decodes of the previous version
            f.unlink(missing_ok=True)
        self.exporter.forget_audio()
        self._sync_isolated()
        self._load_isolated_wave()
        self.statusBar().showMessage(f"{message} Switch a clip to Isolated in the clip editor (V).", 10000)
        if self.project.auto_export:   # clips that were waiting for the isolated audio
            self._auto_timer.start()

    def cancel_background_work(self):
        """Stops everything running in the background: proxy, decoding, subtitle reading, transcription, isolation and
        exports (the clip being written finishes; the ones waiting are dropped)."""
        for j in list(self.jobs) + ([self.transcript_job] if self.transcript_job else []):
            self._cancelled.add(j)
            j.kill()
        self.cancel_isolation(quiet=True)
        self.exporter.cancel_waiting()
        self.statusBar().showMessage("Background work cancelled.", 5000)

    def cancel_isolation(self, quiet: bool = False):
        if self.isolation_job:
            job, self.isolation_job = self.isolation_job, None
            job.kill()
            self._iso_live = None
            self._iso_live_done = 0
            self._sync_isolated()
            self._load_isolated_wave()
            self._job_state.pop("isolation", None)
            self._refresh_job_label()
            if not quiet:
                self.statusBar().showMessage("Isolation cancelled.", 5000)

    def choose_isolation_model(self):
        names = [f"{label}  [{file}]" for file, label in isolation.MODELS]
        current = next((i for i, (f, _l) in enumerate(isolation.MODELS) if f == isolation.model()), 0)
        choice, ok = QInputDialog.getItem(self, "Isolation model", "Model used to separate the vocals:", names, current, False)
        if ok:
            isolation.set_model(isolation.MODELS[names.index(choice)][0])
            self.statusBar().showMessage("The model is used the next time you isolate (the first use downloads it).", 8000)

    def remove_isolation(self):
        track = self.project.audio_track
        using = [c for c in self.project.clips if c.source == "isolated"]
        if QMessageBox.question(self, "Remove isolated audio",
                                "Delete the isolated audio for this track?" +
                                (f"\n\n{len(using)} clip(s) use it and will play and export the original audio instead."
                                 if using else "")) != QMessageBox.Yes:
            return
        for c in using:
            c.source = "original"
            self.project.touch(c)
        if self.editor.clip.source == "isolated":
            self.editor.clip.source = "original"
        media.remove_isolated(self.media_path, track)
        self.exporter.forget_audio()
        self._sync_isolated()
        self._load_isolated_wave()

    def _proxy_ready(self):
        self._proxy_job = None
        if self.project.proxy_enabled:
            self._use_proxy_or_original()
            self.proxy_banner.ready()

    # ------------------------------------------------------------------ transcript
    def transcript(self) -> Transcript:
        return self.transcript_panel.transcript

    def set_transcript(self, tr: Transcript, persist: bool = False):
        """Shows a transcript; `persist` also stores it in the project (not while it is still being generated)."""
        if persist:
            self.project.set_transcript(tr.lines)
        self.transcript_panel.set_transcript(tr)
        self.transcript_panel.follow(self.player.pos)
        self.transcript_area.refresh()
        self.editor.wave.update()

    def start_transcription(self):
        if self.transcript_job:
            return
        status = engine_dialog.ensure_engine(engine.WHISPERX, self)   # says what is missing and offers to install it
        if status is None:
            self.statusBar().showMessage("WhisperX is not set up. Subtitles from the video or a file work without it.", 8000)
            return
        job = TranscriptJob(self.media_path, status.python, self.project.audio_track, self)
        self.transcript_area.set_busy("Transcribing…", 0.0)
        self.transcript_job = job
        job.lines_ready.connect(lambda lines: self._accumulate(lines))
        self._job_progress("transcript", 0.0)
        job.progress.connect(lambda p: self._job_progress("transcript", p))
        job.progress.connect(lambda p: self.transcript_area.set_busy("Transcribing…", p))

        def done(ok, err):
            self.transcript_area.set_busy(None)
            self._job_state.pop("transcript", None)
            self._refresh_job_label()
            self.transcript_job = None
            if job in self._cancelled:
                self._cancelled.discard(job)
                self.statusBar().showMessage("Transcription cancelled.", 5000)
            elif ok:
                self.project.set_transcript(self.transcript().lines)
                self.statusBar().showMessage("Transcript ready", 5000)
            elif job.cancelled:
                self.statusBar().showMessage("Transcription cancelled.", 5000)
            else:
                QMessageBox.warning(self, "Transcription failed", err)
        job.done.connect(done)
        self._acc = Transcript()
        job.start()

    def _accumulate(self, lines):
        self._acc.extend(lines)
        self.set_transcript(Transcript(self._acc.lines))

    def load_subtitle_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Subtitles", str(self.media_path.parent), "SRT (*.srt)")
        if path:
            self.set_transcript(Transcript(parse_srt(Path(path).read_text(encoding="utf-8", errors="replace"))),
                                persist=True)

    # ------------------------------------------------------------------ current clip
    def duration(self) -> float:
        return self.player.duration or self.info.duration

    def edit(self, clip: Clip):
        """Make `clip` (a stored clip or the pending one) the clip being edited."""
        self.editor.load_clip(clip)
        self._apply_source()
        self.project.select(clip.id)
        self.clips.select(clip if clip.id is not None else None)
        if clip.id is not None and clip.start is not None:
            self.player.seek(clip.start)

    def set_range(self, a, b, text: Optional[str] = None):
        if text is None and a is not None and b is not None:
            text = self.transcript().text_for(a, b)
        self.editor.set_range(a, b, text)

    def on_edited(self):
        c = self.editor.clip
        if c.id is not None:
            self.project.touch(c)
        self.editor.refresh_values()

    def on_wave_edited(self, a, b):
        self.set_range(a, b)

    def _renamed(self, tag, old, new):
        if self.pending.tags.get(tag) == old:  # the unsaved clip being cut follows the rename too
            self.pending.tags[tag] = new

    def on_structure_changed(self):
        self.editor.rebuild()
        self.clips.select(self.editor.clip if self.editor.clip.id is not None else None)

    def on_line_selected(self, i: int):
        line = self.transcript().lines[i]
        self.pending.text_auto = True
        self.edit(self.pending)
        self.set_range(line["start"], line["end"], line["text"])
        self.player.seek(line["start"])

    def commit(self):
        c = self.editor.clip
        if c.start is None or c.end is None:
            return
        if c.id is None:
            new = self.project.add(Clip(c.start, c.end, c.text, c.text_auto, dict(c.tags), source=c.source))
            c.start = c.end = None
            c.text, c.text_auto = "", True
            for t in list(c.tags):   # text and number tags stay (the next line is usually the same speaker); yes/no tags reset
                if self.project.tag_kinds.get(t) == "bool":
                    del c.tags[t]
            self.editor.load_clip(c)
            self.player.seek(new.end)                       # the playhead moves on to the next line
        else:
            self.edit(self.pending)

    def duplicate_clip(self, clip: Clip):
        """A copy with the same range, text and tags, right after the original; it opens for editing."""
        copy = self.project.add(Clip(clip.start, clip.end, clip.text, clip.text_auto, dict(clip.tags), source=clip.source))
        self.edit(copy)

    def _confirm_delete(self, clip: Clip) -> str:
        """For a clip that has an exported file: 'both' (clip and file), 'clip' (keep the file) or 'cancel'."""
        box = QMessageBox(QMessageBox.Question, "Delete clip",
                          "Delete this clip?\n\nIt has been exported as:\n" + str(clip.export_path), parent=self)
        both = box.addButton("Delete clip and exported file", QMessageBox.DestructiveRole)
        only = box.addButton("Delete clip only", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        box.exec()
        return "both" if box.clickedButton() is both else "clip" if box.clickedButton() is only else "cancel"

    def delete_clip(self, clip: Clip):
        if clip.export_path and Path(clip.export_path).exists():
            choice = self._confirm_delete(clip)
            if choice == "cancel":
                return
            if choice == "both":
                self.exporter.delete_file_of(clip)
        self.project.remove(clip)
        if self.editor.clip is clip:
            self.edit(self.pending)

    def set_in(self):
        c = self.editor.clip
        t = self.player.now()
        self.set_range(t, c.end if c.end is not None and c.end > t else None)

    def set_out(self):
        c = self.editor.clip
        if c.start is not None:
            self.set_range(c.start, max(self.player.now(), c.start))

    def deselect_clip(self):
        """Clears the markers of the new clip, or stops editing a saved clip (which keeps its timings)."""
        if self.editor.clip.id is None:
            self.pending.text_auto = True
            self.set_range(None, None, "")
        self.edit(self.pending)

    def play_from_in(self):
        c = self.editor.clip
        if c.start is not None:
            self.player.play_range(c.start, None)

    def play_selection(self):
        c = self.editor.clip
        if c.start is not None:
            self.player.play_range(c.start, c.end)

    # ------------------------------------------------------------------ export
    def _export_settings(self) -> Optional[exporting.ExportSettings]:
        return self.exporter.settings()

    def _update_export_state(self, *_):
        s = self._export_settings()
        if s is None:
            enabled, tip = False, "Set up Export Settings first."
        elif exporting.output_dir_problem(s.output_dir):
            enabled, tip = False, "Choose the export folder in Export Settings."
        elif not self.project.clips:
            enabled, tip = False, "There are no clips in the library to export."
        else:
            enabled, tip = True, "Export the clips that are new or changed since they were last exported."
        ready = s is not None and not exporting.output_dir_problem(s.output_dir)
        self.clips.set_export_enabled(
            enabled, tip, ready,
            "Export each clip automatically as soon as it is saved or changed." if ready else tip)
        self.act_export.setEnabled(enabled)
        self.act_export_all.setEnabled(enabled)

    def set_auto_export(self, on: bool):
        if on != self.project.auto_export:
            self.project.auto_export = on
            self.project.dirty.emit()
        if on:
            self._auto_timer.start()   # catches up on everything not exported yet

    def _auto_export(self):
        """Auto export: queue what is new or changed. Runs shortly after the last edit, so dragging a clip's
        handles does not export every step."""
        if self.project.auto_export and self._auto_ready():
            self.export_clips(auto=True)

    def _auto_ready(self) -> bool:
        s = self._export_settings()
        return s is not None and not exporting.output_dir_problem(s.output_dir)

    def edit_export_settings(self):
        dlg = ExportSettingsDialog(self.project, self)
        if dlg.exec():
            new = dlg.settings()
            old = self._export_settings()
            if old is not None:
                self._confirm_moves(self.project.clips, new, old.output_dir, fresh=True)
            self.project.set_export_settings(new.to_json())
            self.exporter.verify_files()
            if self.project.auto_export:
                self._auto_timer.start()

    def _confirm_moves(self, clips: list[Clip], settings: exporting.ExportSettings, old_dir: Optional[str] = None,
                       fresh: bool = False):
        """Before clips are exported to a new place (another folder, a new name or format): if their earlier files are
        still there, asks whether those may be deleted once the new copies are written. Asked every time; the answer
        is kept for those clips until they have been exported, so the export that follows does not ask again.
        `fresh` (the settings were just changed) discards earlier answers first."""
        if fresh:
            self.exporter.forget_decisions()
        moved = self.exporter.undecided(self.exporter.moved_files(clips, settings))
        if not moved:
            return
        folder = (old_dir, settings.output_dir) if old_dir and old_dir != settings.output_dir else None
        delete = self._confirm_cleanup(len(moved), folder)
        self.exporter.decide_old_file([c.id for c in moved], delete)
        if delete and old_dir:
            self.exporter.allow_cleanup(old_dir)

    def _confirm_cleanup(self, count: int, folders: Optional[tuple[str, str]]) -> bool:
        what = f"file{'s' if count != 1 else ''}"
        if folders:
            text = (f"The clips will now be exported to {folders[1]}.\n\nDelete the {count} {what} already exported "
                    f"to the old folder ({folders[0]})?")
        else:
            text = (f"{count} exported {what} will get a new name or move to a different folder, because of changed "
                    f"export settings, tags or text.\n\nDelete the old {what} once the new {'copies are' if count != 1 else 'copy is'} written?")
        box = QMessageBox(QMessageBox.Question, "Exported files are moving", text, QMessageBox.Yes | QMessageBox.No, self)
        box.setInformativeText("Each old file is deleted only after its new copy has been written, and only files "
                               "Snapper exported are touched (plus folders left empty by that).")
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def export_clips(self, force: bool = False, auto: bool = False):
        """Queues the clips that need exporting (all of them if `force`). Returns at once: the work happens in the
        background, the library shows each clip's state, and more can be queued while it runs."""
        s = self._export_settings()
        if s is None or not self.project.clips:
            return
        if (problem := exporting.output_dir_problem(s.output_dir)) and not auto:
            QMessageBox.warning(self, "Export", problem + "\nOpen Export Settings to choose a folder.")
            return
        free = [c for c in self.project.clips if self.exporter.state(c) not in ("queued", "exporting")]
        targets = free if force else self.exporter.outstanding(free, retry_failed=not auto)
        if not targets:
            if not auto:
                self.statusBar().showMessage("Everything is already exported.", 5000)
            return
        if self.isolation_job is not None and not self.isolated_ready():
            waiting = [c for c in targets if c.source == "isolated"]   # their audio is still being made
            if waiting:
                targets = [c for c in targets if c not in waiting]
                self.statusBar().showMessage(f"{len(waiting)} clip(s) use isolated audio and will export when the "
                                             "isolation has finished.", 8000)
                if not targets:
                    return
        self._confirm_moves(targets, s)
        self.exporter.mark_queued(targets)
        track = self.project.audio_track
        lost = [c for c in targets if c.source == "isolated" and not self.isolated_ready()]
        if lost:   # their isolated audio was removed or never made on this track
            self.exporter.cancel_queued(lost, "This clip uses isolated audio, which is not there. Isolate the vocals "
                                              "again (Audio menu) or switch the clip to Original.")
            targets = [c for c in targets if c not in lost]
            if not targets:
                return
        sources = sorted({c.source for c in targets})   # each source needs its own decode of the audio
        paths: dict[str, Path] = {}
        state = {"failed": False}

        def got(src: str, path: Path):
            paths[src] = path
            if len(paths) == len(sources) and not state["failed"]:
                self.exporter.submit(targets, s, paths)

        def failed(err: str):
            if not state["failed"]:
                state["failed"] = True
                self.exporter.cancel_queued(targets, f"Could not prepare the audio: {err}")
        for src in sources:
            self._with_pcm(track, s.channels, s.sample_rate, s.source_bits, lambda p, src=src: got(src, p), failed,
                           isolated=(src == "isolated"))

    def _with_pcm(self, track: int, channels: int, rate: int, bits: int, ok, fail, isolated: bool = False):
        """Calls ok(path) once this decode of the audio exists (making it first if needed)."""
        path = media.export_pcm_path(self.media_path, track, channels, rate, bits, isolated)
        if path.exists():
            ok(path)
            return
        waiters = self._pcm_waiters.get(path)
        if waiters is not None:   # already being decoded for an earlier request
            waiters.append((ok, fail))
            return
        self._pcm_waiters[path] = [(ok, fail)]
        job = media.pcm_job(self.info, self.info.duration, track, channels, rate, bits, isolated=isolated)

        def finished(good: bool, err: str = ""):
            for o, f in self._pcm_waiters.pop(path, []):
                o(path) if good else f(err)
        self._run_job(job, "pcm", lambda: finished(True), lambda err: finished(False, err))

    def _export_state_changed(self, clip_id: int):
        self.clips.model.refresh_clip(clip_id)
        if self.exporter.busy():
            if "export" not in self._job_state:
                self._job_state["export"] = 0.0
                self._refresh_job_label()
            self._spinner.start()

    def _export_progress(self, fraction: float):
        self._job_state["export"] = fraction
        self._refresh_job_label()

    def _export_idle(self):
        self._spinner.stop()
        self.clips.model.tick()
        self._job_state.pop("export", None)
        self._refresh_job_label()
        if not self.project.auto_export:
            self.statusBar().showMessage("Export finished.", 6000)
        failed = [c for c in self.project.clips if self.exporter.state(c) == "failed"]
        if failed:
            self.statusBar().showMessage(f"Export finished with {len(failed)} failed (see the library).", 10000)

    # ------------------------------------------------------------------ tags
    def add_tag_type(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Add tag type")
        name = QLineEdit()
        name.setPlaceholderText("for example emotion, loudness, overlap")
        name.setValidator(QRegularExpressionValidator(QRegularExpression(VALID_INPUT_PATTERN)))
        name.setToolTip(INVALID_HELP)
        kind = QComboBox()
        for label, k in (("String (pick or type a value)", "string"), ("Int (a number)", "int"),
                         ("Bool (yes / no checkbox)", "bool")):
            kind.addItem(label, k)
        form = QFormLayout(dlg)
        form.addRow("Name", name)
        form.addRow("Type", kind)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        while dlg.exec():
            tag = name.text().strip().lower()
            problem = Project.tag_name_problem(tag)
            if tag in self.project.tag_kinds:
                problem = f"There is already a tag called '{tag}'."
            if problem is None:
                self.project.add_tag_type(tag, kind.currentData())
                return
            QMessageBox.warning(self, "Add tag type", problem)

    def rename_value(self, tag: str):
        vals = self.project.values(tag)
        if not vals:
            return
        old, ok = QInputDialog.getItem(self, f"Rename {tag}", f"Which {tag}?", vals, 0, False)
        if not ok:
            return
        new, ok = QInputDialog.getText(self, f"Rename {tag}", f"New name for {old}:", text=old)
        if not ok or not new.strip() or new.strip() == old:
            return
        if clean_tag(new) != new.strip():
            QMessageBox.warning(self, f"Rename {tag}", INVALID_HELP_TEXT)
            return
        self.project.rename_value(tag, old, new.strip())

    # ------------------------------------------------------------------ playback + keys
    def on_position(self, t: float):
        if self.editor.clip.source == "isolated":
            self._update_playing_source()
        self.editor.wave.playhead = t
        self.editor.wave.update()
        if not self.slider.isSliderDown():
            self.slider.setValue(int(t / self.duration() * 100000))
        self.transcript_panel.follow(t, scroll=not self.player.paused)  # paused: a click or scrub must not move the list
        self.update_time_label()

    def _paused_changed(self, paused: bool):
        self.btn_play.setText("▶ Play" if paused else "❚❚ Pause")
        self.update_time_label()

    def set_volume(self, v: int):
        self.player.mpv.volume = v
        QSettings("snapper", "snapper").setValue("volume", v)

    def toggle_mute(self):
        muted = not self.player.mpv.mute
        self.player.mpv.mute = muted
        self.mute.setText("Unmute" if muted else "Mute")

    def update_time_label(self):
        self.time_label.setText(f"{fmt(self.player.pos)} / {fmt(self.duration())}   "
                                f"{'paused' if self.player.paused else 'playing'}")

    def handle_key(self, ev) -> bool:
        k, m = ev.key(), ev.modifiers()
        c = self.editor.clip
        step = 1.0 if m & Qt.ShiftModifier else 0.01 if m & Qt.ControlModifier else 0.1
        if k == Qt.Key_Space:
            self.player.toggle()
        elif k == Qt.Key_S:
            self.player.stop()
        elif k == Qt.Key_I:
            self.set_in()
        elif k == Qt.Key_O and c.start is not None:
            self.set_out()
        elif k == Qt.Key_P:
            self.play_selection()
        elif k == Qt.Key_V:
            self.toggle_source()
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            self.commit()
        elif k == Qt.Key_Escape:
            self.deselect_clip()
        elif k == Qt.Key_Delete and c.id is not None:
            self.delete_clip(c)
        elif k in (Qt.Key_Left, Qt.Key_Right):
            self.player.seek(self.player.now() + (step if k == Qt.Key_Right else -step))
        elif Qt.Key_1 <= k <= Qt.Key_9 and self.project.first_string_tag():
            tag = self.project.first_string_tag()
            vals = self.project.values(tag)
            if k - Qt.Key_1 < len(vals):
                self.editor.set_tag(tag, vals[k - Qt.Key_1])
        elif k == Qt.Key_T and self.editor.tag_boxes:
            box = next(iter(self.editor.tag_boxes.values()))
            box.setFocus()
            box.lineEdit().selectAll()
        else:
            return False
        return True

    # ------------------------------------------------------------------ misc
    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "New project: choose a video", str(self.media_path.parent), launcher.VIDEO_FILTER)
        if path:
            self._open(Path(path))

    def open_project_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open project", str(media.projects_dir()),
                                              launcher.PROJECT_FILTER)
        if path:
            self._open(Path(path))

    def _fill_recent_menu(self):
        self.menu_recent.clear()
        entries = [e for e in recent.entries() if e.path.resolve() != self.project.path.resolve()]
        for e in entries:
            self.menu_recent.addAction(f"{e.video}  ({e.clips} clips)", lambda _c=False, p=e.path: self._open(p))
        self.menu_recent.setEnabled(bool(entries))

    def _open(self, path: Path):
        w = launcher.open_path(path, self)   # the new window opens first: closing the only window would break GL
        if w is not None:
            self.close()

    def save_project_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save project as", str(self.project.path),
                                              "Snapper projects (*.snapper.json)")
        if path:
            self.project.save_as(Path(path if path.endswith(".snapper.json") else path + ".snapper.json"))
            self.statusBar().showMessage(f"Project saved to {self.project.path}", 5000)

    def _schedule_save(self):
        self._save_timer.start()

    def closeEvent(self, e):
        QApplication.instance().removeEventFilter(self._key_filter)
        st = QSettings("snapper", "snapper")
        for name, sp in (("top", self.top), ("left", self.left), ("root", self.root)):
            st.setValue(f"layout/{name}", sp.saveState())
        self.project.save()
        for j in self.jobs:
            j.kill()
        if self.transcript_job:
            self.transcript_job.kill()
        if self.isolation_job:   # never leave the worker running (it would keep the GPU busy) or its partial file behind
            self.isolation_job.kill()
            self.isolation_job = None
        self.exporter.shutdown()
        media.remove_export_audio(self.media_path)
        self.video.close()
        self.player.shutdown()
        super().closeEvent(e)
