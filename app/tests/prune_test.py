"""Proxy cache pruning: oldest (least recently used) proxies go first once over the limit; the one in use stays."""
import os, sys, tempfile, time
from pathlib import Path

root = Path(tempfile.mkdtemp())
os.environ["SNAPPER_CACHE"] = str(root)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from snapper import media

def make(name, size, age):
    d = root / name; d.mkdir()
    f = d / "proxy_480_all.mkv"; f.write_bytes(b"x" * size)
    t = time.time() - age; os.utime(f, (t, t))
    (d / "audio_44100.s16").write_bytes(b"y" * 5000)   # other cache files are never pruned
    return f

a, b, c = make("a", 1000, 300), make("b", 1000, 200), make("c", 1000, 100)
assert media.prune_proxies(limit=3000) == []
assert media.prune_proxies(limit=2500) == [a] and not a.exists() and b.exists() and c.exists()
print("ok   over the limit: the oldest proxy goes")
media.touch_proxy(b)                       # b used just now, so c is now the oldest
assert media.prune_proxies(limit=1500) == [c] and b.exists()
print("ok   using a proxy protects it (least recently used goes first)")
assert media.prune_proxies(keep=b, limit=10) == [] and b.exists()
print("ok   the proxy in use is never removed, even when it alone exceeds the limit")
assert (root / "a" / "audio_44100.s16").exists()
print("PRUNE OK")
