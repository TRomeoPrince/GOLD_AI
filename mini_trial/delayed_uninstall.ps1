# Disclosed expiry self-cleanup. Never touches MetaTrader 5 or local trading records.
param(
    [Parameter(Mandatory=$true)][string]$Uninstaller,
    [Parameter(Mandatory=$true)][string]$ClientExe
)
$ErrorActionPreference = 'Stop'
Start-Sleep -Seconds 8  # Allow original EXE and batch helper to exit first.
if (-not (Test-Path -LiteralPath $Uninstaller -PathType Leaf)) { exit 0 }
# Don't interrupt a possible broker IPC/order submission or live UI.
# The scheduled task retries once the app has closed.
$active = Get-CimInstance Win32_Process -Filter "Name='AZT_Mini_Trial.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -eq $ClientExe }
if ($active) { exit 0 }
$p = Start-Process -FilePath $Uninstaller -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -Wait -PassThru -WindowStyle Hidden
exit $p.ExitCode
