@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "Doxa Research Lab" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
  exit /b 0
)
if exist "..\ForgeMind-Computer-Windows-v1.4.0\.venv\Scripts\pythonw.exe" (
  start "ForgeMind Research Lab" "..\ForgeMind-Computer-Windows-v1.4.0\.venv\Scripts\pythonw.exe" "%~dp0app.py"
  exit /b 0
)
echo No existing runtime was found beside this release.
echo Run SETUP_WINDOWS.bat here, then INSTALL_RESEARCH_GPU.bat for neural training.
pause
exit /b 1
