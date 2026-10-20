"""Main window: wires the player, transcript, editor and clip list together."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSlider,
                               QSplitter, QTextEdit, QVBoxLayout, QWidget)

from . import media
from .progress import JobBars, ProxyBanner
from .clips_panel import ClipsPanel
from .editor import ClipEditor
from .model import Clip, Project
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
        self._job_state: dict[str, Optional[float]] = {}   # running job -> fraction done (None = unknown)
        self._acc = Transcript()
        self.transcript_job: Optional[TranscriptJob] = None
        self._audio_job: Optional[media.FfmpegJob] = None
        self.sub_labels: dict[int, str] = {}
        self._proxy_job: Optional[media.FfmpegJob] = None
        self._on_proxy = False

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
        vl.setContentsMargins(0, 8, 0, 0)
        self.proxy_banner = ProxyBanner()
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
        self.editor.setMinimumHeight(330)
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
        self.editor.deselect_requested.connect(self.deselect_clip)
        self.editor.edited.connect(self.on_edited)
        self.editor.play_btn.clicked.connect(self.play_selection)
        self.editor.play_btn.setFocusPolicy(Qt.NoFocus)
        self.clips.clip_selected.connect(self.edit)
        self.clips.clip_play.connect(lambda c: self.player.play_range(c.start, c.end))
        self.clips.clip_delete.connect(self.delete_clip)
        self.clips.rename_requested.connect(self.rename_value)
        self.project.structure_changed.connect(self.on_structure_changed)
        self.project.value_renamed.connect(self._renamed)
        self.project.dirty.connect(self._schedule_save)
        self._save_timer = QTimer(self, singleShot=True, interval=800, timeout=self.project.save)
        self._key_filter = KeyFilter(self)
        QApplication.instance().installEventFilter(self._key_filter)

        self._start_media()
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
        self._action(f, "&Open episode…", self.open_dialog, QKeySequence.Open)
        self._action(f, "Open &project…", self.open_project_dialog)
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
        e = m.addMenu("&Export")
        ex = self._action(e, "Export clips… (not built yet)", lambda: None)
        ex.setEnabled(False)

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
        self._fill_audio_combo()
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
            job = media.audio_job(self.media_path, self.info.duration, track)
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

    def _run_job(self, job: media.FfmpegJob, name: str, on_ok):
        self.jobs.append(job)
        state = self._job_state
        state[name] = 0.0
        self._refresh_job_label()
        job.progress.connect(lambda p: self._job_progress(name, p))

        def done(ok, err):
            state.pop(name, None)
            self._refresh_job_label()
            if ok:
                on_ok()
            else:
                self.statusBar().showMessage(f"{name} failed: {err[:200]}", 10000)
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
        job = TranscriptJob(self.media_path, self.project.audio_track, self)
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
            if ok:
                self.project.set_transcript(self.transcript().lines)
                self.statusBar().showMessage("Transcript ready", 5000)
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
            new = self.project.add(Clip(c.start, c.end, c.text, c.text_auto, dict(c.tags)))
            c.start = c.end = None
            c.text, c.text_auto = "", True
            for t in list(c.tags):   # text and number tags stay (the next line is usually the same speaker); yes/no tags reset
                if self.project.tag_kinds.get(t) == "bool":
                    del c.tags[t]
            self.editor.load_clip(c)
            self.player.seek(new.end)                       # the playhead moves on to the next line
        else:
            self.edit(self.pending)

    def delete_clip(self, clip: Clip):
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

    # ------------------------------------------------------------------ tags
    def add_tag_type(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Add tag type")
        name = QLineEdit()
        name.setPlaceholderText("for example emotion, loudness, overlap")
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
        if dlg.exec() and name.text().strip():
            self.project.add_tag_type(name.text().strip().lower(), kind.currentData())

    def rename_value(self, tag: str):
        vals = self.project.values(tag)
        if not vals:
            return
        old, ok = QInputDialog.getItem(self, f"Rename {tag}", f"Which {tag}?", vals, 0, False)
        if not ok:
            return
        new, ok = QInputDialog.getText(self, f"Rename {tag}", f"New name for {old}:", text=old)
        if ok and new.strip() and new.strip() != old:
            self.project.rename_value(tag, old, new.strip())

    # ------------------------------------------------------------------ playback + keys
    def on_position(self, t: float):
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
        path, _ = QFileDialog.getOpenFileName(self, "Open episode", str(self.media_path.parent))
        if path:
            self._open(Path(path))

    def open_project_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open project", str(media.projects_dir()),
                                              "Snapper projects (*.snapper.json)")
        if path:
            self._open(Path(path))

    def _open(self, path: Path):
        try:
            w = MainWindow(path)   # the new window opens first: closing the only window would break GL
        except Exception as e:
            QMessageBox.warning(self, "Open", str(e))
            return
        w.show()
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
        self.video.close()
        self.player.shutdown()
        super().closeEvent(e)
