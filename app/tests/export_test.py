"""Export core: name safety, planning, WAV writing, and that exported samples are exactly the waveform's samples."""
import atexit, json, os, shutil, struct, subprocess, sys, tempfile
from pathlib import Path

os.environ.setdefault("SNAPPER_DATA", tempfile.mkdtemp())
WORK = Path(tempfile.mkdtemp())
atexit.register(shutil.rmtree, WORK, ignore_errors=True)   # decoded audio is hundreds of MB: always clean up
def mk() -> Path:
    return Path(tempfile.mkdtemp(dir=WORK))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np

from snapper import id3, media
from snapper.export import (FORMAT_VERSION, ExportSettings, clip_frames, clip_tag, default_frame, encode_mp3, export_clips,
                            export_signature, frame_for, plan_files, read_wav, render_name, template_problem, wav_bytes)
from snapper.model import Clip, Project
from snapper.pathnames import clean_part, clean_tag, has_invalid_chars

from support import episode_arg
episode = episode_arg()

# --- name safety
assert clean_part('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"
assert clean_part("..") == "_" and clean_part("  . ") == "_" and clean_part("") == "_"
assert clean_part("CON") == "_CON" and clean_part("com1.txt") == "_com1.txt" and clean_part("Alastor") == "Alastor"
assert clean_part("trailing. ") == "trailing" and clean_part("x" * 300, 50) == "x" * 50
assert clean_tag('Ala/stor:?') == "Alastor" and clean_tag("  voice 1. ") == "voice 1" and has_invalid_chars("a|b")
assert Project.tag_name_problem("emotion") is None and Project.tag_name_problem("a/b") and Project.tag_name_problem("Text")
assert Project.tag_name_problem("")
print("ok   path-name rules: invalid characters, dots, reserved names, tag names")

# --- planning
p = Project(episode)
p.add_tag_type("emotion"); p.add_tag_type("loud", "int"); p.add_tag_type("overlap", "bool")
def clip(a, b, text="", **tags):
    return p.add(Clip(a, b, text, True, tags))
clip(10, 11, "Hello there", character="Alastor", emotion="happy", overlap=True)
clip(20, 21, "Second", character="Alastor", emotion="happy", loud=7)
clip(30, 31, "Third", character="Husk")
clip(40, 41, "Fourth", character="alastor", emotion="happy")   # same name, different case
s = ExportSettings(name_template="{character}_{n}", folder_tags=["character", "emotion"])
plan = [str(r) for _c, r in plan_files(p, s)]
assert plan == ["Alastor/happy/Alastor_001.wav", "Alastor/happy/Alastor_002.wav", "Husk/_none/Husk_003.wav",
                "alastor/happy/alastor_004.wav"], plan
s = ExportSettings(name_template="{character}", folder_tags=["overlap", "loud"])
plan = [str(r) for _c, r in plan_files(p, s)]
assert plan == ["overlap-yes/_none/Alastor.wav", "overlap-no/7/Alastor.wav", "overlap-no/_none/Husk.wav",
                "overlap-no/_none/alastor.wav"], plan
assert p.set_bool_labels("overlap", "Overlapping", "Alone") is None   # the labels the user chose name the folders
plan = [str(r) for _c, r in plan_files(p, s)]
assert plan[0] == "Overlapping/_none/Alastor.wav" and plan[1] == "Alone/7/Alastor.wav", plan
assert p.set_bool_labels("overlap", "", "") is None and p.bool_labels("overlap") == ("overlap-yes", "overlap-no")   # empty: the default again
s = ExportSettings(name_template="{character}")   # no folders: same name twice, differing only in case
plan = [str(r) for _c, r in plan_files(p, s)]
assert plan == ["Alastor.wav", "Alastor_2.wav", "Husk.wav", "alastor_3.wav"], plan
s = ExportSettings(name_template="{id}-{start}-{text}")
names = [r.name for _c, r in plan_files(p, s)]
assert names[0] == "1-10000-Hello there.wav", names
assert template_problem("{character}_{n}", p.tag_types) is None
assert template_problem("{nope}", p.tag_types) and template_problem("a/b", p.tag_types) and template_problem("{n", p.tag_types)
assert template_problem("", p.tag_types)
evil = clip(50, 51, "x", character="CON")
evil.tags["character"] = ".."          # even a value that slipped through can't escape the export folder
s = ExportSettings(name_template="{character}", folder_tags=["character"])
assert all(".." not in r.parts for _c, r in plan_files(p, s)), [str(r) for _c, r in plan_files(p, s)]
p.remove(evil)
print("ok   planning: folders by tag, _none for untagged, bool/int tags, case-insensitive clashes, tokens, unsafe values")

# --- WAV writing and reading back
rng = np.random.default_rng(1)
for bits, dtype in ((16, np.int16), (24, np.int32), (32, np.float32)):
    for ch in (1, 2):
        frames = (rng.integers(-2**15, 2**15, (1001, ch)).astype(np.int16) if bits == 16 else
                  (rng.integers(-2**23, 2**23, (1001, ch)).astype(np.int32) << 8 if bits == 24 else
                   rng.uniform(-1, 1, (1001, ch)).astype(np.float32)))
        out = mk() / "t.wav"
        tag = id3.tag([id3.comment_frame("héllo wörld"), id3.txxx_frame("snpr", json.dumps({"tags": {"character": "A", "overlap": True}}))])
        out.write_bytes(wav_bytes(frames, 44100, bits, tag))
        w = read_wav(out)
        assert (w["bits"], w["channels"], w["rate"]) == (bits, ch, 44100) and w["format"] == (3 if bits == 32 else 1)
        assert np.array_equal(w["frames"], frames), f"{bits} bit {ch} ch samples differ"
        assert [f for f in w["id3"] if f.id == "COMM"][0].text == "héllo wörld" and w["tags"] == {"character": "A", "overlap": True}
        assert w["info"] == {} and b"LIST" not in out.read_bytes()   # the ID3 chunk is the only metadata
import wave
out16 = mk() / "t16.wav"
out16.write_bytes(wav_bytes(rng.integers(-3000, 3000, (500, 2)).astype(np.int16), 48000, 16, id3.tag([id3.text_frame("TIT2", "t")])))
with wave.open(str(out16)) as f:
    assert (f.getnchannels(), f.getframerate(), f.getsampwidth(), f.getnframes()) == (2, 48000, 2, 500)
print("ok   WAV: 16/24/32-bit, mono/stereo round-trip exactly; one ID3 chunk for the metadata; Python's wave module reads it")

# --- files from before format 2 (a LIST/INFO chunk and a 'snpr' chunk) are still read
def chunk(cid, payload): return cid + struct.pack("<I", len(payload)) + payload + (b"\0" if len(payload) % 2 else b"")
old = bytearray(wav_bytes(np.zeros((10, 1), np.int16), 44100, 16))
extra = chunk(b"LIST", b"INFO" + chunk(b"ICMT", "old text".encode() + b"\0")) + chunk(b"snpr", json.dumps({"character": "A"}).encode())
legacy = mk() / "legacy.wav"
legacy.write_bytes(b"RIFF" + struct.pack("<I", len(old) - 8 + len(extra)) + bytes(old[8:]) + extra)
w = read_wav(legacy); assert w["info"] == {"ICMT": "old text"} and w["tags"] == {"character": "A"} and w["id3"] == [], w
print("ok   WAV files with the old LIST/INFO and snpr chunks are still read")

# --- the ID3 tag a clip gets (docs/export-format.md)
kinds = {"character": "string", "overlap": "bool", "smug": "bool", "loudness": "int", "title": "string", "year": "int", "Mood": "string"}
labels = {"overlap": ("overlap-yes", "overlap-no"), "smug": ("smug", "calm")}
c = Clip(1.0, 2.0, "Hello “there”", True, {"character": "Trixie", "overlap": True, "loudness": 7, "title": "My title", "year": 2012, "Mood": "Très fier"}, 1)
def frames_of(clip, settings, kinds=kinds, labels=labels):
    t = clip_tag(clip, settings, kinds, labels)
    assert id3.size_of(t) == len(t) and t[:4] == b"ID3\x03"
    return t, id3.parse(t)
def find(fr, fid, desc=None): return [f.text for f in fr if f.id == fid and f.desc == desc]
t, fr = frames_of(c, ExportSettings())
assert find(fr, "USLT", "") == ["Hello “there”"] and find(fr, "COMM") == [], fr   # the clip text is always the lyrics
assert find(fr, "TIT2") == ["My title"] and find(fr, "TYER") == ["2012"], fr   # tags with standard names go to the standard frames
assert find(fr, "TXXX", "character") == ["Trixie"] and find(fr, "TXXX", "loudness") == ["7"] and find(fr, "TXXX", "Mood") == ["Très fier"], fr
assert find(fr, "TXXX", "overlap") == ["overlap-yes"] and find(fr, "TXXX", "smug") == ["calm"], fr   # ticked: Yes word; not ticked: No word
meta = json.loads(find(fr, "TXXX", "snpr")[0])
assert meta == {"format": FORMAT_VERSION, "text": "Hello “there”", "tags": {"character": "Trixie", "overlap": True, "smug": False, "loudness": 7,
                                                                           "title": "My title", "year": 2012, "Mood": "Très fier"}}, meta
off = Clip(1.0, 2.0, "x", True, {"character": "A"}, 2)
fr = frames_of(off, ExportSettings())[1]
assert find(fr, "TXXX", "overlap") == ["overlap-no"] and find(fr, "TXXX", "smug") == ["calm"], fr   # the unticked answer is written too
assert json.loads(find(fr, "TXXX", "snpr")[0])["tags"]["overlap"] is False
print("ok   ID3: clip text as lyrics, standard frames by tag name, a TXXX per other tag, Yes/No answers as their labels, JSON with real types")

# bindings: a tag goes where the settings say; custom, or a standard field under another name
fr = frames_of(c, ExportSettings(tag_frames={"character": "TPE1", "Mood": "COMM", "title": "TXXX", "loudness": "TRCK"}))[1]
assert find(fr, "TPE1") == ["Trixie"] and find(fr, "COMM", "") == ["Très fier"] and find(fr, "TRCK") == ["7"], fr
assert find(fr, "TXXX", "title") == ["My title"] and find(fr, "TIT2") == [] and find(fr, "TXXX", "character") == [], fr
assert find(fr, "USLT", "") == ["Hello “there”"], "the text stays the lyrics whatever the tags are bound to"
assert frame_for(ExportSettings(), "Title") == "TIT2" and frame_for(ExportSettings(), "character") == "TXXX" and default_frame("Genre") == "TCON"
assert frame_for(ExportSettings(tag_frames={"title": "TXXX"}), "title") == "TXXX"
fr = frames_of(Clip(1.0, 2.0, "x", True, {"a": "1", "b": "2"}, 3), ExportSettings(tag_frames={"a": "TIT3", "b": "TIT3"}), {"a": "string", "b": "string"}, {})[1]
assert find(fr, "TIT3") == ["1"] and find(fr, "TXXX", "b") == ["2"], "two tags, one field: the first has it"
bad = ExportSettings.from_json({"tag_frames": {"a": "TIT2", "b": "NOPE", "c": 5}, "text_field": "title"})
assert bad.tag_frames == {"a": "TIT2"} and not hasattr(bad, "text_field") and ExportSettings.from_json({"tag_frames": 3}).tag_frames == {}
assert ExportSettings.from_json(ExportSettings(tag_frames={"a": "TPE1"}).to_json()).tag_frames == {"a": "TPE1"}
# a date that is not a year can't go in TYER; two tags for one frame: the first gets it
fr = frames_of(Clip(1.0, 2.0, "", True, {"year": "n/a", "date": 1999}, 4), ExportSettings(), {"year": "string", "date": "int"}, {})[1]
assert find(fr, "TYER") == ["1999"] and find(fr, "TXXX", "year") == ["n/a"], fr
# options: no tags (the text stays), nothing at all (no text, no tags)
assert clip_tag(Clip(1.0, 2.0, "", True, {"character": "A"}, 6), ExportSettings(embed_tags=False), kinds, labels) == b""
fr = frames_of(c, ExportSettings(embed_tags=False))[1]
assert [f.id for f in fr] == ["USLT", "TXXX"] and "tags" not in json.loads(fr[1].text)
assert id3.parse(clip_tag(Clip(1.0, 2.0, "", True, {}, 5), ExportSettings(), {}, {}))[0].desc == "snpr"   # no text, no tags: still the JSON
print("ok   ID3: tag bindings, two tags for one field, TYER only for years, tags / everything left out")

# --- the signature: the format, the labels and what the file contains decide it
base = export_signature(c, ExportSettings(), 0, labels)
assert export_signature(c, ExportSettings(), 0, labels) == base
assert export_signature(c, ExportSettings(), 0, {**labels, "smug": ("smug", "relaxed")}) != base, "a label is in the file"
untagged = ExportSettings(embed_tags=False, name_template="clip")   # no placeholder: no tag reaches the file or its name
assert export_signature(c, untagged, 0, {**labels, "smug": ("smug", "relaxed")}) == export_signature(c, untagged, 0, labels), \
    "labels do not matter when no tag is used"
named = ExportSettings(embed_tags=False, name_template="{character}_{overlap}")
changed = {**labels, "overlap": ("Overlapping", "Alone")}
assert export_signature(c, named, 0, changed) != export_signature(c, named, 0, labels), "but they do when the name uses that tag"
assert export_signature(c, named, 0, {**labels, "smug": ("smug", "relaxed")}) == export_signature(c, named, 0, labels), \
    "a label nothing uses leaves the signature alone"
assert export_signature(c, ExportSettings(embed_tags=False, folder_tags=["overlap"], name_template="clip"), 0, changed) != \
    export_signature(c, ExportSettings(embed_tags=False, folder_tags=["overlap"], name_template="clip"), 0, labels), "folders count too"
assert export_signature(c, ExportSettings(), 0, {**labels, "extra": ("a", "b")}) != base, "a new Yes/No tag adds an answer to every file"
bound = ExportSettings(tag_frames={"character": "TPE1"})
assert export_signature(c, bound, 0, labels) != base, "binding a tag elsewhere changes the file"
assert export_signature(c, ExportSettings(tag_frames={"character": "TPE1"}, embed_tags=False), 0, labels) == \
       export_signature(c, ExportSettings(embed_tags=False), 0, labels), "with no tags in the file, where they go changes nothing"
print("ok   export signature: format version, Yes/No labels and tag bindings are part of it")

# --- an MP3's tag is the same tag, in front of the audio, with no limit on its size
rate = 44100
tone = (np.sin(np.arange(rate // 2) / 5) * 6000).astype(np.int16).reshape(-1, 1)
big = mk() / "big.mp3"
tag = clip_tag(Clip(0.0, 0.5, "long", True, {"character": "x" * 300_000}, 6), ExportSettings(), {"character": "string"}, {})   # beyond the old command-line limit
encode_mp3(tone, rate, "128", big, tag)
raw = big.read_bytes()
assert id3.size_of(raw) == len(tag) and raw[:len(tag)] == tag and raw[len(tag)] == 0xFF, "the tag is first, then the audio"
assert find(id3.parse(raw), "TXXX", "character") == ["x" * 300_000]
dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(big)], capture_output=True, text=True).stdout)
assert abs(dur - 0.5) < 0.06, dur
print("ok   MP3: our ID3 tag first, then the audio; a 300 000 character tag works")

# --- the exported samples are the waveform's samples
wf = media.audio_path(episode, 0)
assert wf.exists(), "needs the warm cache (run the app once on this episode)"
wave_pcm = media.open_pcm(wf, 1, 16)
p2 = Project(episode)
p2.clips.clear()
dur = len(wave_pcm) / 44100
for a, b in ((40.0, 42.417), (0.0, 1.5), (53.4567, 55.0), (dur - 1.0, dur), (dur - 0.5, dur + 40.0)):   # the last runs past the end
    p2.add(Clip(a, b, f"clip {a}", True, {"character": "A"}))
settings = ExportSettings(name_template="c{n}", embed_tags=True)
out = mk()
res = export_clips(p2, settings, wave_pcm, out)
assert len(res.files) == 5 and not res.skipped, res
for f, (c, _rel) in zip(res.files, plan_files(p2, settings)):   # files come back in clip-number order
    w = read_wav(f)
    i0, i1 = int(round(c.start * 44100)), min(int(round(c.end * 44100)), len(wave_pcm))
    assert np.array_equal(w["frames"], wave_pcm[i0:i1]), f"{f.name}: samples differ from the waveform"
    assert [f.text for f in w["id3"] if f.id == "USLT"] == [c.text] and w["tags"] == {"character": "A"} and w["meta"]["format"] == FORMAT_VERSION
print("ok   mono 16-bit export is sample-for-sample the waveform audio (incl. start/end of file)")
res = export_clips(p2, ExportSettings(name_template="c{n}", embed_tags=False), wave_pcm, mk())
w = read_wav(res.files[0]); assert [f.id for f in w["id3"]] == ["USLT", "TXXX"] and w["tags"] is None
print("ok   tags can be left out (the text stays)")

# --- stereo, 24-bit and float decodes line up with the waveform in time
info = media.probe(episode)
def decode(ch, rate, bits):
    path = mk() / "d.pcm"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *media.pcm_args(info, 0, ch, rate, bits), str(path)], check=True)
    return media.open_pcm(path, ch, bits)
