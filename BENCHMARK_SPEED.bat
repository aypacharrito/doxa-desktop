@echo off
setlocal
cd /d "%~dp0"
title Doxa speed benchmark
echo Close Doxa first - the benchmark needs the GPU. Takes about a minute.
pause
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY set "PY=%LOCALAPPDATA%\Programs\Jarvis\runtime\Scripts\python.exe"
"%PY%" benchmark_speed.py
echo.
echo Saved to benchmark-results.txt
pause
