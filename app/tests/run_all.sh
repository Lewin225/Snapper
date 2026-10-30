#!/bin/bash
# (editor, typing, layout and play-clip tests share one window: ui_suite.py)
# Runs every test against the default test video (tests/media/tears_of_steel.mp4, fetched on first use). Run in an environment with the app's
# Python, mpv and ffmpeg; the smoke test goes first because it warms the cache the others read. usage: tests/run_all.sh
cd "$(dirname "$(readlink -f "$0")")/.." || exit 1
PY=${PY:-python3}
export SNAPPER_HWDEC=${SNAPPER_HWDEC:-nvdec-copy} QT_QPA_PLATFORM=${QT_QPA_PLATFORM:-xcb} QT_XCB_GL_INTEGRATION=xcb_egl
export __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json
failed=0
# The tests leave caches and projects in their temp folders; /tmp is memory here (and counts against a container's memory limit),
# so they get a folder of their own that is removed at the end.
export TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
"$(dirname "$0")/fetch_media.sh" || { echo "could not get the test video; stopping" >&2; exit 1; }
for t in smoke ui_suite progress_test project_test tag_kinds_test theme_test \
         prune_test launcher_test system_check_test transfer_test drag_lock_test engine_test isolation_test transcript_ui_test id3_test export_test export_ui_test; do
    echo "=== $t"
    if [ "$t" = isolation_test ] && [ ! -x "${SNAPPER_SEP_PYTHON:-$HOME/envs/sep/bin/python}" ]; then
        echo "skipped: no audio-separator environment (SNAPPER_SEP_PYTHON or ~/envs/sep)"; continue
    fi
    if [ "$t" = export_test ]; then QT_QPA_PLATFORM=offscreen "$PY" -u "tests/$t.py"; else "$PY" -u "tests/$t.py"; fi 2>&1 \
        | grep -v "INVALID_ENUM\|pci id\|pw.conf\|dri2\|Xcb EGL\|propagateSizeHints" | tail -4
    [ "${PIPESTATUS[0]}" = 0 ] || { echo "FAILED: $t"; failed=1; }
done
exit $failed
