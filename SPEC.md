# Snapper — Spec (draft)

A generic bulk audio snipper and transcriber. Open one episode, cut dialogue lines by hand with transcript assistance, tag them, and export one self-contained file per clip. Source-engine specifics live in a separate compiler tool that consumes this app's output.

## Background

Replaces a three-tool workflow:

| Old tool | Used for | Why it worked |
|---|---|---|
| Filmora | Watch episode, cut out dialogue gaps, export WAV | Fast GPU-accelerated scrubbing, marking and clipping |
| UVR | Remove music/background from the audio | Worked, but built for music; likely better dialogue models exist |
| FL Studio | Slice vocals into clips, one layer per clip, export all layers as files | Fast slicing; layer names became filenames. Layers were only a workaround |

**Biggest pain point: cutting.** The old flow cut twice (gap removal, then slicing). The new flow cuts once: the same marks are both the gap removal and the clips.

## Scope

- One episode open at a time (multi-episode later).
- Typical episode ~30 minutes, ~60 clips per character, up to ~500 clips per episode. The UI must stay performant at that size.
- Video is a viewing aid only. No video editing or video export.
- Generic enough for non-Source uses.

## Workflow

1. **Open an episode.** Video and audio load. Background jobs start (see below).
2. **Cut by hand.** Scrub, mark in/out, play/stop/resume. The transcript is a navigation map, never an auto-cutter.
3. **Fine-tune** in the detail panel with draggable in/out handles.
4. **Tag** each clip (character plus other configurable tags) and flag problems.
5. **Review.** Toggle between original and isolated audio for any clip.
6. **Export.** One file per clip.

### Background jobs

- **Dialogue isolation** on the episode audio. Cuts are start/end times, so they apply to the isolated audio once it is ready. The user can cut on the original meanwhile.
- **Transcription with timings.** Phoneme, then word, then line (line-level is the worst case accepted). Results appear as they become ready, so lines can be selected before the whole episode finishes.
- **Speaker detection** that pre-populates the character tag as `voice1`, `voice2`, and so on. Parked for now; the user also sets character by hand.

### Processing constraints

- **Memory budget:** background isolation gets about 4 GB of RAM on top of the app's normal use. Whole-file loading is therefore not acceptable.
- **Everything is windowed.** Isolation and transcription work on windows of the episode (for example 30-120 s) and stream results into the app. No tool we reviewed streams natively, so the app owns the windowing. For isolation that means overlapping windows with a crossfade at the seams (not yet built or tested).
- **Backend contract.** Engines sit behind `speech_backend/contract.py` (`SpeechBackend.transcribe(path, start, end)` returning `Line`/`Word`/`Phoneme`, plus `Capabilities`). The app never imports an engine directly, so WhisperX can be swapped.
- **Transcript sources.** WhisperX is the v1 backend. Embedded subtitle tracks are a planned fallback for machines that cannot run models: the words are usually right but TV subtitle timings are not trusted, so they would give line-level text only.

## Layout

```
┌────────┬────────────────────────────┬──────────────────┐
│Trans-  │                            │ Completed clips  │
│cript   │      Video (≈4/5)          │ ▸ play           │
│(≈1/5)  │                            │ ▸ select to edit │
│        ├────────────────────────────┤ filter by tags   │
│        │ Current clip (hsplit)      │                  │
│        │  waveform + in/out handles │                  │
│        │  phonemes / words          │                  │
│        │  tags, flags, settings     │                  │
└────────┴────────────────────────────┴──────────────────┘
        left 2/3                          right 1/3
```

- **Transcript (far left):** scrollable lines. Click a line, word or phoneme to jump to it or select its span. Follows playback.
- **Video:** the largest area.
- **Current clip editor (below video):** zoomed waveform of the selection with in/out handles that are the same handles as the main selection. Dragging either one changes the selection. Words and phonemes are shown, and once ready for the clip, phonemes highlight as it plays.
- **Completed clips (right):** play any clip, or select it to load it back into the editor. Filter by any tag.

## Cutting UX (top priority)

