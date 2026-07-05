# Backfill keywords JSON for all pilot campaigns (--skip-existing skips done)
param(
    [double]$Pause = 90
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$syncDir = Join-Path (Split-Path $Root -Parent) "data\pilot\sync"
$done = @(Get-ChildItem -Path $syncDir -Filter "keywords_*.json" -ErrorAction SilentlyContinue).Count
Write-Host "Already saved: $done / 10 keyword files"
Write-Host "Pause between campaigns: ${Pause}s (increase if 429)`n"

$ids = @(
    33206346, 35110541, 35704170, 36713559, 37328842,
    31275686, 33206165, 31314341, 35098216, 37636194
)

foreach ($id in $ids) {
    Write-Host "--- advert $id ---"
    python -m scripts.backfill_keywords --advert-id $id --skip-existing --max-retries 2
    $code = $LASTEXITCODE
    if ($code -eq 2) {
        Write-Warning "429 at $id. Wait 15 min, then re-run: .\backfill_all.ps1"
        exit 1
    }
    if ($code -ne 0) {
        Write-Warning "Failed at $id (exit $code)"
        exit 1
    }
    Start-Sleep -Seconds $Pause
}

$done = @(Get-ChildItem -Path $syncDir -Filter "keywords_*.json").Count
Write-Host "`nDone: $done / 10 files. Dashboard: cd .. ; .\wb_advert\run_server.ps1"
