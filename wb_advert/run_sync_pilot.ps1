param(
    [switch]$ResolveNm,
    [switch]$ResolveOnly,
    [double]$Pause = 30,
    [int]$Limit = 0
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$ProbeEnv = Join-Path (Split-Path $Root -Parent) "wb_advert_probe\.env"
if (Test-Path $ProbeEnv) {
    Write-Host "Token: wb_advert_probe\.env (auto-loaded)"
}

$pyArgs = @("--pause", $Pause, "--max-retries", "2")
if ($ResolveNm) { $pyArgs += "--resolve-nm" }
if ($ResolveOnly) {
    $pyArgs += "--resolve-only"
    if ($Limit -le 0) { $Limit = 1 }
}
if ($Limit -gt 0) {
    $pyArgs += @("--limit", $Limit)
} elseif (-not $ResolveOnly -and -not $ResolveNm) {
    # sync: 1 campaign per run avoids 429
    $pyArgs += @("--limit", "1")
}
python -m scripts.sync_pilot @pyArgs
