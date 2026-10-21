"""Export core: name safety, planning, WAV writing, and that exported samples are exactly the waveform's samples."""
import atexit, os, shutil, subprocess, sys, tempfile
from pathlib import Path

os.environ.setdefault("SNAPPER_DATA", tempfile.mkdtemp())
WORK = Path(tempfile.mkdtemp())
atexit.register(shutil.rmtree, WORK, ignore_errors=True)   # decoded audio is hundreds of MB: always clean up
def mk() -> Path:
    return Path(tempfile.mkdtemp(dir=WORK))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np

from snapper import media
from snapper.export import (ExportSettings, clip_frames, export_clips, plan_files, read_wav, render_name, template_problem,
                            wav_bytes)
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
assert plan == ["Yes/_none/Alastor.wav", "No/7/Alastor.wav", "No/_none/Husk.wav", "No/_none/alastor.wav"], plan
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
        out.write_bytes(wav_bytes(frames, 44100, bits, {"ICMT": "héllo wörld"}, {"character": "A", "overlap": True}))
        w = read_wav(out)
        assert (w["bits"], w["channels"], w["rate"]) == (bits, ch, 44100) and w["format"] == (3 if bits == 32 else 1)
        assert np.array_equal(w["frames"], frames), f"{bits} bit {ch} ch samples differ"
        assert w["info"] == {"ICMT": "héllo wörld"} and w["tags"] == {"character": "A", "overlap": True}
import wave
out16 = mk() / "t16.wav"
out16.write_bytes(wav_bytes(rng.integers(-3000, 3000, (500, 2)).astype(np.int16), 48000, 16, {"INAM": "t"}, {"a": "b"}))
with wave.open(str(out16)) as f:
    assert (f.getnchannels(), f.getframerate(), f.getsampwidth(), f.getnframes()) == (2, 48000, 2, 500)
print("ok   WAV: 16/24/32-bit, mono/stereo round-trip exactly; text and tag chunks; Python's wave module reads it")

# --- the exported samples are the waveform's samples
wf = media.audio_path(episode, 0)
assert wf.exists(), "needs the warm cache (run the app once on this episode)"
wave_pcm = media.open_pcm(wf, 1, 16)
p2 = Project(episode)
p2.clips.clear()
dur = len(wave_pcm) / 44100
for a, b in ((40.0, 42.417), (0.0, 1.5), (53.4567, 55.0), (dur - 1.0, dur), (dur - 0.5, dur + 40.0)):   # the last runs past the end
    p2.add(Clip(a, b, f"clip {a}", True, {"character": "A"}))
settings = ExportSettings(name_template="c{n}", text_field="title", embed_tags=True)
out = mk()
res = export_clips(p2, settings, wave_pcm, out)
assert len(res.files) == 5 and not res.skipped, res
for f, (c, _rel) in zip(res.files, plan_files(p2, settings)):   # files come back in clip-number order
    w = read_wav(f)
    i0, i1 = int(round(c.start * 44100)), min(int(round(c.end * 44100)), len(wave_pcm))
    assert np.array_equal(w["frames"], wave_pcm[i0:i1]), f"{f.name}: samples differ from the waveform"
    assert w["info"] == {"INAM": c.text} and w["tags"] == {"character": "A"}
print("ok   mono 16-bit export is sample-for-sample the waveform audio (incl. start/end of file)")
res = export_clips(p2, ExportSettings(name_template="c{n}", text_field=None, embed_tags=False), wave_pcm, mk())
w = read_wav(res.files[0]); assert w["info"] == {} and w["tags"] is None
print("ok   text field / tags can be left out")

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
    assert tg["comment"] == cm.text and _json.loads(tg["snpr"]) == {"character": "Alastor", "overlap": True}, tg
    dec = decode_mp3(f, 1, 44100).astype(float).ravel()
    ref = clip_frames(wave_pcm, 44100, cm).astype(float).ravel()
    n = min(len(dec), len(ref)); lag = 0
    best = max(range(-2400, 2400, 8), key=lambda L: np.dot(dec[max(L, 0):n + min(L, 0)][:20000], ref[max(-L, 0):][:20000]) if True else 0)
    a = dec[max(best, 0):][:40000]; b = ref[max(-best, 0):][:40000]; m = min(len(a), len(b))
    corr = np.corrcoef(a[:m], b[:m])[0, 1]
    assert corr > 0.97, (q, corr, best)
    assert 0.5 < dec.std() / ref.std() < 1.5
    print(f"ok   MP3 {q}: {j['format']['bit_rate']} bit/s, {float(j['format']['duration']):.3f}s, tags + text read back, decoded audio matches the source (r={corr:.3f})")
sm = ExportSettings(name_template="s", format="mp3", mp3_quality="v0", channels=2, sample_rate=48000, text_field=None, embed_tags=False)
res = export_clips(pm, sm, decode(2, 48000, 16), mk())
j = probe(res.files[0]); assert j["streams"][0]["channels"] == 2 and j["streams"][0]["sample_rate"] == "48000"
assert "comment" not in {k.lower() for k in j["format"].get("tags", {})}
assert plan_files(pm, sm)[0][1].suffix == ".mp3" and ExportSettings.from_json({"mp3_quality": "bogus"}).mp3_quality == "192"
print("ok   MP3 stereo 48 kHz, no text / tags")
print("EXPORT OK")
