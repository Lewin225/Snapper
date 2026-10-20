"""WhisperX implementation of SpeechBackend.

Transcribes with faster-whisper (VAD-chunked) and aligns words with a wav2vec2
CTC model. Alignment is character-level, so there are no phoneme timings.
Speaker labelling is not wired up yet (needs a Hugging Face token for pyannote).
"""
from __future__ import annotations

import gc
import subprocess
from typing import Optional

import numpy as np

from contract import Capabilities, Line, Progress, Word

SAMPLE_RATE = 16000


def _read_window(path: str, start: float, end: Optional[float], stream: int = 0) -> np.ndarray:
    """Decode [start, end) of audio stream `stream` to 16 kHz mono float32 via an ffmpeg pipe."""
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{start}"]
    if end is not None:
        cmd += ["-t", f"{end - start}"]
    cmd += ["-i", path, "-map", f"0:a:{stream}", "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


class WhisperXBackend:
    capabilities = Capabilities(word_timing=True, phoneme_timing=False, speakers=False, needs_gpu=True)

    def __init__(self, model: str = "large-v3", device: str = "auto",
                 compute_type: str = "auto", batch_size: int = 16, audio_stream: int = 0):
        self._model_name = model
        if device == "auto":   # the GPU when PyTorch can see one, otherwise the CPU (slower, and 8-bit instead of 16-bit)
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"
        self._device = device
        self._compute_type = compute_type
        self._batch_size = batch_size
        self._audio_stream = audio_stream  # which audio track of the file to read
        self._asr = None
        self._align = {}  # language -> (model, metadata)

    def _load_asr(self, language: str):
        import whisperx
        if self._asr is None:
            self._asr = whisperx.load_model(self._model_name, self._device,
                                            compute_type=self._compute_type, language=language)
        return self._asr

    def _load_align(self, language: str):
        import whisperx
        if language not in self._align:
            self._align[language] = whisperx.load_align_model(language_code=language, device=self._device)
        return self._align[language]

    def transcribe(self, audio_path: str, start: float = 0.0, end: Optional[float] = None, *,
                   language: str = "en", progress: Optional[Progress] = None) -> list[Line]:
        import whisperx
        audio = _read_window(audio_path, start, end, self._audio_stream)
        if audio.size == 0:
            return []

        result = self._load_asr(language).transcribe(audio, batch_size=self._batch_size, language=language)
        if progress:
            progress(0.5)
        align_model, meta = self._load_align(language)
        aligned = whisperx.align(result["segments"], align_model, meta, audio, self._device)
        if progress:
            progress(1.0)

        lines = []
        for seg in aligned["segments"]:
            words = [Word(w["word"],
                          w["start"] + start if "start" in w else None,
                          w["end"] + start if "end" in w else None,
                          w.get("score"))
                     for w in seg.get("words", [])]
            lines.append(Line(seg["start"] + start, seg["end"] + start, seg["text"].strip(), words))
        return lines

    def close(self) -> None:
        self._asr = None
        self._align.clear()
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