- Keyboard-first: set in, set out and commit a clip without the mouse; the playhead then advances.
- Transport: scrub, mark in/out, play/stop/resume. Stop returns to the last play start so a spot can be replayed while tuning a cut (assumed DAW-style behaviour; confirm).
- Transcript click-to-select for navigation.
- Optional snapping of handles to word/phoneme boundaries (toggleable).
- Scrubbing must feel as fast as Filmora (GPU-accelerated decode).
- Detail waveform is sample-accurate, so waveform data is pre-computed at multiple zoom levels.

## Tags

- Tag types are user-defined. **Character** is the default type; others could be emotion, loudness, and so on.
- Each tag type's dropdown offers the values used so far. Typing a new value adds it.
- Detected speakers pre-populate character as `voice1`, `voice2`, … Renaming a voice renames it across all clips.
- Filter the clip list by any tag, combined.
- v1: one value per tag, set by hand (character may be auto-filled).

## Flags

Problem audio (overlapping speech, background residue after isolation) is marked with a user-added **bool tag** (for example `overlap`, `residue`); there are no built-in flags. What happens to clips with a chosen bool tag set is an export option: skip, export anyway, or separate folder.

Tag types have a kind: **string** (pick or type a value; renamable globally; the first string tag gets the 1-9 quick keys), **int** (spin box, unset allowed) or **bool** (checkbox; absent = off, reset after each saved clip). Older project files with `flags` migrate to bool tags (only flags actually used).

## Export

One self-contained file per clip. User-selectable options:

- Format
- Bitrate
- Convert to mono (on/off)
- Folder layout: all in one folder, or a folder per tag value (for example per character)
- Transcript location: LRC sidecar, embedded in the file, or in the filename
- Handling of clips with a chosen bool tag set (skip / export anyway / separate folder)
- Tags may feed folder layout, filenames and embedded metadata

### Embedding

- Plain transcript goes in the format's native lyrics/comment field where there is one.
- Full timing hierarchy (phoneme/word/line) goes in a custom block for the downstream tool: custom chunk in WAV, custom frame in MP3 ID3, comment/application blocks in FLAC/Ogg.
- LRC can hold line timings (enhanced LRC, word timings) but has no standard place for phonemes.
- Each format's compatibility must be checked before relying on it.

## v2 (deferred)

- Auto-suggested tags beyond character (loudness is measurable; emotion needs a model).
- Multiple values per tag.
- Multiple episodes open or batch processing.

## Decisions and findings so far

Bake-off on a 10-minute section of a real episode (RTX 3080 Ti, container capped at 6 GB RAM). WER is measured against the episode's subtitle words, so it is a rough proxy only (subtitles paraphrase).

- **Transcription backend: WhisperX** (faster-whisper large-v3 plus wav2vec2 alignment), behind the contract.
  - About 10 s per 10 minutes of audio once warm, so roughly 30 s for an episode.
  - At batch size 4 and float16 it peaks at about 4.5 GB RAM and about 6 GB VRAM. Batch 16 does not fit alongside a desktop that uses about 3.9 GB of VRAM.
  - 2-minute windows score the same as one pass, so windowing is safe.
  - Gives word timings. **No phoneme timings** (alignment is character-level). Phonemes need a second aligner (Montreal Forced Aligner was the best open one in FA-Bench) added behind the same contract later.
  - Timing accuracy is unmeasured. The user will judge accuracy once the UI exists.
  - Speaker labels are not wired up (pyannote needs a Hugging Face token). Parked.
- **Isolation helps transcription only slightly** (about 3-5 WER points over the raw mix). Six models (MelBand Roformer, MDX23C, BS-Roformer, Kim Vocal 2, htdemucs_ft, UVR-MDX-NET Voc_FT) are within 2 points of each other, which is not a real ranking. No listening test done, so the isolation model is still undecided and needs a by-ear comparison on clean export quality.
- **Center channel of 5.1 is not a good baseline.** It transcribed worse than the raw stereo mix.
- **Streaming review:** none of the isolation tools stream. They window internally but load the whole file and allocate full-length output buffers; their `chunk_duration` option hard-concatenates without crossfade. Hence the app-owned windowing above.

## Stack decision (spike passed)

**Qt 6 with Python (PySide6), libmpv for video, models in a separate subprocess.** An early prototype (since replaced by `app/`, and removed from the repo) proved the core editor: video, scrubbing, and a fine-adjust waveform with draggable in/out handles. The user judged scrubbing "fast enough".

