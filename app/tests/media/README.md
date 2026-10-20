# Test media

- `overgrown.mp4` — *OVERGROWN – Blender Feature Film (Teaser)*, 81 s, H.264 2578×1080, AAC stereo. Licence: CC BY 4.0
  (as stated when it was added; please keep the attribution to its creators when redistributing). The video and audio are
  untouched; one subtitle track (`mov_text`, language `eng`, title "WhisperX (test fixture)") was generated once with
  WhisperX and embedded with `ffmpeg -c copy`, so the tests have subtitles to load from the video (13 lines, e.g.
  "I've had smaller." at 27.45–29.73 s).
- `two_audio.mkv` — an 8 s synthetic file with two audio tracks (pink noise, then a 440 Hz tone) for the audio-track
  tests. Generated with ffmpeg's `testsrc`, `anoisesrc` and `sine` sources.

Run everything with `app/tests/run_all.sh`.
