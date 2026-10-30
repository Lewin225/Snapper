# macOS version: plan

Status: **plan, nothing implemented.** Snapper is Linux only today (see `AGENTS.md`). This lists what has to change for an Apple Silicon Mac,
in the order to do it, and what is still unknown until it is tried on a Mac. Findings go back into this file as they are made.

## Decisions

- **Apple Silicon (arm64) only.** No Intel build, so no universal2 binaries.
- **Unsigned, no notarisation.** Distributed as a `.dmg` on the GitHub release, opened by dragging `Snapper.app` onto the Applications
  folder shortcut in the disk image. Like the Flatpak bundle, there is no store.
- **Selecting on the waveform without a right button** (a trackpad has none, and Ctrl-click is a right click on a Mac): either hold the
  Option key while dragging, or press the left button, hold still for a set time, then drag. See "Waveform gestures".
- The Linux behaviour does not change. Every fix below is behind a platform check or is safe on both.

## What assumes Linux today

| Area | Today | On macOS | Size |
|---|---|---|---|
| Video drawing (`player.py`, `VideoWidget.initializeGL`) | `libEGL.so.1` and `eglGetProcAddress` give mpv its OpenGL entry points | Use the Qt context's own `getProcAddress` on macOS. Apple's OpenGL is deprecated but still present; check that mpv's render API and `QOpenGLWidget` work together there | small |
| Scrub sound (`tape_scrub.py`) | `libpulse-simple` through ctypes; `available()` is false without it | A second output backend for the same sample stream. `sounddevice` (PortAudio, which its wheels bundle) is the least work; CoreAudio through ctypes is the alternative. Qt Multimedia segfaulted when listing devices on Linux, so it is not trusted until tried | medium |
| Endless drag (`drag.py`) | Wayland pointer lock, else X11 pointer warp, else an ordinary drag | The warp path should work through `QCursor.setPos`. The tests must keep `SNAPPER_NO_WARP=1` | small |
| Data and cache folders (`media.py`) | `XDG_DATA_HOME` and `XDG_CACHE_HOME` | `~/Library/Application Support/snapper` and `~/Library/Caches/snapper` (`QStandardPaths` gives both). The environment overrides stay | small |
| Open file, show in folder (`desktop.py`) | D-Bus FileManager1, document-portal paths | `QDesktopServices` for open; `open -R <file>` for show-in-folder. The portal code is skipped | small |
| Theme and start-up (`theme.py`, `__main__.py`) | kdeglobals palette; forces the `xdgdesktopportal` platform theme | Neither: Qt's macOS style follows the system. The menu bar moves into the system bar (Qt does it) so the menu texts need the Quit and Preferences roles checked | small |
| Missing libmpv or ffmpeg message (`system_check.py`) | dnf, apt, pacman, zypper commands | In the bundled app both are inside it, so the message is only for a source checkout (`brew install mpv ffmpeg`) | small |
| Hardware decoding (`main_window.py`) | `auto-safe` (NVDEC fallbacks seen on one machine) | `auto-safe` should pick VideoToolbox; confirm the picture is right, since the Linux notes record 10-bit output rendering as noise | check |
| Scrub proxy (`media.py`) | `libx264` encode | Keep `libx264` if the bundled ffmpeg has it; `h264_videotoolbox` is the fast alternative | check |
| Engines (`engine.py`, `engine_dialog.py`, `speech_backend/`, `isolation_backend/`) | NVIDIA CUDA or CPU choice, a private venv made with the app's Python | See "Engines" | large |
| Shortcuts | `Ctrl+…` | Qt maps `Ctrl` to Cmd for `QKeySequence`; check the ones that use raw key events (`KeyFilter`) and the mouse modifiers | small |
| Tests (`app/tests/`) | `run_all.sh` assumes X11 and the Flatpak's Python | Run from a local virtual environment; skip `drag_lock_test` (Wayland) and the Flatpak-only checks by platform | medium |

## Waveform gestures

Left-drag scrubs the playhead (no clip selected) or pans (a clip selected); right-drag selects; the wheel zooms. For a Mac:

- **Option + left-drag selects.** Simple and discoverable; shown in the waveform's tooltip.
- **Press and hold, then drag, selects.** Press the left button and keep the pointer within a few pixels for a set time (start at 400 ms,
  to be tuned by trying it); the cursor changes to the selecting one when the time is up, then dragging selects. A press that moves before
  the time is up is the usual scrub or pan. The time is a constant in one place so it can be changed (and later offered as a setting).
- Both can be switched on for Linux as well, because the same need exists on any laptop without a right button; that is a separate
  decision.
- Trackpad scrolling reports pixel deltas as well as angle deltas, so the wheel zoom has to be checked with two-finger scrolling.

## Engines

