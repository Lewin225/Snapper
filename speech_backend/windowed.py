"""Backend-agnostic windowed transcription.

Transcribes a long file in fixed windows so memory stays flat. A window can cut a line in half, so the last
line is dropped when it ends at the window edge and the next window starts at that line's start instead.
"""
from __future__ import annotations

from typing import Callable, Iterator, Optional

from contract import Line, SpeechBackend


def transcribe_windowed(backend: SpeechBackend, path: str, duration: float, *, window: float = 120.0,
                        start: float = 0.0, language: str = "en",
                        edge: float = 1.0) -> Iterator[tuple[float, list[Line]]]:
    """Yields (fraction_done, finished_lines) per window, in order, with no duplicates."""
    pos = start
    while pos < duration:
        end = min(pos + window, duration)
        lines = backend.transcribe(path, pos, end, language=language)
        final = end >= duration
        nxt = end
        if not final and lines and lines[-1].end >= end - edge and lines[-1].start > pos:
            nxt = lines.pop().start  # re-transcribe the truncated line from its own start
        yield min(nxt / duration, 1.0), lines
        pos = nxt
