#!/usr/bin/env bash
# Installs the scan timer as a systemd user service.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HOME/.config/systemd/user"
mkdir -p "$DEST"

for f in deploy/apply-jobs-scan.service deploy/apply-jobs-scan.timer; do
  sed "s|@ROOT@|$ROOT|g" "$f" > "$DEST/$(basename "$f")"
done

systemctl --user daemon-reload
systemctl --user enable --now apply-jobs-scan.timer
echo "--- timers ---"
systemctl --user list-timers "apply-jobs-scan.timer" || true
echo "Next scan: every 3 days at 07:00 IST (see 'systemctl --user list-timers')."
