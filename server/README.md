# GOLD_AI Owner Server

Runs on the owner's laptop. Core strategy logic stays private here.

Start locally:
```cmd
cd /d "C:\Users\USER\Desktop\Bots\Forex\AMD1" && .venv\Scripts\python -m pip install -r server\requirements.txt && .venv\Scripts\python -m uvicorn server.app:app --host 0.0.0.0 --port 8765
```

The customer clients connect to this server. Telegram onboarding uses @Princetradingbot.
