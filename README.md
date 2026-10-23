# Snapper

A bulk audio snipper and transcriber for TV episodes. Open an episode, cut each spoken line by hand while a transcript
guides you, tag the lines (character, and any tags you define), and export one self-contained audio file per line with its
transcript. Made for building voice sets for game mods (Source engine and the like), but it stays generic.

- **Fast manual cutting:** scrub, set in/out, play-stop-resume; click a transcript line to jump to it. Nothing is ever cut automatically.
- **Transcripts:** use the video's subtitles, load an `.srt`, or generate one with [WhisperX](https://github.com/m-bain/whisperX) (installed on first use, see below).
- **Library:** tag, filter, duplicate and delete clips; clips are saved with the project.
- **Export:** WAV (16/24/32-bit) or MP3, mono or stereo, your own folder layout and file names (`{character}_{text}`), transcript as embedded tag / LRC / file name, optional auto export.
- Follows your desktop theme (Breeze on KDE) and uses the system file dialogs.

See [SPEC.md](SPEC.md) for the design decisions and what's planned (background dialogue isolation, phoneme timings, speaker suggestions).

## Running it

Flatpak (from a release bundle):

    flatpak install --user Snapper.flatpak
    flatpak run io.github.Lewin225.Snapper

From source (Linux; other platforms are not tested):

    pip install -r app/requirements.txt     # PySide6, python-mpv, numpy; also needs libmpv and ffmpeg installed
    ./run.sh [video-or-project]

With no argument Snapper shows a start screen with your recent projects. Opening a video asks whether to resume its
project, if one exists; opening a project file opens it.

### Transcribing with WhisperX
The first time you press *Generate using WhisperX*, Snapper checks for WhisperX, PyTorch and torchaudio and says what is
missing. *Install separately, just for Snapper* creates a private environment in the app's data folder (about 5 GB, needs
network access); *Use my own installation…* lets you point at an existing Python. A GPU is strongly recommended. Loading
subtitles from the video or an `.srt` file needs none of this.

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
