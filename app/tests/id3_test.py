"""ID3v2.3 writing and reading (snapper/id3.py): encodings, frame layout, tag size, and reading a v2.4 tag."""
import struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from snapper import id3

# --- layout: header, synchsafe tag size, plain 32-bit frame sizes
t = id3.tag([id3.text_frame("TIT2", "Hello")])
assert t[:5] == b"ID3\x03\x00" and t[5] == 0
body = t[10:]
assert body[:4] == b"TIT2" and struct.unpack(">I", body[4:8])[0] == 6 and body[8:10] == b"\0\0" and body[10:] == b"\x00Hello"
assert (t[6] & 0x80) == 0 and id3.size_of(t) == len(t) == 10 + len(body)
big = id3.tag([id3.txxx_frame("k", "x" * 300_000)])   # sizes beyond 127 / 16383 use all four synchsafe bytes
assert id3.size_of(big) == len(big) and all(b < 128 for b in big[6:10]) and id3.parse(big)[0].text == "x" * 300_000
assert id3.size_of(b"") == 0 and id3.size_of(b"\xff\xfb\x90") == 0 and id3.size_of(b"ID3") == 0
print("ok   header, synchsafe tag size, 32-bit frame sizes")

# --- encodings: ISO-8859-1 when it fits, UTF-16 with a byte-order mark when not
assert id3.text_frame("TIT2", "Très")[10] == 0 and id3.text_frame("TIT2", "“Très”")[10] == 1
assert id3.text_frame("TIT2", "“x”")[11:13] == b"\xff\xfe"
texts = ["", "plain", "Très fier", "“curly” — dash", "日本語", "emoji 🙂", "line\nbreak"]
for x in texts:
    assert id3.parse(id3.tag([id3.text_frame("TIT2", x)])) == [id3.Frame("TIT2", None, x)], x
    assert id3.parse(id3.tag([id3.comment_frame(x)])) == [id3.Frame("COMM", "", x)], x
    assert id3.parse(id3.tag([id3.txxx_frame("name", x)])) == [id3.Frame("TXXX", "name", x)], x
    assert id3.parse(id3.tag([id3.txxx_frame("Nömé “1”", x)])) == [id3.Frame("TXXX", "Nömé “1”", x)], x
c = id3.comment_frame("hi")
assert c[10] == 0 and c[11:14] == b"eng" and c[14:] == b"\0hi"   # encoding, language, empty description, text
print("ok   text, comment and TXXX frames round-trip, Latin-1 and UTF-16")

# --- several frames in order; unknown frames are skipped; padding ends the tag
frames = [id3.text_frame("TIT2", "a"), id3.txxx_frame("one", "1"), b"APIC" + struct.pack(">I", 3) + b"\0\0" + b"xyz", id3.text_frame("TRCK", "5")]
tg = id3.tag(frames)
assert [(f.id, f.desc, f.text) for f in id3.parse(tg)] == [("TIT2", None, "a"), ("TXXX", "one", "1"), ("TRCK", None, "5")]
padded = bytearray(tg + b"\0" * 20); n = len(padded) - 10   # the padding is part of the tag size
padded[6:10] = bytes([(n >> 21) & 127, (n >> 14) & 127, (n >> 7) & 127, n & 127])
assert [f.id for f in id3.parse(bytes(padded) + b"audio")] == ["TIT2", "TXXX", "TRCK"] and id3.size_of(bytes(padded)) == len(padded)
assert id3.parse(b"\xff\xfbaudio") == []
print("ok   frame order, skipped frames, padding")

# --- a v2.4 tag from another tool: synchsafe frame sizes, UTF-8, a footer flag
def v4frame(fid, payload):
    n = len(payload)
    return fid + bytes([(n >> 21) & 127, (n >> 14) & 127, (n >> 7) & 127, n & 127]) + b"\0\0" + payload
f4 = v4frame(b"TIT2", b"\x03" + "Très “ok”".encode()) + v4frame(b"TXXX", b"\x03" + b"d\0" + "v—1".encode())
n = len(f4)
t4 = b"ID3\x04\x00\x10" + bytes([(n >> 21) & 127, (n >> 14) & 127, (n >> 7) & 127, n & 127]) + f4 + b"3DI" + b"\x04\x00\x10" + bytes(4)
assert id3.size_of(t4) == len(t4) and [(f.id, f.desc, f.text) for f in id3.parse(t4)] == [("TIT2", None, "Très “ok”"), ("TXXX", "d", "v—1")]
print("ok   reads a v2.4 tag (synchsafe sizes, UTF-8, footer)")
lyr = id3.tag([id3.uslt_frame("Hello “there”"), id3.uslt_frame("plain")])
assert [(f.id, f.desc, f.text) for f in id3.parse(lyr)] == [("USLT", "", "Hello “there”"), ("USLT", "", "plain")]
assert id3.uslt_frame("plain")[10:] == b"\x00eng\x00plain"
print("ok   USLT lyrics frame: layout and round trip, Latin-1 and UTF-16")
print("ID3 OK")
