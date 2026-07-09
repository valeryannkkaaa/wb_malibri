# Daily pilot cycle: rotate sync → optimizer → parse all primary x regions → stocks
param(
    [double]$SyncPause = 8,
    [int]$ParseLimit = 0,
    [switch]$SkipParse,
    [switch]$SkipSync,
    [switch]$SkipStocks,
    [switch]$ForceParse
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
try { chcp 65001 | Out-Null } catch {}
$utf8 = [System.Text.Encoding]::UTF8
$OutputEncoding = $utf8
[Console]::OutputEncoding = $utf8

Write-Host "=== WB Advert daily cycle ===" -ForegroundColor Cyan

if (-not $SkipSync) {
    Write-Host "`n[1/5] Sync rotate (1 campaign + fullstats if due)..." -ForegroundColor Yellow
    python -m scripts.sync_pilot --rotate --pause $SyncPause --limit 1
}

Write-Host "`n[2/5] Optimizer (suggest-only)..." -ForegroundColor Yellow
python -m scripts.run_optimizer

if (-not $SkipParse) {
    $parseLabel = if ($ParseLimit -gt 0) { "$ParseLimit SKU" } else { "all primary x 3 regions" }
    Write-Host "`n[3/5] Parse positions ($parseLabel)..." -ForegroundColor Yellow
    $parseArgs = @("--all-regions", "--skip-fresh")
    if ($ParseLimit -gt 0) { $parseArgs += @("--limit", "$ParseLimit") }
    if ($ForceParse) { $parseArgs += "--force" }
    python -m scripts.parse_positions @parseArgs
}

if (-not $SkipStocks) {
    Write-Host "`n[4/5] Stocks report (skip if synced <24h)..." -ForegroundColor Yellow
    python -m scripts.sync_stocks
}

Write-Host "`n[5/5] Capture snapshots (memory)..." -ForegroundColor Yellow
python -m scripts.capture_snapshots

Write-Host "`nDone. Dashboard: http://127.0.0.1:8765" -ForegroundColor Green
