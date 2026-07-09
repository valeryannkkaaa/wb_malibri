# Register Windows Task Scheduler job for WB Advert pilot (every 15 min)
param(
    [int]$IntervalMinutes = 15,
    [string]$TaskName = "WBAdvertPilotCycle",
    [switch]$Unregister
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$CycleScript = Join-Path $Root "run_daily_cycle.ps1"
$LogDir = Join-Path (Split-Path $Root -Parent) "data\pilot\logs"
if (-not (Test-Path -Path $LogDir)) {
    $null = [System.IO.Directory]::CreateDirectory($LogDir)
}
$AppDataLogDir = Join-Path $env:LOCALAPPDATA "WBAdvert\logs"

if ($Unregister) {
    schtasks /Delete /TN $TaskName /F 2>$null
    Write-Host "Removed task: $TaskName"
    exit 0
}

if (-not (Test-Path $CycleScript)) {
    Write-Error "Missing $CycleScript"
    exit 1
}

$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) {
    Write-Error "python not found in PATH"
    exit 1
}

# Wrapper is run_daily_cycle_scheduled.ps1 (committed)
$Wrapper = Join-Path $Root "run_daily_cycle_scheduled.ps1"
$Action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Wrapper`""
schtasks /Delete /TN $TaskName /F 2>$null | Out-Null
schtasks /Create /TN $TaskName /TR $Action /SC MINUTE /MO $IntervalMinutes /F | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Error "schtasks failed (exit $LASTEXITCODE). Run PowerShell as Administrator or create task manually."
    exit 1
}

Write-Host "Scheduled task created: $TaskName"
Write-Host "  Every: $IntervalMinutes minute(s)"
Write-Host "  Runs:  $Wrapper"
Write-Host "  Logs:  $LogDir\cycle_YYYY-MM-DD.log"
Write-Host "         (fallback: $AppDataLogDir if project folder is not writable)"
Write-Host ""
Write-Host "Test now:  schtasks /Run /TN $TaskName"
Write-Host "Remove:    .\install_scheduled_task.ps1 -Unregister"
