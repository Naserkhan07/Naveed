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
& $naveedBin --setup --force | Out-Null

Write-Host ""
Write-Host "Done. Start the companion with:"
Write-Host "  $naveedBin"
Write-Host ""
Write-Host "Naveed thinks with an LLM *API*: a URL and a model name. There is no key to"
Write-Host "paste anywhere - the starter config points at a local Ollama on this machine:"
Write-Host ""
Write-Host "  ollama serve   # then: ollama pull qwen2.5vl:7b     (the local default;"
Write-Host "                                                      nothing leaves your PC)"
Write-Host ""
Write-Host "Any other OpenAI-compatible API works too:"
Write-Host "  $naveedBin --api http://127.0.0.1:1234/v1 --model qwen2.5-vl-7b-instruct"
Write-Host "  $naveedBin --setup --provider openai   # a hosted one (LLM_TOKEN covers the"
Write-Host "                                         # rare gateway that insists)"
Write-Host "  $naveedBin --setup --provider ollama   # local, free, no token at all"
Write-Host ""
Write-Host "Prefer a text box, or no window at all? The same bot runs in your browser:"
Write-Host "  $naveedBin --serve                 # http://127.0.0.1:8765 (no PySide6 needed)"
Write-Host ""
Write-Host "Check everything at any time with:  $naveedBin --check"
