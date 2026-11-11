@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Doxa has not been set up yet.
  echo Run SETUP_WINDOWS.bat first.
  pause
  exit /b 1
)
start "Doxa" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
