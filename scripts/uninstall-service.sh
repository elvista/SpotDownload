#!/usr/bin/env bash
set -euo pipefail

LABEL="com.cratedigger"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ -f "$PLIST_DST" ]]; then
  launchctl unload "$PLIST_DST" 2>/dev/null || true
  rm "$PLIST_DST"
  echo "==> Removed $PLIST_DST"
else
  echo "==> No plist at $PLIST_DST (nothing to do)"
fi