- **Scrubbing needs a proxy.** Playing the original (1080p 10-bit HEVC) is too coarse: cheap seeks land on keyframes. Generate a 480p all-intra H.264 proxy in the background on open (ffmpeg x264, `-g 1 -crf 34`, audio copied; ~45 s and ~0.5 GB for a 33-minute episode) and cache it. Use the original until it is ready. Video is a viewing aid, so proxy quality does not matter.
- **Latest-wins seeking while dragging.** Keep only the newest target and issue the next seek when the previous finishes. Never queue seeks.
- **Never poll mpv from the UI loop.** Polling properties and repainting the waveform every tick cut scrubbing to about 24 seeks/s. Use property observers and a cached waveform image.
- **Waveform draws only the selection plus a few seconds**, auto-gained (TV dialogue is quiet, about x14 here). Audio is decoded once to a memory-mapped mono file.
- **Hardware decode quirks (this machine, spike):** mpv's zero-copy `nvdec` and 10-bit `nvdec-copy` output both rendered as noise in the Qt GL context (subtitles stayed clean). Software decode and an 8-bit conversion (`vf=format=yuv420p`) are clean. Native Wayland could not create an NVIDIA GL context inside the distrobox, so the spike runs through XWayland. Re-check on the host and for the shipped build.
- **Keyboard focus:** child widgets must not take focus or they swallow the arrow keys.

## Audio playback and the export invariant

- **mpv plays the audio.** The user found it accurate enough for snipping, so there is no custom audio engine.
- **Invariant: what is highlighted on the waveform is exactly what is exported.** Selections are stored as times and converted to sample indices at the export sample rate. Export slices the same decoded PCM the waveform was drawn from, not a separate `ffmpeg -ss` seek on the compressed stream, so the two cannot drift. Handle any container start-time offset once, at decode.
- **Test:** export a clip, then compare it sample-for-sample with the waveform's slice of the same range. Do this for each export format before trusting it.

## Build status

`app/` is the real application skeleton. `app/tests/smoke.py` drives the real window end to end. `spike/` is the earlier throwaway spike.

Working: video with scrub proxy (generated and swapped in the background), waveform editor with word labels and snapping, transcript panel (WhisperX via a subprocess worker, or subtitles from a file or embedded), I/O/Enter cutting with sticky tags and quick keys, tag types and values with filters, global value rename, string/int/bool tag kinds, per-episode project file (`<episode>.snapper.json`), caches in `~/.cache/snapper`.

Not built: MP3 export (next), flagged-clip handling at export, isolation job and the original/isolated toggle, speaker pre-population, phoneme timings, undo, an installer.

## Open research items

1. **Dialogue isolation model.** Pick by ear, then build and test the windowed wrapper (overlap and crossfade) against whole-file output at the seams. Cinematic dialogue models (Bandit v2, MVSEP DnR) were not run.
2. **Phoneme alignment** (second backend behind the contract) and per-clip on-demand alignment.
3. **Speaker detection** quality for pre-populating character tags. Parked.
4. **Embedding format per container**, in coordination with the second tool that reads it.
5. **Source phoneme storage** — only if it ever matters; out of scope for this app.

## Open questions

- Confirm stop/resume behaviour (return to last play start).
- Confirm the "overlap/residue" flag interpretation of question 6.

## Build status addendum (UI features not recorded above)
- **Audio track picker** (combo under the video): selects which audio track is decoded for the waveform/transcription and played by mpv; stored in the project (`audio_track`). Caches per track: `audio_44100_a<N>.s16`.
- **Subtitle survey**: embedded subtitle tracks are listed and labelled; the empty transcript panel offers "Generate using WhisperX" and "Load from video" (dropdown when several subtitle tracks exist); Transcript -> Load subtitles file does the same from a file.
- **Layout**: video and clip editor cannot be collapsed (minimum sizes); transcript and clip library are collapsible (F2/F3, View menu); View -> Reset layout; layout persisted in QSettings.
- **Transport row** (under video): Play/Pause, Stop (returns to last play start), Play From Marker, Set In, Set Out, Deselect clip, preview volume. Play Clip lives in the clip editor.
- **Clip editor**: Play Clip + "Deselect clip (Esc)" left of Start/End; Start/End are drag-to-adjust values (10 ms/px, Ctrl 1 ms, Shift 100 ms, double-click to type); Save to Library (becomes "Done" for saved clips). Deselect never alters a saved clip's timings.
- **Keyboard shortcuts are suppressed while typing** in any text entry.
- **Marking** uses `Player.now()` (direct mpv read), not the event-fed `pos`, which can lag.
- **Known test caveat**: headless GUI tests that depend on live mpv playback timing are flaky when the test window is not the front window; the app itself plays correctly when used.

