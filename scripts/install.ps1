# Naveed installer for Windows (PowerShell).
#
#   iwr -useb https://raw.githubusercontent.com/Naserkhan07/Naveed/main/scripts/install.ps1 | iex
#
# Installs Naveed into ~\.naveed\venv so it never disturbs the system Python.
# Use -All to add the offline speech stack as well.
param(
  [switch]$All,
  [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$homeDir = if ($env:NAVEED_HOME) { $env:NAVEED_HOME } else { Join-Path $HOME ".naveed" }
$venv = Join-Path $homeDir "venv"
$naveedBin = Join-Path $venv "Scripts\naveed.exe"

Write-Host "Naveed installer"
Write-Host "  home: $homeDir"

& $Python -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Naveed needs Python 3.9 or newer" }

New-Item -ItemType Directory -Force -Path $homeDir | Out-Null
if (-not (Test-Path $venv)) {
  Write-Host "  creating virtual environment..."
  & $Python -m venv $venv
}

$pip = Join-Path $venv "Scripts\pip.exe"
Write-Host "  installing Naveed..."
& $pip install --quiet --upgrade pip
& $pip install --quiet "naveed[ui,capture,input]"
if ($All) {
  Write-Host "  installing the offline voice stack (this can take a while)..."
  & $pip install --quiet "naveed[voice]"
}

Write-Host "  writing a starter configuration..."
& $naveedBin --setup --force --provider openai | Out-Null

Write-Host ""
Write-Host "Done. Start the companion with:"
Write-Host "  $naveedBin"
Write-Host ""
Write-Host "Then open the panel's settings (the gear icon) and paste your model key,"
Write-Host "or point Naveed at a local model:"
Write-Host "  $naveedBin --setup --force --provider ollama"
Write-Host ""
Write-Host "Check everything at any time with:  $naveedBin --check"
