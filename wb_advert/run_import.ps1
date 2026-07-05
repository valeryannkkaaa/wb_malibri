# Run from anywhere - sets cwd to wb_advert
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$LocalEnv = Join-Path $Root ".env"
$ProbeEnv = Join-Path (Split-Path $Root -Parent) "wb_advert_probe\.env"

if (Test-Path $LocalEnv) {
    Write-Host "Token: wb_advert\.env"
} elseif (Test-Path $ProbeEnv) {
    Write-Host "Token: wb_advert_probe\.env (auto-loaded)"
} else {
    Copy-Item (Join-Path $Root ".env.example") $LocalEnv -ErrorAction SilentlyContinue
    Write-Warning "Add WB_API_TOKEN to wb_advert\.env or wb_advert_probe\.env"
}

python -m pip install -q -r requirements.txt
python -m scripts.import_pilot @args
