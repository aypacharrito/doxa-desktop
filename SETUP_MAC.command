#!/bin/bash
# Doxa setup for macOS (experimental). Double-click in Finder, or run: bash SETUP_MAC.command
set -e
cd "$(dirname "$0")"
echo ""
echo " Doxa setup (Mac)"
echo " ----------------"

PY=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys, tkinter; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)' 2>/dev/null; then
      PY="$candidate"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10-3.12 with Tk is required. Install Python 3.12 from https://www.python.org/downloads/macos/"
  echo "(the python.org installer includes Tk; Homebrew's python also needs: brew install python-tk@3.12)"
  exit 1
fi

echo "Creating Doxa's private Python environment with $PY..."
"$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo "Installing the local AI engine (Apple Metal)... this can take several minutes."
if ! CMAKE_ARGS="-DGGML_METAL=on" .venv/bin/python -m pip install --upgrade llama-cpp-python; then
  echo ""
  echo "The local model engine didn't install (it needs Xcode command line tools: xcode-select --install)."
  echo "Doxa still works with paid AIs (Settings -> AI brains). Run this setup again later to add it."
fi

.venv/bin/python -m playwright install chromium || echo "Browser tasks need: .venv/bin/python -m playwright install chromium"

chmod +x START_DOXA_MAC.command
echo ""
echo "Setup complete. Start Doxa with START_DOXA_MAC.command"
