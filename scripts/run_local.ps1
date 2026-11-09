# Windows PowerShell:  .\scripts\run_local.ps1   ->  http://127.0.0.1:8000
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\Activate.ps1
pip install --quiet -r backend\requirements.txt
if (-not (Test-Path frontend\dist\index.html)) {
  if (Get-Command npm -ErrorAction SilentlyContinue) { Push-Location frontend; npm install --no-audit --no-fund; npm run build; Pop-Location }
  else { Write-Warning "npm not found: dashboard will not be served." }
}
$root = (Get-Location).Path
$env:FRONTEND_DIST = Join-Path $root "frontend\dist"
$env:DATA_DIR = Join-Path $root "data"
$env:MODEL_DIR = Join-Path $root "models"
$env:MODEL_WEIGHTS_PATH = Join-Path $root "models\best.onnx"
Set-Location backend
Write-Host "Dashboard: http://127.0.0.1:8000   API docs: http://127.0.0.1:8000/docs"
uvicorn app.main:app --host 127.0.0.1 --port 8000
