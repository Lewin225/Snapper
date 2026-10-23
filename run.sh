#!/bin/bash
# Runs Snapper from a source checkout, with your own Python.
#   ./run.sh [video-or-project]
# Needs Python 3.10+ with the packages in app/requirements.txt (pip install -r app/requirements.txt), the libmpv library,
# and ffmpeg on PATH. Set PYTHON to use a particular interpreter (e.g. a virtual environment's).
HERE="$(dirname "$(readlink -f "$0")")"
PY="${PYTHON:-python3}"
if ! "$PY" -c "import PySide6, mpv, numpy" 2>/dev/null; then
    echo "Snapper needs PySide6, python-mpv and numpy (and libmpv): pip install -r $HERE/app/requirements.txt" >&2
    exit 1
fi
command -v ffmpeg >/dev/null || { echo "Snapper needs ffmpeg on your PATH." >&2; exit 1; }
cd "$HERE/app" && exec "$PY" -u -m snapper "$@"
