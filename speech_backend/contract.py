"""Backend-neutral contract for transcription, timing and speaker labelling.

Any engine (WhisperX, MFA + Whisper, a cloud API, subtitles) implements
SpeechBackend and returns Lines. The app never imports an engine directly.
Timings are seconds from the start of the source media, not of the window.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol


@dataclass
class Phoneme:
    symbol: str
    start: float
    end: float


@dataclass
class Word:
    text: str
    start: Optional[float]  # None when the engine could not align the word
    end: Optional[float]
    score: Optional[float] = None
    phonemes: Optional[list[Phoneme]] = None


@dataclass
class Line:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    speaker: Optional[str] = None  # engine label such as "voice1", renamed by the user later


@dataclass(frozen=True)
class Capabilities:
    word_timing: bool
    phoneme_timing: bool
    speakers: bool
    needs_gpu: bool


Progress = Callable[[float], None]  # 0.0 .. 1.0


class SpeechBackend(Protocol):
    capabilities: Capabilities

    def transcribe(
        self,
        audio_path: str,
        start: float = 0.0,
        end: Optional[float] = None,
        *,
        language: str = "en",
        progress: Optional[Progress] = None,
    ) -> list[Line]:
        """Transcribe [start, end) of audio_path. Reads only that window, so
        memory does not grow with file length. Returned times are absolute."""
        ...

    def close(self) -> None:
        """Release models and GPU memory."""
        ...
