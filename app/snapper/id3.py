"""ID3v2.3 tags, written by Snapper itself: the same tag goes at the start of an MP3 and in the 'ID3 ' chunk of a WAV (see
docs/export-format.md). ffmpeg only encodes the audio, so nothing depends on which frames its tag writer knows or on the
operating system's command-line length.

Text is ISO-8859-1 when it fits and otherwise UTF-16 with a byte-order mark, the two encodings ID3v2.3 has."""
from __future__ import annotations

import struct
from typing import NamedTuple, Optional


class Frame(NamedTuple):
    id: str
    desc: Optional[str]    # TXXX / COMM: the description; None for plain text frames
    text: str


def _same_encoding(*strings: str) -> int:
    """One encoding for a frame's strings: ISO-8859-1 if they all fit, else UTF-16."""
    try:
        for t in strings:
            t.encode("latin-1")
        return 0
    except UnicodeEncodeError:
        return 1


def _string(enc: int, text: str, terminate: bool = False) -> bytes:
    if enc == 0:
        return text.encode("latin-1") + (b"\0" if terminate else b"")
    return b"\xff\xfe" + text.encode("utf-16le") + (b"\0\0" if terminate else b"")


def _synchsafe(n: int) -> bytes:
    """A 28-bit size in four bytes of 7 bits, as the tag header requires."""
    return bytes([(n >> 21) & 127, (n >> 14) & 127, (n >> 7) & 127, n & 127])


def _frame(fid: str, payload: bytes) -> bytes:
    return fid.encode("ascii") + struct.pack(">I", len(payload)) + b"\0\0" + payload   # v2.3: plain 32-bit size, no flags


def text_frame(fid: str, text: str) -> bytes:
    enc = _same_encoding(text)
    return _frame(fid, bytes([enc]) + _string(enc, text))


def comment_frame(text: str, desc: str = "", lang: str = "eng") -> bytes:
    enc = _same_encoding(text, desc)
    return _frame("COMM", bytes([enc]) + lang.encode("ascii") + _string(enc, desc, True) + _string(enc, text))


def txxx_frame(desc: str, value: str) -> bytes:
    enc = _same_encoding(desc, value)
    return _frame("TXXX", bytes([enc]) + _string(enc, desc, True) + _string(enc, value))


def uslt_frame(text: str, lang: str = "eng") -> bytes:
    """Unsynchronised lyrics (also what players show as the text or captions): the whole text."""
    enc = _same_encoding(text)
    return _frame("USLT", bytes([enc]) + lang.encode("ascii") + _string(enc, "", True) + _string(enc, text))


def tag(frames: list[bytes]) -> bytes:
    """A whole ID3v2.3 tag: header and `frames`."""
    body = b"".join(frames)
    return b"ID3\x03\x00\x00" + _synchsafe(len(body)) + body


def size_of(data: bytes) -> int:
    """Length in bytes of the ID3v2 tag at the start of `data` (header included), 0 if there is none."""
    if data[:3] != b"ID3" or len(data) < 10:
        return 0
    n = (data[6] & 127) << 21 | (data[7] & 127) << 14 | (data[8] & 127) << 7 | (data[9] & 127)
    return 10 + n + (10 if data[5] & 0x10 else 0)   # a v2.4 footer, if flagged


def _decode(enc: int, raw: bytes) -> str:
    if enc == 1:
        return raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-16le")
    if enc == 2:
        return raw.decode("utf-16be")
    return raw.decode("utf-8" if enc == 3 else "latin-1")


def _split(enc: int, raw: bytes) -> tuple[str, bytes]:
    """(first string, rest) of a terminated string at the start of `raw`."""
    if enc in (1, 2):
        i = 0
        while i + 1 < len(raw) and raw[i:i + 2] != b"\0\0":
            i += 2
        return _decode(enc, raw[:i]), raw[i + 2:]
    i = raw.find(b"\0")
    i = len(raw) if i < 0 else i
    return _decode(enc, raw[:i]), raw[i + 1:]


def _raw_frames(data: bytes):
    """(frame id, body) of every frame of the ID3v2.3/2.4 tag at the start of `data`."""
    total = size_of(data)
    v4 = bool(total) and data[3] == 4
    pos = 10
    while total and pos + 10 <= total:
        fid = data[pos:pos + 4]
        if not fid.strip(b"\0"):
            break   # padding
        raw = data[pos + 4:pos + 8]
        size = ((raw[0] & 127) << 21 | (raw[1] & 127) << 14 | (raw[2] & 127) << 7 | (raw[3] & 127)) if v4 else struct.unpack(">I", raw)[0]
        yield fid.decode("latin-1"), data[pos + 10:pos + 10 + size]
        pos += 10 + size


def parse(data: bytes) -> list[Frame]:
    """The text, comment, lyrics and TXXX frames of the ID3v2.3/2.4 tag at the start of `data` (other frames are skipped).
    Used to read exported files back (tests, and old-or-new WAV reading)."""
    out = []
    for name, body in _raw_frames(data):
        if not body:
            continue
        enc, rest = body[0], body[1:]
        if name == "TXXX":
            desc, value = _split(enc, rest)
            out.append(Frame(name, desc, _decode(enc, value)))
        elif name in ("COMM", "USLT"):
            desc, value = _split(enc, rest[3:])   # skip the language
            out.append(Frame(name, desc, _decode(enc, value)))
        elif name.startswith("T"):
            out.append(Frame(name, None, _decode(enc, rest)))
    return out