- **Python for the environments.** The Flatpak provides a Python for the private venv. A bundled `.app` has none that can make venvs, so
  the app carries `uv` (one small binary), which makes each engine's environment with a managed Python. The "install separately for
  Snapper" choice stays; "use the system Python" is dropped on macOS (the system Python is Apple's and is not for this).
- **No NVIDIA choice.** `has_nvidia()` is false on a Mac, so the dialog offers one install ("Apple Silicon") with PyTorch's default macOS
  wheels (they include the Metal backend, MPS). The download sizes in the dialog need new numbers.
- **WhisperX.** CTranslate2 publishes arm64 macOS wheels, so the install works. A wheel for the platform is not the same as GPU use:
  as far as I know CTranslate2 uses the CPU on a Mac (the backend already picks `cpu` and `int8` when CUDA is absent). To measure on the
  Mac: how long a 10-minute window takes. If it is too slow, a second backend behind the existing `SpeechBackend` contract (an MLX
  Whisper) is the way out, but that is a separate piece of work.
- **audio-separator.** Check whether it uses MPS or ONNX Runtime's CoreML provider on Apple Silicon, whether the three models in
  `isolation.py` run on it, and whether the output is still aligned sample for sample (an invariant).
- `isolate_worker.py` and `transcribe_worker.py` read and write raw PCM and need no change for alignment.

## Packaging

- **Build:** PyInstaller (or py2app) makes `Snapper.app` with the Python code, PySide6, `python-mpv`, NumPy, `speech_backend/` and
  `isolation_backend/` next to the package (the app looks for them there), `uv`, and the libraries below.
- **libmpv and ffmpeg** go inside the bundle, with their dependent libraries copied in and their install names rewritten
  (`dylibbundler` or `delocate`). ffmpeg and ffprobe are built with LAME (MP3 export) and x264 or use VideoToolbox (proxy), as the
  Flatpak does for the same reasons. The same licence notes apply as for the Flatpak build.
- **Signing:** Apple Silicon refuses unsigned code, so every Mach-O file is ad-hoc signed (`codesign --force --sign -`) after the
  libraries are rewritten, and the bundle as a whole last. There is no developer identity and no notarisation.
- **First start for a user:** a downloaded unsigned app is blocked by Gatekeeper. The README says what to do: on current macOS, open
  System Settings ▸ Privacy & Security and choose Open Anyway after the first refusal, or run
  `xattr -dr com.apple.quarantine /Applications/Snapper.app`. The exact steps differ between macOS versions, so they are written down
  after trying them on the Mac.
- **Disk image:** `Snapper.dmg` with `Snapper.app` and a shortcut to `/Applications`, so installing is a drag.
- **CI:** a macOS job in `.github/workflows/release.yml` on a hosted Apple Silicon runner builds the `.dmg` on a `v*` tag and attaches
  it to the same draft release. The Linux workflow has not run yet either; both will need adjusting on their first run. The OSV audit in
  `security.yml` already reads the engines' requirements and does not need changes for the Mac, but the engine pins may differ there.
- **Version and metadata:** `CFBundleIdentifier` `io.github.Lewin225.Snapper` (the same id as the Flatpak), the icon as `.icns`
  (made from `snapper.svg`), a minimum macOS version once it is known which one the bundled libraries need.

## Order of work

1. **Spike on the Mac, no code changes.** Install `mpv` and `ffmpeg` with Homebrew, make a virtual environment with `PySide6`,
   `python-mpv` and `numpy`, run `./run.sh` with a short video, and record what fails or looks wrong. Also try the engines by hand
   (`pip install` into a venv, then the two worker scripts) to learn the speeds and whether MPS or CoreML are used. The results replace
   the "check" and "unknown" entries here.
2. **Portability fixes** (the small rows above), each tested on Linux first, with stand-ins where a platform check can be faked.
3. **Scrub sound backend** chosen from what the spike shows.
4. **Waveform gestures** (Option-drag and press-and-hold), tried on the Mac's trackpad.
5. **Engines:** `uv`, the Apple Silicon install, new download notes, measured speeds in the README.
6. **Packaging and CI:** the `.app`, the `.dmg`, the workflow job, the README's first-start steps.
7. **Tests:** platform guards in `run_all.sh`, the Mac-only checks (data folders, `open -R`, the bundle starts and plays a video).

## Unknown until tried

- Whether mpv's OpenGL render API works inside a `QOpenGLWidget` on the Mac's current macOS, and with which `hwdec`.
- Whether libmpv from Homebrew can be bundled without breaking (many dependent libraries) or has to be built.
- Pointer warping during a drag on current macOS (it may need no permission, but this is not confirmed).
- How the Gatekeeper steps read on the Mac's macOS version, and whether the app opens at all once quarantined.
- Speed of WhisperX on the CPU of the Mac, and whether audio-separator runs on the GPU.
- Which minimum macOS version the bundle ends up needing.
