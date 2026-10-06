#!/bin/sh
# Launch Aubade native app (needs system python for GTK4/libadwaita/GStreamer).
cd "$(dirname "$0")"
exec /usr/bin/python3 -m aubade "$@"
