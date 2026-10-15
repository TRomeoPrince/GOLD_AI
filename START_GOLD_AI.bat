@echo off
title GOLD_AI Owner Launcher
cd /d "%~dp0"

echo Starting GOLD_AI owner server and signal engine...
start "GOLD_AI API" cmd /k ".venv\Scripts\python -m uvicorn server.app:app --host 127.0.0.1 --port 8765"
timeout /t 2 /nobreak >nul

start "GOLD_AI SIGNAL ENGINE" cmd /k ".venv\Scripts\python -m server.signal_engine"
timeout /t 2 /nobreak >nul

echo Starting hosted MT5 workers...
start "GOLD_AI HOSTED MT5" cmd /c ".venv\Scripts\python -m server.hosted_manager --start-all"
timeout /t 2 /nobreak >nul

echo Starting ngrok...
start "GOLD_AI NGROK" cmd /k "ngrok http --domain=grandpa-skier-sphere.ngrok-free.dev 8765"

echo.
echo GOLD_AI owner stack started.
echo Public endpoint: https://grandpa-skier-sphere.ngrok-free.dev
echo Keep these windows open while GOLD_AI is running.
pause
