@echo off
setlocal
REM Runs outside AZT Mini after its trading workers and GUI exit.
powershell.exe -NoProfile -NonInteractive -Command "Start-Sleep -Seconds 5" >nul
if exist "%~dp0unins000.exe" (
  "%~dp0unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
)
exit /b
