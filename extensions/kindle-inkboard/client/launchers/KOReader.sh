#!/bin/sh
# Offline KOReader launcher for the HDNEXT Scriptlets integration.
KOREADER_DIR=/mnt/us/koreader
export KOREADER_DIR
cd "$KOREADER_DIR" || exit 1
exec /bin/sh ./koreader.sh > "$KOREADER_DIR/ark-launch.log" 2>&1
