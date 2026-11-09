@echo off
setlocal
REM Runs outside AZT Mini after its trading workers and GUI exit.
timeout /t 5 /nobreak >nul
if exist "%~dp0unins000.exe" (
  "%~dp0unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
)
exit /b
