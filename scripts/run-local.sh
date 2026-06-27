#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
USE_SUDO=0

if [[ "${1:-}" == "--sudo" ]]; then
  USE_SUDO=1
  shift
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
  if command -v python3.13 >/dev/null 2>&1; then
    BASE_PYTHON="$(command -v python3.13)"
  elif command -v python3 >/dev/null 2>&1; then
    BASE_PYTHON="$(command -v python3)"
  else
    echo "Python 3.10+ is required, but no python3 executable was found." >&2
    exit 1
  fi

  "$BASE_PYTHON" -m venv "$ROOT_DIR/.venv"
  "$VENV_PYTHON" -m pip install -r "$ROOT_DIR/requirements.txt"
fi

if [[ "$USE_SUDO" -eq 1 ]]; then
  exec sudo "$VENV_PYTHON" "$ROOT_DIR/fit_ant_playback_qt.py" "$@"
fi

exec "$VENV_PYTHON" "$ROOT_DIR/fit_ant_playback_qt.py" "$@"