## Project file and caches
- A project is one JSON file (`<video>-<hash>.snapper.json`) in the app data folder (`$XDG_DATA_HOME/snapper/projects`; under Flatpak that is the app's own data dir, so nothing is written beside the video). It holds the **video path** (absolute plus relative-to-project, so a moved folder still resolves; the user is asked to locate the video otherwise), the **transcript** (lines with word times), the **clip library**, tag types/kinds/values, the **selected clip**, the chosen audio track and whether the **scrub proxy is enabled**. Autosaves 0.8 s after any change and on close. File -> Open project / Save project as.
- Proxies and decoded audio live in the cache folder (`$XDG_CACHE_HOME/snapper`). Proxies are pruned least-recently-used-first once they total more than **2 GB**; the proxy in use is never removed. Opening a proxy marks it as used.
- Tests run with `SNAPPER_DATA` pointing at a temporary folder and never touch real projects.

## Sandboxing (Flatpak)
- All file dialogs are Qt's standard dialogs with the platform theme forced to `xdgdesktopportal`, so they are the system's own dialogs and are the only route to files outside the sandbox. No dialog uses `DontUseNativeDialog`.
- Videos chosen through the portal arrive as document-portal paths (`/run/user/<uid>/doc/<id>/<name>`). The project stores that path plus a path relative to the project; if neither resolves, the user is asked to locate the video again.
- Projects, caches (proxies, decoded audio) and logs stay in the app's own data/cache folders, which need no extra permissions. Exports will be written through a portal "choose folder" dialog.

## Theme
The app follows the system theme. With a real platform theme (the KDE Flatpak runtime) Qt styles everything and the app forces nothing. Otherwise the palette is built from the user's KDE colour scheme (`kdeglobals`, which a Flatpak needs `--filesystem=xdg-config/kdeglobals:ro` to read), falling back to Qt's light/dark palette, and it updates live when either changes. Colours in custom widgets, including the waveform (background, wave, words, selection), come from the palette; the video area stays black. `SNAPPER_KDEGLOBALS` overrides the file's path (dev container).

## Export (WAV first)
- **Project-level settings**, stored in the project file, edited in a pop-up ("Export Settings…" under the library); **Export** (the primary button, also in the Export menu) is enabled only once the project has settings and clips. The **export folder is part of the settings** (picked with the system folder dialog, required and must be writable), so Export never asks.
- **Settings:** file-name template (`{id}`, `{n}`, `{start}` in ms, `{text}`, and any tag name as `{tag}`; no path separators); format (WAV now, MP3 next); mono/stereo; sample rate; format options (WAV bit depth 16/24/32-float; MP3 will add bitrate/quality); **folders by tag**: an ordered list of tags (first = top folder, then sub-folders; clips with no value go in `_none`; bool tags give Yes/No); which **text field** the clip text is written to (WAV LIST/INFO: Comment ICMT, Title INAM or Subject ISBJ, or none); whether to **add the clip's tags to the file** (JSON in a custom `snpr` chunk).
- **Sample accuracy:** a clip's start/end times become sample indices `round(t * rate)` and exactly those samples are written. The waveform audio and every export are decoded with the same ffmpeg arguments (`media.pcm_args`: same track, the track's start offset padded as silence, a fixed downmix scale so 16/24/32-bit decodes have the same loudness), so sample N is the same moment everywhere. A mono 16-bit 44.1 kHz export slices the waveform's own cache file; other formats decode a temporary file (removed after the export). Tested sample-for-sample against the waveform, and stereo/24-bit/float decodes tested for zero-lag alignment and equal level.
- **Safe names:** tag names and values cannot contain `\ / : * ? " < > |` or control characters (the tag boxes refuse them, rename and add-tag dialogs reject them, loaded values are cleaned); every generated file/folder name is also cleaned (reserved device names, trailing dots/spaces, `..`), clashes get `_2`, `_3` (compared case-insensitively), and no path can leave the export folder. Tag names `id`, `n`, `start`, `text` are reserved for the template.
- Existing files with the same name in the destination are overwritten.

