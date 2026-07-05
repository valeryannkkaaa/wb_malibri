param(
    [Parameter(Mandatory = $true)]
    [int]$AdvertId
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$ProbeEnv = Join-Path (Split-Path $Root -Parent) "wb_advert_probe\.env"
if (-not (Test-Path (Join-Path $Root ".env")) -and (Test-Path $ProbeEnv)) {
    Write-Host "Token: wb_advert_probe\.env (auto-loaded)"
}

python -m scripts.sync_once --advert-id $AdvertId
