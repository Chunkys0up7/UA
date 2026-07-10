# =============================================================================
# Dev runner (Windows PowerShell)
# Starts the FastAPI backend and the Next.js frontend in two child processes.
# Ctrl+C stops both.
# =============================================================================

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

Write-Host "Starting backend (uvicorn :8000)..." -ForegroundColor Cyan
$be = Start-Process -FilePath "powershell" `
  -ArgumentList "-NoExit","-Command","cd '$backend'; uvicorn app.main:app --reload --port 8000" `
  -PassThru -WindowStyle Normal

Write-Host "Starting frontend (next dev :3000)..." -ForegroundColor Cyan
$fe = Start-Process -FilePath "powershell" `
  -ArgumentList "-NoExit","-Command","cd '$frontend'; npm run dev" `
  -PassThru -WindowStyle Normal

Write-Host ""
Write-Host "Backend  : http://localhost:8000   (PID $($be.Id))"
Write-Host "Frontend : http://localhost:3000   (PID $($fe.Id))"
Write-Host ""
Write-Host "Press Ctrl+C to stop both."

try {
  Wait-Process -Id $be.Id, $fe.Id
} finally {
  if (-not $be.HasExited) { Stop-Process -Id $be.Id -Force }
  if (-not $fe.HasExited) { Stop-Process -Id $fe.Id -Force }
}
