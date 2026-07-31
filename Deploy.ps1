# Thin wrapper so deployment can be started from the repository root.
& (Join-Path $PSScriptRoot 'scripts/Deploy-CloudInventoryDiscovery.ps1') @args
if (-not $?) {
    exit 1
}
exit 0
