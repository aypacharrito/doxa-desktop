@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run SETUP_WINDOWS.bat first.
  pause
  exit /b 1
)
echo Installing the optional official PyTorch CUDA 12.8 runtime, approximately 3.3 GB.
echo This is separate from your downloaded chat model. A compatible NVIDIA driver is needed.
".venv\Scripts\python.exe" -m pip install "torch==2.7.1" --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 (
  echo Installation failed. Check internet connection and the error above.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import torch; print('PyTorch:', torch.__version__); print('CUDA available:', torch.cuda.is_available()); print(torch.cuda.get_device_name() if torch.cuda.is_available() else 'GPU training unavailable; check driver or select CPU')"
pause
