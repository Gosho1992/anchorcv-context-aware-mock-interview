# AnchorCV — backend startup script
# Run with: powershell.exe -ExecutionPolicy Bypass -File "C:\Users\SiliCon\Downloads\ANCHOR CV\start_backend.ps1"

$ErrorActionPreference = "Stop"

$ROOT     = "C:\Users\SiliCon\Downloads\ANCHOR CV"
$BACKEND  = Join-Path $ROOT "anchorcv-backend"
$VENVPY   = Join-Path $BACKEND ".venv\Scripts\python.exe"

Write-Host ""
Write-Host "=== Starting AnchorCV backend on port 8000 ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $VENVPY)) {
    Write-Host "ERROR: venv not found at: $VENVPY" -ForegroundColor Red
    Write-Host "Run setup_venv.ps1 first." -ForegroundColor Red
    exit 1
}

Write-Host "Backend root: $BACKEND" -ForegroundColor Green
Write-Host "Python:       $VENVPY" -ForegroundColor Green
Write-Host ""
Write-Host "Tip: open a SECOND PowerShell window to run curl tests against http://127.0.0.1:8000" -ForegroundColor Yellow
Write-Host "     Press Ctrl+C in THIS window to stop the backend." -ForegroundColor Yellow
Write-Host ""
Write-Host "Starting uvicorn ..." -ForegroundColor Cyan
Write-Host ""

Push-Location $BACKEND
try {
    & $VENVPY -m uvicorn app.main:app --port 8000
} finally {
    Pop-Location
}
