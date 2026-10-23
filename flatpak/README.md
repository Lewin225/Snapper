# Snapper Flatpak

Builds Snapper on the **KDE 6.11 runtime** (real Breeze, portals) with the **PySide6 base app**.

    flatpak install --user flathub org.kde.Platform//6.11 org.kde.Sdk//6.11 io.qt.PySide.BaseApp//6.11
    cd flatpak
    flatpak-builder --user --install --force-clean --ccache build-dir io.github.Lewin225.Snapper.yml
    flatpak run io.github.Lewin225.Snapper                 # start screen with recent projects
    flatpak run io.github.Lewin225.Snapper path/to/video   # asks to resume if the video has a project

What is built from source: ffmpeg 9.0.1 (x264, LAME, NVDEC headers), libplacebo, libmpv, python-mpv, and the app itself.
The first build takes a while (ffmpeg); later builds only redo what changed.

## Sandbox
- No filesystem permissions. Videos, projects and the export folder are chosen with the **file-chooser portal**; the app
  stores/reads its own data in `~/.var/app/io.github.Lewin225.Snapper/{data,cache,config}`.
- GPU through `--device=dri`; hardware decoding uses the host's NVIDIA GL extension (`auto-copy`, set in `snapper.sh`).
- `org.freedesktop.FileManager1` is reachable, for "Open containing folder".
- **Optional engines (WhisperX, audio-separator) are not included**: the first use offers to install them for Snapper (network access is allowed for that, see SPEC.md, "Flatpak").
- App id: `io.github.Lewin225.Snapper` (matches the GitHub account; change all four files if the repo moves).
