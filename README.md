# Snapper

A bulk audio snipper and transcriber for TV episodes. Open an episode, cut each spoken line by hand while a transcript
guides you, tag the lines (character, and any tags you define), and export one self-contained audio file per line with its
transcript. Made for building voice sets for game mods (Source engine and the like), but it stays generic.

- **Fast manual cutting:** scrub, set in/out, play-stop-resume; click a transcript line to jump to it; drag the waveform to scrub with tape-style sound (or pan, with a clip selected) and hold the right button then drag to select a clip. Nothing is ever cut automatically.
- **Transcripts:** use the video's subtitles, load an `.srt`, or generate one with [WhisperX](https://github.com/m-bain/whisperX) (installed on first use, see below).
- **Library:** tag, filter, duplicate and delete clips; clips are saved with the project.
- **Export:** WAV (16/24/32-bit) or MP3, mono or stereo, your own folder layout and file names (`{character}_{text}`), transcript as embedded tag / LRC / file name, optional auto export.
- Follows your desktop theme (Breeze on KDE) and uses the system file dialogs.

See [SPEC.md](SPEC.md) for the design decisions and what's planned (background dialogue isolation, phoneme timings, speaker suggestions).

## Running it

Flatpak (from a release bundle):

    flatpak install --user Snapper.flatpak
    flatpak run io.github.Lewin225.Snapper

Without Flatpak, with pip or pipx (Linux; other platforms are not tested). Snapper uses your system's **libmpv** and **ffmpeg**
(with the `libx264` and `libmp3lame` encoders, for the scrub proxy and MP3 export; stock Fedora ffmpeg lacks them, install
ffmpeg from [RPM Fusion](https://rpmfusion.org)). Install those first, for example:

    sudo dnf install mpv-libs ffmpeg        # Fedora        (Debian/Ubuntu: sudo apt install libmpv2 ffmpeg)
    pipx install https://github.com/Lewin225/Snapper/releases/download/v1.0.0/snapper-1.0.0-py3-none-any.whl
    snapper [video-or-project]

If libmpv or ffmpeg is missing, Snapper says so at start and shows the command for your distribution. A missing encoder is
reported only when you use the feature that needs it (the scrub proxy falls back to the original video; MP3 export asks you to
pick WAV or fix ffmpeg).

From a checkout:

    pip install -r app/requirements.txt     # PySide6, python-mpv, numpy
    ./run.sh [video-or-project]

With no argument Snapper shows a start screen with your recent projects. Opening a video asks whether to resume its
project, if one exists; opening a project file opens it.

### Optional tools: WhisperX and audio-separator
Transcribing and vocal isolation use big Python packages (PyTorch and friends), so they are not part of Snapper. The first
time you use *Generate using WhisperX* (Transcript menu) or *Generate processed audio using audio-separator* (Audio menu), Snapper checks
what is missing and offers to install it for a **GPU or a CPU**: *just for Snapper* (a private environment in the app's data
folder), into your *system Python*, or you can point it at an installation you already have. A GPU is strongly recommended
(about 5 GB download); everything else works without either tool. Loading subtitles from the video or an `.srt` file needs
nothing extra.

**Processed audio:** *Audio → Generate processed audio using audio-separator* removes the music and effects, leaving the
dialogue. It runs in the background and can be used as soon as the first part is done (playback returns to the original beyond
the finished part). The processed audio sits beside the original: pick *Original* or *Processed* per clip in the clip editor
(or press `V`); the waveform, what you hear and what gets exported all follow that choice. *Audio → Import custom processed
audio…* lets you use an audio file made with another model or tool instead (it is placed at the start of the episode and
padded or cut to its length). *Transcript → Generate using WhisperX → From processed audio* often hears the words better.

## Tests

    app/tests/run_all.sh        # fetches the test video on first use

The tests drive the real app with a Qt window and mpv; they need a display (or `QT_QPA_PLATFORM=offscreen` for some) and a
GPU is optional. See `app/tests/media/README.md` for the test media and its credits.

## Licence

Snapper is licensed under the **GNU Affero General Public License, version 3 or later** (see [LICENSE](LICENSE)).

Third-party software it uses or ships:

| | Licence |
|---|---|
| Qt 6 / PySide6 | LGPL-3.0 (or GPL) |
| python-mpv | GPL-2.0+ or LGPL-2.1+ |
| libmpv, libplacebo, libass | GPL-2.0+ / LGPL-2.1+ (the Flatpak's mpv is GPL) |
| FFmpeg (separate program; the Flatpak build is GPL, with x264) and LAME | GPL-2.0+ / LGPL |
| numpy | BSD-3-Clause |
| WhisperX, PyTorch, torchaudio, faster-whisper, CTranslate2, transformers | BSD / MIT / Apache-2.0 (installed separately, not bundled) |

The Flatpak manifest in `flatpak/` lists the exact source of everything it builds. The speech models WhisperX downloads
have their own licences.

Test video: *Tears of Steel* © Blender Foundation | mango.blender.org, CC BY 3.0 (downloaded when you run the tests, never bundled).
