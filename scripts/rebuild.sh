#!/usr/bin/env bash
set -euo pipefail

REPO="/Users/elvista/Sites/SpotDownload"
LABEL="com.cratedigger"

echo "==> Rebuilding frontend"
cd "$REPO/frontend"
npm run build

echo "==> Restarting backend"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

sleep 2
echo "==> Done. http://127.0.0.1:5174"
