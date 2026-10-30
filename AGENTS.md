# AGENTS.md

For AI coding agents working in this repository, and for agents helping someone who uses Snapper.

Snapper is a Qt 6 / PySide6 desktop app (libmpv for playback, ffmpeg for decoding and encoding) for cutting spoken lines out
of TV episodes by hand, guided by a transcript, tagging them and exporting one audio file per line. Transcripts (WhisperX) and
dialogue isolation (audio-separator) are optional tools that live in their own Python environments and are never imported by the
app. Linux only (tested on KDE, Wayland and X11); distributed as a Flatpak bundle and as a pip/pipx wheel.

- Users read `README.md`. Design decisions, findings and what was rejected are in `SPEC.md`. Flatpak notes: `flatpak/README.md`.
- Python 3.10+. Everything is under `app/snapper` (the package), `speech_backend/` and `isolation_backend/` (scripts that run in the
  engines' environments), `flatpak/` (manifest), `app/tests/`.

---

## Part 1: working on the code

### Ground rules

- **Match the surrounding code**: comment density, naming, idiom. Comments say why, not what. No decoration.
- **Never move or click the user's real pointer or inject input** (no `ydotool`, `xdotool`, warping in a live session). The tests send
  made-up mouse events and set `SNAPPER_NO_WARP=1` for that reason. Verify pointer behaviour with a window and stand-in objects, or ask
  the user to try it.
- **Do not commit, push, publish or tag unless asked.** Nothing has been pushed to GitHub; publishing choices belong to the user.
- **Downloads are big** (a GPU install is about 5 GB, models 0.7 to 3 GB). Never trigger an engine install or a model download on the user's
  machine without asking. Use the stand-in package override (`SNAPPER_<KEY>_PACKAGES`, see below) to test the installer.
- **Do not delete user data**: projects, the export folder (auto export renames and removes files in it by design), engine folders, models.
- Personal details stay out of the tree and the git history (paths under `/home/<user>`, names, emails in files).
- The Flatpak is the reference environment (Python 3.13, Qt 6.11, KDE 6.11 runtime). A developer machine may differ; check in the sandbox.

### Running and testing

    ./run.sh [video-or-project]                  # from a checkout (needs PySide6, python-mpv, numpy, libmpv, ffmpeg)
    app/tests/run_all.sh                         # every test; fetches the Creative Commons test video on first use

The tests drive the real app (a Qt window and mpv) and need a display; some run with `QT_QPA_PLATFORM=offscreen`. They use `SNAPPER_DATA`
pointing at a temporary folder and never touch real projects. `engine_test` installs a tiny stand-in package instead of the real engines.
Running a single test or a probe inside the sandbox, which has the right Python and Qt:

    flatpak run --command=python3 --filesystem=/path/to/app:ro io.github.Lewin225.Snapper -u /path/to/app/tests/transfer_test.py

Building the bundle (outputs `build-dir`, `.flatpak-builder`, `repo` are git-ignored):

    cd flatpak
    flatpak-builder --user --force-clean --ccache --repo=repo build-dir io.github.Lewin225.Snapper.yml
    flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo repo ~/Desktop/Snapper.flatpak io.github.Lewin225.Snapper

`--runtime-repo` lets whoever installs the bundle fetch the KDE runtime from Flathub if they do not have it.

Releases are built on GitHub: `.github/workflows/release.yml` builds the wheel and the bundle when a `v*` tag is pushed and attaches both to a
draft release (the tag must equal `version` in `pyproject.toml`, and the metainfo needs a `<release>` for it). "Run workflow" on the Actions
page builds both without a release. The workflow has not run yet; the first run may need adjusting (runner disk space, bubblewrap permissions).

Dependencies are audited by `.github/workflows/security.yml` (weekly, and when `pyproject.toml`, `app/requirements.txt` or `engine.py` change): it
resolves the exact versions of the app's dependencies and of what each engine installs (read from `engine.py` by
`.github/scripts/engine_requirements.py`), and `osv_check.py` looks them up in OSV. A vulnerable version fails the run; accept an advisory
after reading it by adding its id and the reason to `.github/osv-ignore.txt`. The C libraries the Flatpak builds from source are not covered.
Dependabot (`.github/dependabot.yml`) opens weekly pull requests for newer versions.

If a build is interrupted, a stale `rofiles-fuse` mount can make the next one fail ("Transport endpoint is not connected"): unmount it
(`fusermount3 -uz`) and remove `.flatpak-builder/rofiles`. Do not match processes with `pkill -f` from a shell command that contains the
same text; it kills its own shell.

### Invariants that must not break

