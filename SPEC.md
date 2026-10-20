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

**Qt 6 with Python (PySide6), libmpv for video, models in a separate subprocess.** `spike/` proves the core editor: video, scrubbing, and a fine-adjust waveform with draggable in/out handles. The user judged scrubbing "fast enough".

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

Not built: export (next), isolation job and the original/isolated toggle, speaker pre-population, phoneme timings, undo, an installer.

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
