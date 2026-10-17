# Build portable Python (Windows embeddable package) into .\python\
# Usage (from project root):
#   powershell -ExecutionPolicy Bypass -File scripts\build_portable.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\build_portable.ps1 -Version 3.13.16
#
# Proxy: set HTTPS_PROXY / HTTP_PROXY env vars beforehand if needed.
# SSL verification is never disabled; if it fails, report the error.

param(
    [string]$Version = "3.13.16"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # much faster Invoke-WebRequest on PS 5.1
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root   = Split-Path -Parent $PSScriptRoot
$PyDir  = Join-Path $Root "python"
$Tmp    = Join-Path $Root "build_tmp"
$Zip    = Join-Path $Tmp "python-$Version-embed-amd64.zip"
$GetPip = Join-Path $Tmp "get-pip.py"
$Url    = "https://www.python.org/ftp/python/$Version/python-$Version-embed-amd64.zip"
$PyExe  = Join-Path $PyDir "python.exe"

# 1. Clean
if (Test-Path $PyDir) { Remove-Item $PyDir -Recurse -Force }
if (Test-Path $Tmp)   { Remove-Item $Tmp -Recurse -Force }
New-Item -ItemType Directory -Path $Tmp | Out-Null

# 2. Download & extract embeddable package
Write-Host "[1/4] Download $Url"
Invoke-WebRequest -Uri $Url -OutFile $Zip -UseBasicParsing
Write-Host ("      SHA256 " + (Get-FileHash $Zip -Algorithm SHA256).Hash)
Expand-Archive -Path $Zip -DestinationPath $PyDir

# 3. Edit python3XX._pth: add Lib\site-packages, enable import site
Write-Host "[2/4] Patch ._pth"
$Pth = Get-ChildItem $PyDir -Filter "python3*._pth" | Select-Object -First 1
$Lines = Get-Content $Pth.FullName | Where-Object { $_ -notmatch '^\s*#?\s*import site\s*$' }
$Lines += "Lib\site-packages"
$Lines += "import site"
Set-Content -Path $Pth.FullName -Value $Lines -Encoding Ascii

# 4. Install pip, then requirements (binary wheels only)
Write-Host "[3/4] Install pip"
Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip -UseBasicParsing
& $PyExe $GetPip --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "get-pip failed" }

Write-Host "[4/4] Install requirements.txt"
& $PyExe -m pip install --only-binary=:all: --no-warn-script-location -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Remove-Item $Tmp -Recurse -Force
& $PyExe -c "import sys, streamlit, openpyxl; print('ok', sys.version)"