1. **What is highlighted on the waveform is exactly what is exported.** Selections are times, converted to sample indices at the export
   rate (44.1 kHz); export slices the same decoded PCM the waveform was drawn from, never a separate `ffmpeg -ss` seek. Container
   start-time offsets are handled once, at decode.
2. **Processed audio lines up with the original sample for sample** (same moment at sample N in both). The worker reads and writes raw PCM.
3. **A clip's export file is out of date exactly when its signature changes.** `export.export_signature` hashes everything that decides the file (including the format version and the Yes/No labels that reach it);
   `source` is added only for non-original clips so older projects stay valid.
4. **Engines run in their own Python environment and are never imported by the app.** They are only checked (importing in a subprocess)
   and run as scripts (`speech_backend/transcribe_worker.py`, `isolation_backend/isolate_worker.py`).
5. **Seeks during a scrub are coalesced** (only the newest is issued); exact seeks (not keyframe) are used while scrubbing the waveform.
6. **Nothing is cut automatically.** The user sets every in and out point.

### Source map

The columns are the file, what it is for, what it does, and why it is built that way.

| Source | Function | Behaviour | Why |
|---|---|---|---|
| `app/snapper/__main__.py` | Entry point (`snapper` command, `python -m snapper`) | Sets the file-dialog platform theme to the desktop portal, the app name and desktop file name (`io.github.Lewin225.Snapper`) and window icon, checks libmpv and ffmpeg before importing the player, opens a path given on the command line or shows the start window | Portal dialogs are the only way out of the Flatpak sandbox; the desktop file name is what Wayland compositors use to pick the launcher icon; libmpv is checked first because importing the player fails without it |
| `main_window.py` | `MainWindow`: wires everything | Menus, shortcuts (`KeyFilter` ignores keys while typing in a field), playback and clip state, scrub handling, project save and restore, starting transcript, isolation and export jobs, engine setup, status bar | One place owns the state the panels share; panels stay dumb and emit signals |
| `player.py` | `Player` (mpv wrapper), `VideoWidget` (OpenGL) | mpv plays the audio and the video follows; pause/seek/volume/mute; `scrub(t, exact)` keeps only the newest pending seek and issues it with `command_async`; hardware decoding from `SNAPPER_HWDEC` | The user found mpv's audio accurate enough for cutting, so there is no custom playback engine; coalescing keeps dragging responsive on long files |
| `waveform.py` | `WaveformWidget`: the clip editor's wave | Draws the decoded PCM (original always, processed once it exists), word labels, in/out handles; left-drag scrubs (no clip) or pans (clip selected); right-drag selects; wheel zooms; snaps to words | Fine editing needs the sample-accurate view the export slices |
| `editor.py` | `ClipEditor` | Waveform plus start, end, length fields, tags, text, Original/Processed buttons, Save/Done | The panel where one clip is made or changed |
| `scrubber.py` | `TimeScrubber`: a time field adjusted by dragging | Drag left/right changes the value like a DAW number field; uses `RelativeDrag`; typed times parsed by `parse_time` | Fast fine adjustment without leaving the keyboard or mouse |
| `drag.py` | `RelativeDrag`: endless dragging | Reads movement as distance since last time; on Wayland starts a pointer lock (`wayland_lock.py`) and counts it only once the compositor grants it, else (X11) warps the pointer back after each move, else an ordinary drag. Keeps the left-right arrow cursor | Ball mice and small pads must scrub any distance without hitting the screen edge; every fallback leaves a working drag |
| `wayland_lock.py` | `PointerLock`: native Wayland pointer lock | `zwp_pointer_constraints_v1.lock_pointer` (oneshot) + `zwp_relative_pointer_v1`, with the cursor position hint and a surface commit to put the pointer back. Finds the window's `wl_surface` through Qt's own library (`QWindow::handle()`, Itanium-ABI offset-to-top, exported `QWaylandWindow::wlSurface()`), accepting the wayland-egl plugin's `QWaylandEglWindow` (the window with the video) | Qt cannot move the pointer on Wayland and does not expose the surface to Python; the checks make an unexpected Qt build fail soft (no lock). Debug with `SNAPPER_LOCK_DEBUG=1` |
| `tape_scrub.py` | `TapeVoice`, `TapeScrub`: scrub sound | Plays the audio under the cursor from decoded samples at the drag speed (tape: varispeed with 50 ms smoothing; granular: Hann-windowed grains aligned WSOLA-style so pitch stays put), silent when still; output through `libpulse-simple` with ctypes; gain follows the volume curve (cubed) and mute, times `LEVEL` | mpv can only play forward from a seek, so it cannot do kinesthetic scrubbing. Qt Multimedia segfaulted when listing devices, so PulseAudio is used directly (`available()` is false without it and scrubbing is then silent) |
| `transcript.py` | `Transcript`, `parse_srt`, `TranscriptJob`, `TranscriptPanel` | Transcript lines with optional word times; subtitle fallback from the video or an `.srt`; `TranscriptJob` runs the WhisperX worker in the engine environment and reads one `@@{json}` line per finished window | Windowed output lets the panel fill in while it runs; word times give snapping and word-level selection |
| `model.py` | `Clip`, `Project`, `ClipTableModel`, `ClipFilter` | The project is one JSON file `<video>-<hash>.snapper.json` in the data folder: video path (absolute and relative), transcript, clips, tag types and values, the words of each Yes/No tag (`tag_labels`; default `<tag>-yes` / `<tag>-no`, used wherever the tag becomes text), selected clip, audio track, playhead `position`, unsaved half-cut clip `pending`, export settings | Nothing is written beside the video (required in the Flatpak); the saved position and pending clip let a project reopen where it was left |
| `clips_panel.py` | `ClipsPanel`: the library | Clip table with per-tag filters, Export Settings, Export, Auto export, context menu (duplicate, delete, open containing folder, open in system app) | The right-hand pane |
| `export.py` | Naming, folders, WAV and MP3 writing, `ExportManager` | Plans file names and tag folders from the template, builds each clip's ID3 tag (`clip_tag`), writes WAV in Python (`fmt `, `data`, `ID3 ` chunks), encodes MP3 through ffmpeg (`libmp3lame`, audio only) and puts the tag in front, runs a background worker per clip, removes/renames files when settings or tags change, keeps per-clip signatures | Auto export must be exact and repeatable; the signature makes "changed" mean exactly what affects the file |
| `id3.py` | ID3v2.3 writing and reading | Text, comment, lyrics (USLT) and TXXX frames (ISO-8859-1, or UTF-16 when needed), the tag header, `size_of` (also used to cut ffmpeg's empty tag off an MP3), and `parse` to read tags back | One tag for MP3 and WAV, written by Snapper, so nothing depends on ffmpeg's tag table or the command-line length (see `docs/export-format.md`) |
| `export_dialog.py` | `ExportSettingsDialog` | Folder, name template, format, channels, rate, depth, tag embedding, the table of what goes where in the ID3 tag (clip text and synced text fixed and read-only, one choice of field per tag; a warning when two tags share a field), tag folder order, validation | All the choices that go into the signature |
| `media.py` | Probing, caches, ffmpeg jobs | `ffprobe` for tracks and subtitles; `DATA_ROOT` and `CACHE_ROOT` (`SNAPPER_DATA`/`SNAPPER_CACHE` or XDG; in the Flatpak they land in `~/.var/app/io.github.Lewin225.Snapper`); decoded PCM, scrub proxies (480p, pruned oldest-first above 2 GB), subtitle extraction, custom processed audio import | Decode once and share it; the proxy makes scrubbing fast on slow storage |
| `isolation.py` | `IsolationJob`, model choice | Runs `isolate_worker.py` in the audio-separator environment as a QProcess; models: BS-Roformer (default), MelBand Roformer, MDX-Net Voc FT; usable while partial | Long files are processed in windows so the first part is usable early |
| `engine.py` | Optional engine management | `Engine` descriptions (WhisperX; audio-separator), finding a working interpreter (chosen, `SNAPPER_WX_PYTHON`/`SNAPPER_SEP_PYTHON`, developer `~/envs/...`, Snapper's private folder, system), checking required modules, `EngineInstaller` (private venv or `pip --user`), `TransferMeter` (pip `--progress-bar raw`: bytes, rate, time left). audio-separator is installed with `--no-deps` plus its requirements without `diffq` and with `audioread` | The packages are huge and need PyTorch, so they are not bundled. `diffq` only serves the Demucs models (unused) and has no Python 3.13 wheel; audio-separator imports `audioread` without declaring it |
| `engine_dialog.py` | `EngineDialog`, `ensure_engine` | Says what is missing, offers GPU/CPU, private/system install or an existing installation; shows progress and a cancel button | The user must consent before gigabytes are downloaded |
| `system_check.py` | Requirements | libmpv and ffmpeg/ffprobe at start (with the install command for the distribution); encoders (`libx264`, `libmp3lame`) only when used; where the backends live | Stock Fedora ffmpeg lacks the encoders; a late, specific message beats a crash |
| `launcher.py` | Opening things | Video (asks to resume its project) or project file; `back_up` sets a project aside as `.bak`; window size via `SNAPPER_SIZE` | Command line, start screen and File menu behave the same |
| `recent.py`, `start_window.py` | Recent projects and the start screen | Paths only in `QSettings`; everything shown is read from the project file | A single source of truth |
| `progress.py` | Status-bar bars, proxy banner | One bar per background job, with cancel | Several jobs run at once |
| `desktop.py` | Opening files and folders | `QDesktopServices` (portal in the Flatpak); the file manager's `ShowItems` to select a file | Works inside the sandbox |
| `theme.py` | Follow the desktop | Real platform theme when present, else a palette from `kdeglobals` (`SNAPPER_KDEGLOBALS`) | The Flatpak shares the colour scheme read-only |
| `pathnames.py`, `titles.py` | Safe file and folder names; pane headings | Cleans tag text for file systems | Exports must work on every platform |
| `snapper.svg` | Window icon fallback | Used when no installed icon of the same name exists | The Flatpak installs the real icon; a pip install does not |
| `speech_backend/` | Transcription | `contract.py` (neutral `SpeechBackend`), `whisperx_backend.py`, `windowed.py`, `transcribe_worker.py` (runs in the WhisperX environment) | Another engine can be swapped in without touching the app |
| `isolation_backend/isolate_worker.py` | Vocal separation | Runs in the audio-separator environment, writes PCM per window | Same alignment guarantee as above |
| `app/tests/` | Tests | `run_all.sh` order: smoke, ui_suite (editor, typing, layout, play-clip and waveform-drag tests in one window), progress, project, tag_kinds, theme, prune, launcher, system_check, transfer, drag_lock, engine, isolation, transcript_ui, id3, export, export_ui; `support.py` has the shared helpers | Tests exercise the real UI because most defects were interaction defects |
| `flatpak/` | Packaging | Manifest on the KDE 6.11 runtime with `io.qt.PySide.BaseApp`, `snapper.sh` launcher, `.desktop`, metainfo, icon | Builds ffmpeg (x264, LAME), libplacebo, libmpv from source so MP3 export and the proxy work |
| `run.sh` | Run from a checkout | Checks PySide6/python-mpv/numpy and ffmpeg, then runs `python -m snapper` from `app/` | Quick start without packaging |
| `pyproject.toml` | pip/pipx package | Installs `snapper`, `speech_backend` and `isolation_backend` together | The app looks for the backends next to the package |

### Environment variables (debugging and tests)

| Variable | Effect |
|---|---|
| `SNAPPER_DATA`, `SNAPPER_CACHE` | Move the data and cache folders (tests use temporary ones) |
| `SNAPPER_WX_PYTHON`, `SNAPPER_SEP_PYTHON` | Interpreter to use for WhisperX / audio-separator |
| `SNAPPER_WX_PACKAGES`, `SNAPPER_SEP_PACKAGES` | Override what the installer installs (tests install a tiny package) |
| `SNAPPER_MODELS_DIR` | Where audio-separator keeps its models |
| `SNAPPER_LOCK_DEBUG` | Print what the Wayland pointer lock is doing on stderr |
| `SNAPPER_NO_LOCK`, `SNAPPER_NO_WARP` | Turn the pointer lock / pointer warping off |
| `SNAPPER_HWDEC`, `SNAPPER_AO`, `SNAPPER_MPV_LOG`, `SNAPPER_MPV_LEVEL` | mpv hardware decoding, audio output, extra warnings, log level |
| `SNAPPER_SIZE`, `SNAPPER_KDEGLOBALS` | Window size at start (`1500x950`, for checking layouts), colour scheme file to follow |

Settings (`QSettings("snapper", "snapper")`): `scrub/sound`, `playhead/motion`, `volume`, `isolation/model`, `recent`, and the chosen
interpreter per engine.

---

## Part 2: helping someone who uses Snapper

Be practical and short. Find out the facts first, change nothing until you know the cause.

### Ask first

- How is it installed: Flatpak (`flatpak list | grep Snapper`), `pipx`/`pip`, or a checkout (`run.sh`)?
- Distribution, desktop, session (`echo $XDG_SESSION_TYPE`: wayland or x11), and whether there is an NVIDIA GPU (`nvidia-smi`).
- The exact error text, from a terminal run (the app prints warnings and errors there): `flatpak run io.github.Lewin225.Snapper` or
  `snapper`. For the pointer lock add `--env=SNAPPER_LOCK_DEBUG=1`.

### Where things are

| What | Flatpak | pip / checkout |
|---|---|---|
| Projects (`*.snapper.json`) | `~/.var/app/io.github.Lewin225.Snapper/data/snapper/projects` | `~/.local/share/snapper/projects` |
| Engines Snapper installed itself | `.../data/snapper/engines/whisperx`, `.../engines/separator` (Snapper opens this with *File ▸ Open the folder of installed environments*) | same under `~/.local/share/snapper` |
| Models (audio-separator) | `.../data/snapper/models/audio-separator` | same |
| Caches: proxies, decoded audio | `~/.var/app/io.github.Lewin225.Snapper/cache/snapper` | `~/.cache/snapper` |
| Settings | `~/.var/app/io.github.Lewin225.Snapper/config` | `~/.config/snapper` |

A project holds the clips, tags and transcript. It is safe to copy; caches are safe to delete (they are rebuilt); engines can be removed and
reinstalled. Ask before deleting anything.

### Running a command inside the Flatpak

The Flatpak's Python has no pip and the engine environments' interpreters point into the sandbox, so run them through it:

    flatpak run --command=sh io.github.Lewin225.Snapper -c '~/.var/app/io.github.Lewin225.Snapper/data/snapper/engines/separator/bin/python -m pip install <package>'

Replace `separator` with `whisperx` for the other engine. Check what an engine has: `... bin/python -c "import torch, audio_separator"`.
Paste one command per line when giving commands to run: text pasted after a command becomes part of it.

### Common problems

| Symptom | Cause and fix |
|---|---|
| "Snapper cannot start", libmpv or ffmpeg missing | Install them (the message shows the command for the distribution, for example `sudo dnf install mpv-libs ffmpeg` or `sudo apt install libmpv2 ffmpeg`). The Flatpak bundles both |
| MP3 export says an encoder is missing, or the scrub proxy is never made | ffmpeg lacks `libmp3lame` / `libx264`. Fedora: install ffmpeg from RPM Fusion. Choose WAV meanwhile; the proxy falls back to the original video |
| Engine install fails with "Failed building wheel for diffq" | Old build. Current versions install audio-separator without `diffq` (only Demucs models use it, and Snapper does not) |
| `ModuleNotFoundError: No module named 'audioread'` after the audio-separator install | Old build; install `audioread` into the engine (command above). Current versions include it |
| Install refused: "externally-managed-environment" (PEP 668) | Choose *Install separately, just for Snapper* instead of the system Python, or let it install into `~/.local` when it asks |
| Not enough free disk space | About 12 GB is needed for an install plus models (GPU about 5 GB, CPU about 1 GB; speech model about 3 GB; separation model about 0.7 GB). The installer unpacks on disk next to the engine, not in RAM |
| Transcription or processing very slow | CPU install or no GPU found. A GPU install (NVIDIA CUDA) is many times faster |
| "Use my own installation" is not accepted | The Python must have the packages importable: WhisperX needs `whisperx`, `torch`, `torchaudio`; audio-separator needs `audio_separator`, `torch`, `onnxruntime`. In the Flatpak it must also be in a folder the sandbox can reach |
| Dragging the waveform stops at the screen edge (Wayland) | The pointer lock was not granted or is unavailable. Run with `SNAPPER_LOCK_DEBUG=1` and read the `[pointer lock]` lines (`requested`, `locked`, `given up`, `not available`). It falls back to an ordinary drag. Under X11 the pointer is warped instead |
| Window shows a generic icon | The launcher entry and the window's app id must match (`io.github.Lewin225.Snapper`); outside the Flatpak the bundled icon is used |
| No scrub sound | Needs PulseAudio or PipeWire-pulse (`libpulse-simple`). The *Audio ▸ Scrub sound* setting may be Muted. Check the volume slider and mute |
| Exported files vanished or moved | Auto export keeps the export folder matching the settings by design: it renames and removes files there. Use an empty folder |
| Video not found when reopening a project | The project stores an absolute and a relative path; Snapper asks you to locate the video if both fail (common after moving files or in the Flatpak's document-portal paths) |
| Processed audio missing for a clip | Each clip chooses Original or Processed; exports follow that choice and wait for processing to finish. Deleting the processed audio switches those clips back to the original |

### Things not supported

- Windows and macOS (untested; the scrub sound output, pointer lock, packaging and paths are Linux-specific).
- Demucs models in audio-separator (no `diffq`).
- Anything that cuts clips automatically: by design the user sets every in and out point.

### When you cannot fix it

Say so plainly. Ask the user for the terminal output and the answers above, and point them to the issue tracker at
https://github.com/Lewin225/Snapper/issues (the repository is not public until the owner publishes it). Do not guess at fixes that touch
their projects, their export folder or their Python.
