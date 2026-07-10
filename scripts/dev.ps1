# UA dev launcher (specs/16 §4): starts backend (uvicorn :8000) and
# frontend (next dev :3000) in two windows, then opens the workbench.
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

# stamp the code SHA into the environment for decision snapshots (HR-7)
$sha = (git -C $repo rev-parse --short HEAD 2>$null); if (-not $sha) { $sha = "dev" }

foreach ($port in 8000, 3000) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conns) {
        Write-Host "Port $port busy - stopping existing listener..." -ForegroundColor Yellow
        $conns | Select-Object -ExpandProperty OwningProcess -Unique |
            ForEach-Object { Stop-Process -Id $_ -Force -Confirm:$false }
        Start-Sleep -Seconds 1
    }
}

if (-not (Test-Path "$repo\backend\.venv\Scripts\python.exe")) {
    Write-Host "Backend venv missing. Create it first:" -ForegroundColor Red
    Write-Host "  cd backend; uv venv --python 3.12 .venv; uv pip install --python .venv\Scripts\python.exe -r requirements.txt"
    exit 1
}
if (-not (Test-Path "$repo\frontend\node_modules")) {
    Write-Host "Frontend deps missing. Run: cd frontend; npm install" -ForegroundColor Red
    exit 1
}

Write-Host "Starting backend on http://localhost:8000 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "`$env:CODE_GIT_SHA='$sha'; Set-Location '$repo\backend'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"

Write-Host "Starting frontend on http://localhost:3000 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "Set-Location '$repo\frontend'; npm run dev"

Start-Sleep -Seconds 5
Write-Host ""
Write-Host "UA workbench:  http://localhost:3000  (redirects to /pipeline)" -ForegroundColor Green
Write-Host "Backend API:   http://localhost:8000/loans" -ForegroundColor Green
Start-Process "http://localhost:3000"
