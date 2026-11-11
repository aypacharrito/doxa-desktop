@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "Doxa" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
  exit /b 0
)
if exist "%LOCALAPPDATA%\Programs\Jarvis\runtime\Scripts\pythonw.exe" (
  start "Doxa" "%LOCALAPPDATA%\Programs\Jarvis\runtime\Scripts\pythonw.exe" "%~dp0app.py"
  exit /b 0
)
echo Run SETUP_WINDOWS.bat once, then start Doxa again.
pause