### Export runs in the background, per clip
- **Export** queues every clip that is *new, changed or failed* and returns at once; "Re-export all clips" (Export menu) forces everything. More can be queued while it runs. One background thread writes clips one at a time; stereo/24-bit/float audio is decoded first as a background job (shown as "Preparing audio"), once per setting combination, and the temporary decode is deleted when the project window closes (leftovers older than a day are purged at start-up).
- The **library has an Export column** per clip: blank (never exported), `⋯ Queued`, `◐ Exporting` (animated), `✓ Exported`, `● Changed` (the clip, its tags/text or the export settings changed since it was exported) and `✗ Failed` (tooltip says why). The state is derived from a signature of everything that decides the file (times, text/tags where used, all settings incl. folder, audio track) stored with the clip, so it survives restarts; at load, clips whose file was deleted show as not exported.
- A clip's file name uses `{n}` = the clip's number (its id), not its position, so names stay put as clips are added or removed; clashes are resolved in clip-number order. When a re-export lands somewhere else (tags or name changed) the old file is deleted, plus folders that became empty, never above the export folder.
- This is the machinery an **auto-export** (export a clip as soon as it is created or changed) will use: `ExportManager.mark_queued` / `submit` for any list of clips.

### Library buttons, auto export, pane titles
- The library's buttons (Play, Delete, Export Settings…, Export) share one row; above it, the clip count and an **Auto export** tick (stored in the project as `auto_export`). With it on, any saved clip that is new or changed is exported by itself about 0.7 s after the last edit (so dragging handles does not export every step); changing the export settings re-exports everything affected; ticking it exports whatever is outstanding. It needs working export settings (folder). A clip that failed is not retried until it is edited (a manual Export does retry). Clips deleted from the library leave their files alone. Opening a project does not export anything by itself.
- Each pane has a bold title: **Transcript, Playback, Library, Clip Editor** (`titles.section_title`). The Clip Editor's title also carries the clip status ("Clip Editor — New clip / Editing a saved clip / No selection").

### MP3 export and the library's right-click menu
- **MP3** is encoded with ffmpeg's LAME encoder from the same 16-bit sample-accurate slices as WAV (bit depth does not apply; the dialog shows a Quality row instead): constant 128–320 kbps or variable V0/V2/V4. Mono/stereo and 22.05/44.1/48 kHz as for WAV. The file is encoded to a temporary file and renamed, so the Xing/LAME header (gapless delay information) is written. The clip text goes to an ID3v2.3 frame chosen in the dialog (Comment COMM, Title TIT2, Subtitle TIT3) and the clip's tags go as JSON in a custom `snpr` text frame (TXXX). Changing the format re-exports every clip (and removes the old files).
- **Right-click a library row:** Duplicate (same range, text and tags, placed after the original and opened for editing; with auto export on it exports by itself), Delete, Open containing folder (file manager with the file selected via org.freedesktop.FileManager1, else the plain folder) and Open in system app (default application for the file). The two Open entries are disabled until the clip has been exported and its file exists. Both go through Qt/D-Bus so they work through the desktop portal in a Flatpak.

### Changing where exported files go, and deleting clips
- **Asked every time, never remembered.** (Superseded: an earlier version asked once per session.) The answer is kept only for those clips until they have been exported again, so the export that follows the settings dialog does not ask a second time.
- **Deleting a clip** (right-click Delete or the Delete button) that has an exported file asks: *Delete clip and exported file* / *Delete clip only* / *Cancel*. A clip that was never exported is deleted without asking.
- *Any* change that would put a clip's file somewhere else counts: another export folder, a different file-name template or tag-folder layout, another format, or editing a clip's tags/text so its name or folder changes. The check runs when the settings dialog is confirmed and again each time clips are queued for export, comparing each clip's earlier file with the path it would get now.
- Changing the export folder in Export Settings makes every clip "Changed", so they are re-exported into the new folder (by Export, or by themselves with Auto export). If files exported earlier still exist in the old folder, a dialog asks whether to delete them.
- If Yes: each old file is deleted only after its replacement has been written, and only files Snapper itself exported (the path stored with the clip) are touched; folders left empty inside the old folder are removed, the old folder itself and any other files stay. If No: the old files are never deleted.

