#!/bin/bash
# Double-click launcher for FIT ANT+ Playback on macOS

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "Python 3 not found."
  read -r -n 1 -p "Press any key to close..."
  echo
  exit 1
fi

echo "Starting FIT ANT+ Playback..."
echo "You may be prompted for your password for USB/ANT+ access."
echo

sudo "$PYTHON_BIN" "$SCRIPT_DIR/fit_ant_playback.py"
EXIT_CODE=$?

echo
if [ "$EXIT_CODE" -ne 0 ]; then
  echo "App exited with code $EXIT_CODE."
else
  echo "App closed."
fi
read -r -n 1 -p "Press any key to close..."
echo
exit "$EXIT_CODE"
