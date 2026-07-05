# WB advert-api connectivity check
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
python -m scripts.check_api