### Test video and tests
- The default test video is *Tears of Steel* (Blender Foundation, CC BY 3.0, 12 min, lots of dialogue), downloaded on demand by `app/tests/fetch_media.sh` (checked against a SHA-256, not stored in git) with a WhisperX subtitle track (`tears_of_steel.srt`, 80 lines) embedded. The earlier OVERGROWN teaser was dropped: its licence is not stated. `two_audio.mkv` is a synthetic two-track file.
- `app/tests/run_all.sh` runs every test against it (no arguments needed; a `.mp4`/`.mkv` or `.png` argument is recognised by its extension). Tests that use clip times use the first 80 seconds of the video.

### Flatpak
- `flatpak/` builds the app on the **KDE 6.11 runtime** with `io.qt.PySide.BaseApp` (PySide6, Python 3.13, numpy). ffmpeg 9 (x264, LAME, NVDEC headers), libplacebo, libmpv and python-mpv are built from source in the manifest. Real **Breeze** style is used when Qt has it (the dev container only has Fusion + the colours from kdeglobals, which is kept as the fallback); the KDE colour scheme is read from the host's `kdeglobals` that the base app shares read-only.
- **Sandbox:** no filesystem access at all; file dialogs are the portal's (verified: `FileChooser.OpenFile` is called). Native Wayland with X11 fallback, `--device=dri`, PulseAudio socket, `org.freedesktop.FileManager1` for "Open containing folder". Hardware decoding via the host NVIDIA GL extension (`auto-copy`); the scrub proxy plays in software, as before.
- **Start-up behaviour:** no file -> start screen listing recent projects (New Project (Open Video)…, Open project…); a project file opens directly; a video asks to resume its project (Resume / Start fresh, which keeps the old file as `*.bak`). File > Open recent mirrors the list.
- **Known limits:** videos and the export folder come through the document portal, so their paths are `/run/user/<uid>/doc/...` (stable while the app keeps the permission; a moved or forgotten video is re-located through the dialog); WhisperX is not packaged: it is set up on first use (next section). The manifest therefore has `--share=network`.

### WhisperX engine set-up (on first use)
- WhisperX (needs PyTorch, several GB) lives in its own Python environment (`engine.py`). It is only looked for when **Generate using WhisperX** is pressed, so subtitles from the video or an .srt work without it.
- Lookup order: the interpreter the user chose (QSettings `engine/python`), `SNAPPER_WX_PYTHON`, the developer's `~/envs/wx`, then the one Snapper installs under `<data>/engines/whisperx`. The probe lists Python, whisperx, torch and torchaudio with their versions (and whether PyTorch sees a GPU).
- If something is missing a dialog lists exactly what (Python / WhisperX / PyTorch / torchaudio, ✓ or ✗) and offers **Install separately, just for Snapper** (venv + pip, pinned whisperx 3.8.6 / torch 2.8.0 / torchaudio 2.8.0, about 5 GB, needs 12 GB free, cleaned up completely on failure or cancel) or **Use my own installation…** (pick a Python; accepted only if complete), or Not now.
- The backend now falls back to the CPU (int8) when PyTorch can't see a GPU. Inside the Flatpak only the Snapper-installed or a reachable user installation can be used.
- Test overrides: `SNAPPER_ENGINE_PACKAGES`, `SNAPPER_ENGINE_REQUIRED`. Tests: `engine_test.py`.

### Distribution decision
- Snapper ships as a Flatpak bundle attached to **GitHub releases**, not through a store (no Flathub review). So the run-time WhisperX installer (with `--share=network`) stays as it is; a separate engine package is only worth revisiting if that changes. No Flathub packages exist for WhisperX, PyTorch, faster-whisper or CTranslate2 (checked); aTrain's Flathub manifest is a reference if we ever bundle one.

