#!/bin/bash
# Start Doxa on macOS (experimental). Double-click in Finder.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Run SETUP_MAC.command once, then start Doxa again."
  exit 1
fi
exec .venv/bin/python app.py
