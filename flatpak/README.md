# Snapper Flatpak

Builds Snapper on the **KDE 6.11 runtime** (real Breeze, portals) with the **PySide6 base app**.

    flatpak install --user flathub org.kde.Platform//6.11 org.kde.Sdk//6.11 io.qt.PySide.BaseApp//6.11
    cd flatpak
    flatpak-builder --user --install --force-clean --ccache build-dir local.snapper.Snapper.yml
    flatpak run local.snapper.Snapper                 # start screen with recent projects
    flatpak run local.snapper.Snapper path/to/video   # asks to resume if the video has a project

What is built from source: ffmpeg 9.0.1 (x264, LAME, NVDEC headers), libplacebo, libmpv, python-mpv, and the app itself.
The first build takes a while (ffmpeg); later builds only redo what changed.

## Sandbox
- No filesystem permissions. Videos, projects and the export folder are chosen with the **file-chooser portal**; the app
  stores/reads its own data in `~/.var/app/local.snapper.Snapper/{data,cache,config}`.
- GPU through `--device=dri`; hardware decoding uses the host's NVIDIA GL extension (`auto-copy`, set in `snapper.sh`).
- `org.freedesktop.FileManager1` is reachable, for "Open containing folder".
- **Not included yet: the WhisperX engine** (see SPEC.md, "Flatpak"). "Generate using WhisperX" reports that the engine is
  missing; subtitles from the video or an .srt file work.
- The app id `local.snapper.Snapper` is a placeholder.
