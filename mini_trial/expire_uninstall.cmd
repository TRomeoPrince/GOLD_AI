@echo off
setlocal
REM The helper exits before the separate delayed uninstaller removes its files.
REM Never kill an MT5 terminal or delete broker/strategy execution history.
set "AZT_MINI_UNINSTALL=%~dp0unins000.exe"
set "AZT_MINI_CLIENT=%~dp0AZT_Mini_Trial.exe"
set "AZT_MINI_HELPER=%~dp0delayed_uninstall.ps1"
if not exist "%AZT_MINI_UNINSTALL%" exit /b 2
if not exist "%AZT_MINI_HELPER%" exit /b 2
start "" /b powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy RemoteSigned -File "%AZT_MINI_HELPER%" -Uninstaller "%AZT_MINI_UNINSTALL%" -ClientExe "%AZT_MINI_CLIENT%"
exit /b 0
