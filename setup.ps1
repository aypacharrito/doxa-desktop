param(
    [ValidateSet("CUDA", "Vulkan", "CPU")]
    [string]$Backend = "CUDA"
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectDir ".venv"

function Find-CompatiblePython {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($version in @("3.12", "3.11", "3.10")) {
            & py "-$version" -c "import sys; print(sys.executable)" *> $null
            if ($LASTEXITCODE -eq 0) {
                return @{ Command = "py"; Prefix = @("-$version") }
            }
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $minor = & python -c "import sys; print(sys.version_info.minor if sys.version_info.major == 3 else -1)"
        if ([int]$minor -ge 10 -and [int]$minor -le 12) {
            return @{ Command = "python"; Prefix = @() }
        }
    }
    throw "Python 3.10, 3.11, or 3.12 is required. Install Python 3.12 from python.org, then run setup again."
}

Set-Location $ProjectDir
$Python = Find-CompatiblePython
$PythonCommand = $Python.Command
$PythonPrefix = $Python.Prefix
Write-Host "Creating Doxa's private Python environment..." -ForegroundColor Cyan
& $PythonCommand @PythonPrefix -m venv $VenvDir
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $ProjectDir "requirements.txt")

switch ($Backend) {
    "CUDA"   { $WheelIndex = "https://abetlen.github.io/llama-cpp-python/whl/cu124" }
    "Vulkan" { $WheelIndex = "https://abetlen.github.io/llama-cpp-python/whl/vulkan" }
    "CPU"    { $WheelIndex = "https://abetlen.github.io/llama-cpp-python/whl/cpu" }
}

Write-Host "Installing the local AI engine ($Backend)..." -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade llama-cpp-python --extra-index-url $WheelIndex
if ($LASTEXITCODE -ne 0) {
    throw "The local model engine could not be installed. Try setup again and choose Vulkan; it is a good fallback on Windows."
}

if ($Backend -eq "CUDA") {
    Write-Host "Installing NVIDIA runtime libraries required by the CUDA engine..." -ForegroundColor Cyan
    & $VenvPython -m pip install --upgrade "nvidia-cuda-runtime-cu12==12.4.127" "nvidia-cublas-cu12==12.4.5.8"
    if ($LASTEXITCODE -ne 0) {
        throw "The NVIDIA runtime libraries could not be installed. Check the internet connection and run setup again."
    }
}

& $VenvPython (Join-Path $ProjectDir "verify_install.py")
if ($LASTEXITCODE -ne 0) {
    throw "Installation finished, but verification failed. Try the Vulkan option."
}

$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Doxa.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $ProjectDir "START_FORGEMIND.bat"
$Shortcut.WorkingDirectory = $ProjectDir
$Shortcut.Description = "Private local AI coding assistant"
$Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
$Shortcut.Save()
Write-Host "Desktop shortcut created: Doxa" -ForegroundColor Green
