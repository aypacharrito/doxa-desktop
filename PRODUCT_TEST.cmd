@echo off
setlocal
cd /d "%~dp0"
set "DOXA_PY=%LOCALAPPDATA%\Programs\Jarvis\runtime\Scripts\python.exe"
if not exist "%DOXA_PY%" (echo Doxa desktop runtime not found. & pause & exit /b 1)
echo Product Test - edit docs\store-pilot-example.json to try another product.
echo Prices and supplier costs in the example are assumptions, not quotes.
choice /m "Generate creative drafts using Doxa's shared OpenAI allowance"
if errorlevel 2 (
 "%DOXA_PY%" store_pilot.py docs\store-pilot-example.json "%TEMP%\doxa-product-test.html"
) else (
 "%DOXA_PY%" store_pilot.py docs\store-pilot-example.json "%TEMP%\doxa-product-test.html" --ai
)
if errorlevel 1 (echo Brief generation failed. & pause & exit /b 1)
start "" "%TEMP%\doxa-product-test.html"