st = decode(2, 44100, 16)
assert abs(len(st) - len(wave_pcm)) <= 2, (len(st), len(wave_pcm))
a, b = int(40 * 44100), int(45 * 44100)
mono_ref = wave_pcm[a:b, 0].astype(np.float64)
mix = st[a:b].astype(np.float64).mean(axis=1)
def best_lag(x, y, maxlag=2000):
    lags = range(-maxlag, maxlag + 1, 1)
    c = [np.dot(x[maxlag:-maxlag], np.roll(y, l)[maxlag:-maxlag]) for l in lags]
    return list(lags)[int(np.argmax(c))]
lag = best_lag(mono_ref, mix)
assert lag == 0, f"stereo decode is {lag} samples off the waveform"
print(f"ok   stereo decode is aligned with the waveform audio (lag {lag} samples, {len(st)} frames)")
d24 = decode(1, 44100, 24)
assert len(d24) == len(wave_pcm)
assert np.max(np.abs((d24[a:b, 0] >> 16).astype(np.int64) - wave_pcm[a:b, 0].astype(np.int64))) <= 20
f32 = decode(1, 44100, 32)
dif = np.abs(f32[a:b, 0] * 32768 - wave_pcm[a:b, 0].astype(np.float64)); print("float vs s16: max", dif.max(), "n>2:", int((dif > 2).sum()), "peak f32", float(np.abs(f32[a:b,0]).max()))
assert dif.max() <= 20, "float decode must be the same loudness as the 16-bit one"
res = export_clips(p2, ExportSettings(name_template="c{n}", channels=2, bit_depth=24), st if False else decode(2, 44100, 24), mk())
w = read_wav(res.files[0]); assert w["channels"] == 2 and w["bits"] == 24
print("ok   24-bit and float decodes match the waveform; a stereo 24-bit export is written")

