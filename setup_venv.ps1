# AnchorCV — venv setup script
# Run with: powershell.exe -ExecutionPolicy Bypass -File "C:\Users\SiliCon\Downloads\ANCHOR CV\setup_venv.ps1"

$ErrorActionPreference = "Stop"

$ROOT     = "C:\Users\SiliCon\Downloads\ANCHOR CV"
$BACKEND  = Join-Path $ROOT "anchorcv-backend"
$VENV     = Join-Path $BACKEND ".venv"
$REQS     = Join-Path $ROOT "requirements.txt"
$VENVPY   = Join-Path $VENV "Scripts\python.exe"

Write-Host ""
Write-Host "=== AnchorCV venv setup ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: verify py launcher works
Write-Host "[1/6] Checking Python 3.12 ..." -ForegroundColor Yellow
$pyVersion = & py -3.12 --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: py -3.12 failed. Output: $pyVersion" -ForegroundColor Red
    Write-Host "Install Python 3.12 first via: winget install --id Python.Python.3.12" -ForegroundColor Red
    exit 1
}
Write-Host "  Found: $pyVersion" -ForegroundColor Green

# Step 2: confirm backend directory exists
Write-Host ""
Write-Host "[2/6] Checking project layout ..." -ForegroundColor Yellow
if (-not (Test-Path $BACKEND)) {
    Write-Host "ERROR: Backend directory not found: $BACKEND" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $REQS)) {
    Write-Host "ERROR: requirements.txt not found at: $REQS" -ForegroundColor Red
    exit 1
}
Write-Host "  Backend: $BACKEND" -ForegroundColor Green
Write-Host "  Requirements: $REQS" -ForegroundColor Green

# Step 3: delete old venv if it exists
Write-Host ""
Write-Host "[3/6] Removing old venv (if any) ..." -ForegroundColor Yellow
if (Test-Path $VENV) {
    Remove-Item -Recurse -Force $VENV
    Write-Host "  Old venv deleted." -ForegroundColor Green
} else {
    Write-Host "  No old venv found." -ForegroundColor Green
}

# Step 4: create fresh venv with --copies
Write-Host ""
Write-Host "[4/6] Creating new venv (with --copies) ..." -ForegroundColor Yellow
Push-Location $BACKEND
try {
    & py -3.12 -m venv .venv --copies
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: venv creation failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "  New venv created at: $VENV" -ForegroundColor Green
} finally {
    Pop-Location
}

if (-not (Test-Path $VENVPY)) {
    Write-Host "ERROR: venv python.exe missing after creation: $VENVPY" -ForegroundColor Red
    exit 1
}

# Step 5: upgrade pip + install requirements
Write-Host ""
Write-Host "[5/6] Installing dependencies (this takes 2-5 minutes) ..." -ForegroundColor Yellow
& $VENVPY -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pip upgrade failed." -ForegroundColor Red
    exit 1
}
& $VENVPY -m pip install -r $REQS
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pip install failed. See output above." -ForegroundColor Red
    exit 1
}
Write-Host "  Dependencies installed." -ForegroundColor Green

# Step 6: verify imports
Write-Host ""
Write-Host "[6/6] Verifying imports ..." -ForegroundColor Yellow
$verifyOutput = & $VENVPY -c "import fastapi, uvicorn, openai, supabase; print('OK')" 2>&1
if ($LASTEXITCODE -ne 0 -or $verifyOutput -notmatch "OK") {
    Write-Host "ERROR: import verification failed. Output: $verifyOutput" -ForegroundColor Red
    exit 1
}
Write-Host "  All required modules import cleanly." -ForegroundColor Green

# Done
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "DONE. venv is ready at: $VENV" -ForegroundColor Green
Write-Host ""
Write-Host "Next step: start the backend by running:" -ForegroundColor Cyan
Write-Host "  powershell.exe -ExecutionPolicy Bypass -File `"$ROOT\start_backend.ps1`"" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