### Optional tools: audio-separator and vocal isolation
- **Optional engines** (`engine.py`): WhisperX and audio-separator each live in their own Python environment and are only looked for when used. Search order: the user's chosen interpreter, `SNAPPER_WX_PYTHON` / `SNAPPER_SEP_PYTHON`, the developer's `~/envs/wx` / `~/envs/sep`, Snapper's private environment (`<data>/engines/<name>`), then the system Python (not inside a Flatpak). If something is missing the dialog lists each package (✓/✗ with versions, GPU visible or not) and offers: **Install separately, just for Snapper** (private venv), **Install into my system Python** (`pip install --user`; a distribution-managed Python is refused with an explanation and, on a yes, retried with `--break-system-packages`, still into `~/.local` only) or **Use my own installation…**, with a **GPU / CPU** choice (GPU preselected when an NVIDIA GPU is present; CPU installs use PyTorch's CPU wheels and are much smaller).
- **Isolate vocals using audio-separator** (Audio menu). Pinned `audio-separator==0.47.1` (`[gpu]` or `[cpu]`). The app decodes the track to stereo 44.1 kHz PCM, the worker (`isolation_backend/isolate_worker.py`, run in the engine's Python) memory-maps it and separates 45 s windows with 5 s overlap, crossfading the overlaps (audio-separator's own chunking does not crossfade), with `normalization_threshold=1.0` so every window keeps the original level; progress per window; peak RAM is a window, not the episode. Default model BS-Roformer (`model_bs_roformer_ep_317_sdr_12.9755.ckpt`), changeable under **Isolation model…**; models are cached in `<data>/models/audio-separator` (`SNAPPER_MODELS_DIR` overrides). Measured on the RTX 3080 Ti: about 2× real time. Cancelling keeps any earlier isolated audio.
- **The isolated audio is a second version of the track**: a 16-bit stereo 44.1 kHz WAV, sample N = the same moment as the original (`media.isolated_pcm_path`). The waveform, playback and every export are derived from it exactly as for the original (export invariant unchanged). mpv gets it as an extra audio track after the video's own; the clip editor's **Original | Isolated** switch (and the **V** key) is per clip (`Clip.source`, saved in the project; new clips inherit the last choice). A clip whose isolated audio is gone plays/exports the original (export refuses it with a clear message). Switching a clip's source marks it Changed for export.
- **Load custom audio replacement…** (Audio menu) uses any audio file (another model, a stem from a mixing tool) in place of the isolated audio: placed at time 0, converted to 16-bit stereo 44.1 kHz and padded with silence or cut to exactly the episode's length, with a warning if the lengths differ by more than a second. **Remove isolated audio** deletes it and puts its clips back on Original.
- Not yet: using the isolated audio for transcription, and isolating only part of an episode.
- **Waveform:** it has no background of its own (the window shows through). The original audio is always drawn; the isolated audio is drawn over it in a second colour (the theme's link colour, orange if that is too close to the highlight) on the same vertical scale, so what was removed is visible. The original steps back (lighter) while the overlay is shown. The overlay is shown for a clip whose source is Isolated and while an isolation is running, when it **fills in window by window**: the worker flushes each finished window to its `.tmp` output and reports `upto` seconds; the app reads that part of the file and updates a rough mono waveform (the exact one is rebuilt from the finished file). Using the isolated audio for playback/export of a clip before the whole job has finished is not done yet.
- **Early use of the isolated audio:** it can be used as soon as a stretch of it is finished. The worker preallocates its output at full length and writes windows in place; once the first window is done, the player adds that (growing) file as the extra audio track and the Original | Isolated switch is enabled. For a clip set to Isolated, playback uses the isolated audio while the playhead is inside the finished part and **returns to the original within a second of its end**, switching back when the playhead is inside it again (the switch shows what is playing; the clip's saved choice does not change). The waveform overlay and a tooltip ("Isolated so far up to m:ss") say how far it has got. Exporting a clip that needs isolated audio waits until the isolation has finished (it is skipped with a message rather than failed, and auto export picks it up when the job ends). Closing the window, cancelling or a failure stops the worker and removes the partial file.
