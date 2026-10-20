"""Runs in the WhisperX environment. Prints one `@@{json}` line per finished window.

usage: python transcribe_worker.py MEDIA [--audio-stream N] [--start S] [--end E] [--window 120] [--batch 4] [--language en]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from contract import Line  # noqa: E402
from windowed import transcribe_windowed  # noqa: E402


def duration_of(path: str) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                 "csv=p=0", path], capture_output=True, text=True, check=True).stdout)


def to_json(line: Line) -> dict:
    return {"start": line.start, "end": line.end, "text": line.text, "speaker": line.speaker,
            "words": [{"text": w.text, "start": w.start, "end": w.end} for w in line.words]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float)
    ap.add_argument("--window", type=float, default=120.0)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--language", default="en")
    ap.add_argument("--audio-stream", type=int, default=0, help="audio track (0-based) to transcribe")
    a = ap.parse_args()

    from whisperx_backend import WhisperXBackend
    backend = WhisperXBackend(batch_size=a.batch, audio_stream=a.audio_stream)
    dur = a.end or duration_of(a.media)
    try:
        for frac, lines in transcribe_windowed(backend, a.media, dur, window=a.window, start=a.start,
                                               language=a.language):
            print("@@" + json.dumps({"progress": frac, "lines": [to_json(l) for l in lines]}), flush=True)
    finally:
        backend.close()
    print("@@" + json.dumps({"done": True}), flush=True)


if __name__ == "__main__":
    main()
