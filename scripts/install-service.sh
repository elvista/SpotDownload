#!/usr/bin/env bash
set -euo pipefail

REPO="/Users/elvista/Sites/SpotDownload"
LABEL="com.cratedigger"
PLIST_SRC="$REPO/scripts/$LABEL.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/cratedigger"

echo "==> Building frontend"
cd "$REPO/frontend"
npm install
npm run build

echo "==> Preparing log directory"
mkdir -p "$LOG_DIR"

echo "==> Installing launchd agent"
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DST"

if launchctl list | grep -q "$LABEL"; then
  launchctl unload "$PLIST_DST" 2>/dev/null || true
fi
launchctl load "$PLIST_DST"

sleep 2
if launchctl list | grep -q "$LABEL"; then
  echo "==> CrateDigger is running"
  echo "    Local:   http://127.0.0.1:5174"
  echo "    LAN:     http://$(hostname -s).local:5174"
  echo "    Logs:    $LOG_DIR/"
else
  echo "!! Service failed to start. Check $LOG_DIR/stderr.log"
  exit 1
fi
