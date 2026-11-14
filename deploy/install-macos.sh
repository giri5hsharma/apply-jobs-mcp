#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/data" "$HOME/Library/LaunchAgents"

python3 - "$ROOT" "$HOME/Library/LaunchAgents/com.apply-jobs-mcp.scan.plist" <<'PY'
import plistlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
destination = Path(sys.argv[2])
job = {
    "Label": "com.apply-jobs-mcp.scan",
    "ProgramArguments": [str(root / ".venv/bin/python"), "-m", "apply_jobs_mcp.worker",
                         "--source", "all", "--keywords", "intern"],
    "WorkingDirectory": str(root),
    "EnvironmentVariables": {"AJM_CONFIG": str(root / "config.example.toml")},
    "StartCalendarInterval": [{"Day": day, "Hour": 7, "Minute": 0}
                              for day in range(1, 32, 3)],
    "StandardOutPath": str(root / "data/scan.log"),
    "StandardErrorPath": str(root / "data/scan.err"),
    "RunAtLoad": False,
}
destination.write_bytes(plistlib.dumps(job))
PY

LABEL="com.apply-jobs-mcp.scan"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl print "gui/$(id -u)/$LABEL" | head -25
