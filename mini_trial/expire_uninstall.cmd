@echo off
setlocal
REM The helper exits BEFORE the separate delayed uninstaller removes its files.
REM Owner databases, MT5 terminals and trading records are never deleted.
set "AZT_MINI_UNINSTALL=%~dp0unins000.exe"
start "" /b powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -Command "Start-Sleep -Seconds 8; if (Test-Path -LiteralPath $env:AZT_MINI_UNINSTALL) { Start-Process -FilePath $env:AZT_MINI_UNINSTALL -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -Wait }"
exit /b 0
