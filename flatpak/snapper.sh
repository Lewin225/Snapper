#!/bin/sh
# Starts Snapper inside the Flatpak sandbox.
export PYTHONPATH=/app/lib/snapper-app${PYTHONPATH:+:$PYTHONPATH}
# The KDE colour scheme the base app shares from the host (xdg-config/kdeglobals:ro) is at the host's config path.
if [ -z "$SNAPPER_KDEGLOBALS" ]; then
    for f in "${HOST_XDG_CONFIG_HOME:-}/kdeglobals" "$HOME/.config/kdeglobals" "$XDG_CONFIG_HOME/kdeglobals"; do
        [ -r "$f" ] && SNAPPER_KDEGLOBALS=$f && break
    done
    export SNAPPER_KDEGLOBALS
fi
# Hardware video decoding with the frames copied back (the safe variant; uses NVDEC through the host's NVIDIA GL extension).
export SNAPPER_HWDEC=${SNAPPER_HWDEC:-auto-copy}
exec python3 -u -m snapper "$@"
