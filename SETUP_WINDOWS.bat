@echo off
setlocal
cd /d "%~dp0"
title Doxa Setup
echo.
echo  Doxa setup
echo  ----------------
echo  1. NVIDIA RTX GPU - CUDA 12.4 (recommended for RTX 4070)
echo  2. NVIDIA/AMD/Intel GPU - Vulkan fallback
echo  3. CPU only
echo.
set /p choice="Choose 1, 2, or 3: "
if "%choice%"=="2" set backend=Vulkan
if "%choice%"=="3" set backend=CPU
if not defined backend set backend=CUDA
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -Backend %backend%
if errorlevel 1 (
  echo.
  echo Setup did not finish. Read the message above.
  pause
  exit /b 1
)
echo.
echo Setup complete. Opening Doxa...
call "%~dp0START_FORGEMIND.bat"
