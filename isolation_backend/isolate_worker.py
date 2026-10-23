"""Runs in the audio-separator environment. Separates the vocals (the dialogue) from a long file, one window at a time.

The input is raw 16-bit little-endian stereo PCM at 44.1 kHz; the output is the same as a WAV file (so players can open
it), sample N being the same moment in both. The input is memory-mapped and each window is processed on its own, so memory stays flat however long the episode is. Neighbouring
windows overlap and are crossfaded, which hides the seams a hard cut between chunks would leave.

Prints `@@{json}` lines: {"stage": text}, {"progress": 0..1}, {"device": text}, finally {"done": true}.

usage: python isolate_worker.py IN.pcm OUT.wav --model NAME --model-dir DIR [--window 45] [--overlap 5] [--work DIR]
"""
import argparse
import json
import os
import shutil
import struct
import sys
import tempfile
from pathlib import Path

import numpy as np

RATE = 44100


def say(**kw):
    print("@@" + json.dumps(kw), flush=True)


def wav_header(frames: int) -> bytes:
    """A 44-byte header for 16-bit stereo 44.1 kHz PCM of `frames` frames (the length is known before writing)."""
    data = frames * 4
    return (b"RIFF" + struct.pack("<I", 36 + data) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 2, RATE, RATE * 4, 4, 16)
            + b"data" + struct.pack("<I", data))


def to_pcm16(x: np.ndarray) -> bytes:
    return (np.clip(x, -1.0, 1.0) * 32767.0).round().astype("<i2").tobytes()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pcm_in")
    ap.add_argument("pcm_out")
    ap.add_argument("--model", required=True)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--window", type=float, default=45.0)
    ap.add_argument("--overlap", type=float, default=5.0)
    ap.add_argument("--work", default=None, help="scratch folder (default: a temporary one)")
    a = ap.parse_args()

    import logging
    import soundfile as sf
    from audio_separator.separator import Separator

    data = np.memmap(a.pcm_in, dtype="<i2", mode="r").reshape(-1, 2)
    total = len(data)
    L, O = int(a.window * RATE), int(a.overlap * RATE)
    assert L > 2 * O > 0, "the window must be longer than twice the overlap"
    work = Path(a.work or tempfile.mkdtemp(prefix="snapper-isolate-"))
    work.mkdir(parents=True, exist_ok=True)
    Path(a.model_dir).mkdir(parents=True, exist_ok=True)

    say(stage="Loading the vocal model (the first time this downloads it)…")
    # normalization 1.0: only a peak above full scale is ever scaled, so every window keeps the original's level
    sep = Separator(output_dir=str(work), model_file_dir=a.model_dir, output_format="WAV", output_single_stem="Vocals",
                    normalization_threshold=1.0, amplification_threshold=0.0, log_level=logging.WARNING)
    sep.load_model(model_filename=a.model)
    say(device=str(getattr(sep, "torch_device", "")))
    say(stage="Isolating…", progress=0.0)

    def vocals(lo: int, hi: int) -> np.ndarray:
        src = work / "window.wav"
        sf.write(src, data[lo:hi].astype(np.float32) / 32768.0, RATE, subtype="FLOAT")
        names = sep.separate(str(src))
        out = Path(names[0]) if Path(names[0]).is_absolute() else work / names[0]
        y, rate = sf.read(out, dtype="float32", always_2d=True)
        assert rate == RATE, f"the model returned {rate} Hz"
        for f in (src, out):
            f.unlink(missing_ok=True)
        if len(y) < hi - lo:                     # models may drop a few samples at the end
            y = np.pad(y, ((0, hi - lo - len(y)), (0, 0)))
        return y[:hi - lo, :2]

    tmp = Path(str(a.pcm_out) + ".tmp")
    try:
        with open(tmp, "wb") as out:
            out.write(wav_header(total))
            tail = None
            start = 0
            while start < total:
                end = min(start + L, total)
                chunk = vocals(start, end)
                if tail is not None:                       # fade the previous window's end into this window's start
                    k = min(len(tail), len(chunk))
                    ramp = np.linspace(0.0, 1.0, k, dtype=np.float32)[:, None]
                    out.write(to_pcm16(tail[:k] * (1.0 - ramp) + chunk[:k] * ramp))
                    chunk = chunk[k:]
                if end >= total:
                    out.write(to_pcm16(chunk))
                    break
                out.write(to_pcm16(chunk[:-O]))
                tail = chunk[-O:]
                start = end - O
                say(progress=min(end / total, 0.999))
        os.replace(tmp, a.pcm_out)
        assert os.path.getsize(a.pcm_out) == 44 + total * 4, "the output is not the same length as the input"
    finally:
        tmp.unlink(missing_ok=True)
        if a.work is None:
            shutil.rmtree(work, ignore_errors=True)
    say(progress=1.0)
    say(done=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # reported to the app, which shows it
        say(error=f"{type(e).__name__}: {e}")
        raise
