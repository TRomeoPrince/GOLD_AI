@echo off
setlocal
cd /d "%~dp0\.."

start "GOLD_AI API" cmd /k ".venv\Scripts\python -m uvicorn server.app:app --host 127.0.0.1 --port 8765"
timeout /t 2 /nobreak >nul
start "GOLD_AI SIGNAL ENGINE" cmd /k ".venv\Scripts\python -m server.signal_engine"
start "GOLD_AI CLIENT TELEGRAM" cmd /k ".venv\Scripts\python -m server.client_telegram"

echo GOLD_AI owner server + signal engine + client Telegram bot started.
echo Public tunnel should forward port 8765.
