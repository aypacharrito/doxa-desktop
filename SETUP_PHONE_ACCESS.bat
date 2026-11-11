@echo off
setlocal
title Doxa phone access setup
echo.
echo  Doxa phone access - one-time setup
echo  ------------------------------------
echo  Installs Cloudflare's tunnel connector (cloudflared), which lets your phone
echo  reach Doxa on this PC securely. No router or firewall changes.
echo.
pause
where cloudflared >nul 2>nul && goto done
winget --version >nul 2>nul
if not errorlevel 1 (
  winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
  if not errorlevel 1 goto done
)
echo Downloading cloudflared from Cloudflare's official GitHub releases...
if not exist "%LOCALAPPDATA%\ForgeMind\bin" mkdir "%LOCALAPPDATA%\ForgeMind\bin"
powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile \"$env:LOCALAPPDATA\ForgeMind\bin\cloudflared.exe\""
if errorlevel 1 (
  echo Download failed. Check your internet connection and try again.
  pause
  exit /b 1
)
:done
echo.
echo Done. In Doxa press Ctrl+K, choose "Phone access...", turn it on and start a link.
pause
