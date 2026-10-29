# Compatibility shim — SignedDriver lives under Drivers\SignedDriver.
# Forwards to the canonical installer next to signeddrv.sys.
param(
    [ValidateSet("start", "stop", "remove", "status")]
    [string]$Action = "status",
    [string]$ServiceName = "WinNotify",
    [string]$DriverPath = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$canonical = Join-Path $root "Drivers\SignedDriver\load_signeddrv.ps1"
if (-not (Test-Path -LiteralPath $canonical)) {
    Write-Error "Canonical SignedDriver script missing: $canonical"
    exit 1
}
if ([string]::IsNullOrEmpty($DriverPath)) {
    $sys = Join-Path $root "Drivers\SignedDriver\signeddrv.sys"
    if (Test-Path -LiteralPath $sys) { $DriverPath = $sys }
}
& $canonical -Action $Action -ServiceName $ServiceName -DriverPath $DriverPath
exit $LASTEXITCODE
