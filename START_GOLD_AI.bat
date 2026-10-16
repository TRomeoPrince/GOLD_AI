@echo off
title GOLD_AI Owner Launcher
cd /d "%~dp0"

echo Starting GOLD_AI API watchdog...
start "GOLD_AI API WATCHDOG" cmd /k ".venv\Scripts\python -m server.api_watchdog"

echo Waiting for GOLD_AI API health...
powershell -NoProfile -Command "$ok=$false; for($i=0;$i -lt 30;$i++){ try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/health -TimeoutSec 2; if($r.StatusCode -eq 200){$ok=$true; break} } catch {}; Start-Sleep -Seconds 1 }; if(-not $ok){ exit 1 }"
if errorlevel 1 (
  echo ERROR: GOLD_AI API did not become healthy on port 8765.
  pause
  exit /b 1
)

echo Starting GOLD_AI signal engine...
start "GOLD_AI SIGNAL ENGINE" cmd /k ".venv\Scripts\python -m server.signal_engine"
timeout /t 2 /nobreak >nul

echo Starting hosted MT5 workers...
start "GOLD_AI HOSTED MT5" cmd /c ".venv\Scripts\python -m server.hosted_manager --start-all"
timeout /t 2 /nobreak >nul

echo Starting ngrok...
start "GOLD_AI NGROK" cmd /k "ngrok http --domain=grandpa-skier-sphere.ngrok-free.dev 8765"

echo.
echo GOLD_AI owner stack is online.
echo Local health:  http://127.0.0.1:8765/health
echo Public health: https://grandpa-skier-sphere.ngrok-free.dev/health
echo.
echo The API watchdog will restart the owner API if it crashes.
pause
