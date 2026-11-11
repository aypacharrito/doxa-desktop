"""Stable Doxa launcher: lives in %LOCALAPPDATA%\Programs\Jarvis and opens the version in current.txt.

Taskbar pins and shortcuts point here, so upgrading Doxa only means changing current.txt
(e.g. "app-1.12.3"); old pins keep working and keep the Doxa icon.
"""
import os
import runpy
import sys
from pathlib import Path

home = Path(__file__).resolve().parent
try:
    folder = (home / "current.txt").read_text(encoding="utf-8").strip()
except OSError:
    folder = ""
app = home / folder / "app.py" if folder else None
if not app or not app.is_file():  # fall back to the newest installed version
    versions = sorted(home.glob("app-*/app.py"),
                      key=lambda p: tuple(int(x) for x in p.parent.name[4:].split(".") if x.isdigit()))
    app = versions[-1]
os.chdir(app.parent)
sys.path.insert(0, str(app.parent))
sys.argv = [str(app)]
runpy.run_path(str(app), run_name="__main__")
