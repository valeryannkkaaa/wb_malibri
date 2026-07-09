param(
    [int]$Port = 0
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Parent = Split-Path $Root -Parent
Set-Location $Parent

python -m pip install -q -r (Join-Path $Root "requirements.txt")

if ($Port -le 0) {
    foreach ($p in 8765, 8766, 8767, 8088) {
        $inUse = netstat -ano | Select-String "127.0.0.1:$p\s+.*LISTENING"
        if (-not $inUse) { $Port = $p; break }
    }
    if ($Port -le 0) { $Port = 8765 }
}

$inUse = netstat -ano | Select-String "127.0.0.1:$Port\s+.*LISTENING"
if ($inUse) {
    Write-Warning "Port $Port busy. Use: .\wb_advert\run_server.ps1 -Port 8766"
    exit 1
}

Write-Host "Advert dashboard: http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "  /  or  /advert  — главная" -ForegroundColor DarkGray
Write-Host "  /advert/decisions — audit log" -ForegroundColor DarkGray
python -m uvicorn wb_advert.app:app --host 127.0.0.1 --port $Port --reload
