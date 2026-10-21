# Test media

- `tears_of_steel.mp4` — **not stored in the repository**; `app/tests/fetch_media.sh` downloads it (and `run_all.sh` runs the
  script when it is missing). It is *Tears of Steel* (12 min 14 s, 480p H.264 1152×480, AAC stereo), a live-action sci-fi
  short with plenty of English dialogue.
  - **Licence:** Creative Commons Attribution 3.0. "(CC) Blender Foundation | mango.blender.org". The film and its raw
    material were released under CC BY 3.0 as stated on its page: https://video.blender.org/videos/watch/8533ea43-4271-4a57-9694-e9d0b35e1aa1
    and https://mango.blender.org. Video and audio are untouched.
  - The download is checked against a SHA-256 (the script refuses a file that doesn't match). One subtitle track
    (`mov_text`, language `eng`, title "WhisperX (test fixture)") is added with `ffmpeg -c copy` from
    `tears_of_steel.srt`, which WhisperX generated once from the film's audio (80 lines, e.g. "You have your robotics, and I
    just want to be awesome in space." at 27.37–30.07 s). The tests load it as the video's embedded subtitles.
- `two_audio.mkv` — an 8 s synthetic file with two audio tracks (pink noise, then a 440 Hz tone) for the audio-track
  tests. Generated with ffmpeg's `testsrc`, `anoisesrc` and `sine` sources.

Run everything with `app/tests/run_all.sh`.