# --- MP3
import json as _json
def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, text=True)
    return _json.loads(r.stdout)
def decode_mp3(path, ch, rate):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", str(ch), "-ar", str(rate), "-"], capture_output=True).stdout
    return np.frombuffer(raw, "<i2").reshape(-1, ch)
pm = Project(episode); pm.add_tag_type("overlap", "bool")
cm = pm.add(Clip(40.0, 42.417, "But, yeah, “that” might be fun.", True, {"character": "Alastor", "overlap": True}))
for q, kbps_lo, kbps_hi in (("128", 120e3, 136e3), ("v2", 40e3, 260e3)):
    sm = ExportSettings(name_template="m_{n}", format="mp3", mp3_quality=q, folder_tags=["character"])
    assert sm.source_bits == 16
    res = export_clips(pm, sm, wave_pcm, mk())
    assert len(res.files) == 1 and not res.skipped and res.files[0].suffix == ".mp3" and res.files[0].parent.name == "Alastor", res
    f = res.files[0]; j = probe(f)
    st = j["streams"][0]; tg = {k.lower(): v for k, v in j["format"]["tags"].items()}
    assert st["codec_name"] == "mp3" and st["channels"] == 1 and st["sample_rate"] == "44100", st
    assert abs(float(j["format"]["duration"]) - 2.417) < 0.06, j["format"]["duration"]
    assert kbps_lo < float(j["format"]["bit_rate"]) < kbps_hi, (q, j["format"]["bit_rate"])
    assert next(v for k, v in tg.items() if k.startswith("lyrics")) == cm.text and tg["character"] == "Alastor" and tg["overlap"] == "overlap-yes", tg
    assert _json.loads(tg["snpr"]) == {"format": FORMAT_VERSION, "text": cm.text, "tags": {"character": "Alastor", "overlap": True}}, tg
    head = f.read_bytes()[:10]
    assert head[:5] == b"ID3\x03\x00" and "encoder" not in tg, (head, tg)
    dec = decode_mp3(f, 1, 44100).astype(float).ravel()
    ref = clip_frames(wave_pcm, 44100, cm).astype(float).ravel()
    n = min(len(dec), len(ref)); lag = 0
    best = max(range(-2400, 2400, 8), key=lambda L: np.dot(dec[max(L, 0):n + min(L, 0)][:20000], ref[max(-L, 0):][:20000]) if True else 0)
    a = dec[max(best, 0):][:40000]; b = ref[max(-best, 0):][:40000]; m = min(len(a), len(b))
    corr = np.corrcoef(a[:m], b[:m])[0, 1]
    assert corr > 0.97, (q, corr, best)
    assert 0.5 < dec.std() / ref.std() < 1.5
    print(f"ok   MP3 {q}: {j['format']['bit_rate']} bit/s, {float(j['format']['duration']):.3f}s, tags + text read back, decoded audio matches the source (r={corr:.3f})")
sm = ExportSettings(name_template="s", format="mp3", mp3_quality="v0", channels=2, sample_rate=48000, embed_tags=False)
res = export_clips(pm, sm, decode(2, 48000, 16), mk())
j = probe(res.files[0]); assert j["streams"][0]["channels"] == 2 and j["streams"][0]["sample_rate"] == "48000"
assert "comment" not in {k.lower() for k in j["format"].get("tags", {})}
assert plan_files(pm, sm)[0][1].suffix == ".mp3" and ExportSettings.from_json({"mp3_quality": "bogus"}).mp3_quality == "192"
print("ok   MP3 stereo 48 kHz, no text / tags")
print("EXPORT OK")
