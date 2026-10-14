# ============================================================================
# load_signeddrv.ps1 - Install / Start / Stop / Remove the signeddrv kernel driver
#
# signeddrv.sys (Windows-Memory-Informer / "WinNotify") is a Microsoft-signed
# memory driver that exposes a PER-PROCESS VIRTUAL-memory read/write primitive
# and kernel-level process discovery. Because it is signed, it loads without
# requiring Microsoft Defender to allow it (unlike Tencent KSLD / MpKslDrv).
#
# Usage (run as Administrator):
#   powershell -ExecutionPolicy Bypass -File load_signeddrv.ps1 -Action start
#   powershell -ExecutionPolicy Bypass -File load_signeddrv.ps1 -Action stop
#   powershell -ExecutionPolicy Bypass -File load_signeddrv.ps1 -Action remove
#
# Place signeddrv.sys in the same folder as this script, or pass:
#   -DriverPath "C:\path\to\signeddrv.sys"
# ============================================================================

param(
    [ValidateSet("start", "stop", "remove", "status")]
    [string]$Action = "status",
    [string]$ServiceName = "WinNotify",
    [string]$DriverPath = ""
)

$ErrorActionPreference = "Stop"

# Resolve the driver binary path if not supplied.
if ([string]::IsNullOrEmpty($DriverPath)) {
    $candidates = @("signeddrv.sys")
    foreach ($name in $candidates) {
        $s = Get-ChildItem -Path $PSScriptRoot -Filter $name -ErrorAction SilentlyContinue
        if ($s) {
            $DriverPath = $s.FullName
            break
        }
    }
}

if (-not [string]::IsNullOrEmpty($DriverPath)) {
    $DriverPath = (Resolve-Path $DriverPath).Path
}

function Get-ServiceState {
    try {
        $svc = Get-Service -Name $ServiceName -ErrorAction Stop
        return $svc.Status
    } catch {
        return "NotInstalled"
    }
}

switch ($Action) {
    "status" {
        "WinNotify service state: $(Get-ServiceState)"
    }

    "start" {
        if ([string]::IsNullOrEmpty($DriverPath)) {
            "ERROR: signeddrv.sys not found next to this script. Pass -DriverPath."
            exit 1
        }
        $state = Get-ServiceState
        if ($state -eq "Running") {
            "WinNotify is already running."
        } elseif ($state -eq "NotInstalled") {
            "Creating service '$ServiceName' -> $DriverPath"
            Copy-Item -Path $DriverPath -Destination "C:\Windows\System32\drivers\$($ServiceName).sys" -Force
            # Use sc.exe create (works on all PowerShell versions) for a kernel driver.
            sc.exe create $ServiceName type= kernel start= demand `
                binPath= "C:\Windows\System32\drivers\$($ServiceName).sys" `
                DisplayName= "WinNotify Memory Driver (signeddrv)" | Out-Null
            "Starting service '$ServiceName'"
            Start-Service -Name $ServiceName
            "WinNotify started."
        } else {
            "Starting service '$ServiceName'"
            Start-Service -Name $ServiceName
            "WinNotify started."
        }
    }

    "stop" {
        $state = Get-ServiceState
        if ($state -eq "Running") {
            Stop-Service -Name $ServiceName -Force
            "WinNotify stopped."
        } else {
            "WinNotify is not running (state: $state)."
        }
    }

    "remove" {
        $state = Get-ServiceState
        if ($state -ne "NotInstalled") {
            if ($state -eq "Running") {
                Stop-Service -Name $ServiceName -Force
            }
            sc.exe delete $ServiceName | Out-Null
            $sys = "C:\Windows\System32\drivers\$($ServiceName).sys"
            if (Test-Path $sys) {
                Remove-Item -Path $sys -Force
            }
            "WinNotify service removed."
        } else {
            "WinNotify service is not installed."
        }
    }
}
