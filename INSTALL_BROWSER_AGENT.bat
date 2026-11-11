@echo off
setlocal
cd /d "%~dp0"
title Doxa browser tasks setup
echo.
echo  Doxa browser tasks - one-time setup
echo  -------------------------------------
echo  Adds the browser-control package (Playwright) to Doxa's runtime.
echo  It drives Microsoft Edge, which is already installed, so nothing else is downloaded.
echo  Close Doxa before continuing.
echo.
pause
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Jarvis\runtime\Scripts\python.exe" set "PY=%LOCALAPPDATA%\Programs\Jarvis\runtime\Scripts\python.exe"
if not defined PY (
  echo Could not find Doxa's Python runtime. Run SETUP_WINDOWS.bat first.
  pause
  exit /b 1
)
"%PY%" -m pip install "playwright>=1.48,<2"
if errorlevel 1 (
  echo.
  echo Installation failed. Check your internet connection and try again.
  pause
  exit /b 1
)
"%PY%" -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(channel='msedge', headless=True); b.close(); p.stop(); print('Microsoft Edge works with Doxa browser tasks.')"
if errorlevel 1 (
  echo.
  echo Edge could not be started. Installing Playwright's own browser instead...
  "%PY%" -m playwright install chromium
)
echo.
echo Done. Start Doxa with START_DOXA.cmd and ask it to book something.
pause
