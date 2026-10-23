"""The installer's download display: reading pip's `--progress-bar raw` output into bytes, rate, time left and totals."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from snapper import engine
from snapper.engine import TransferMeter, describe, format_bytes, format_duration

assert format_bytes(512) == "512 B" and format_bytes(18_400) == "18 KB" and format_bytes(16_526_072) == "16.5 MB" \
    and format_bytes(2_500_000_000) == "2.5 GB"
assert format_duration(26) == "0:26" and format_duration(65) == "1:05" and format_duration(3725) == "1:02:05"

now = [100.0]
m = TransferMeter(clock=lambda: now[0])
assert m.feed("Collecting torch==2.8.0") is None
assert m.feed("  Downloading torch-2.8.0.whl.metadata (30 kB)") is None, "metadata downloads are not counted as files"
assert m.feed("Downloading torch-2.8.0-cp313-cp313-manylinux_2_28_x86_64.whl (800.0 MB)") is None
assert m.feed("Progress 0 of 800000000").total == 800_000_000
for i in range(1, 9):                                   # 50 MB per second for 8 seconds
    now[0] += 1.0
    t = m.feed(f"Progress {i * 50_000_000} of 800000000")
assert abs(t.rate - 50e6) < 1e6 and t.done == 400_000_000 and t.files == 1, t
text = describe(t)
assert "torch-2.8.0: 400.0 MB of 800.0 MB" in text and "50.0 MB/s" in text and "0:08 left" in text, text
assert "Downloaded so far: 400.0 MB in 1 file" in text, text

m.feed("Downloading numpy-2.2.6-cp313-cp313-manylinux_2_17_x86_64.whl (16.5 MB)")   # the next file adds to the total
now[0] += 1.0
t = m.feed("Progress 8000000 of 16500000")
assert t.name.startswith("numpy") and t.files == 2 and t.all_bytes == 800_000_000 + 8_000_000, t
assert t.rate > 0
assert m.feed("Progress 5 of 5").name.startswith("numpy"), "still the same file"
assert engine.TransferMeter().feed("Progress 5 of 10") is None, "numbers before any file name are ignored"
print("ok   pip's download output becomes a file name, bytes, rate, time left and a running total")
print("TRANSFER OK")
