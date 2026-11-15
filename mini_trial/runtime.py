"""Dedicated Mini-only state: never use the Owner's DB or credentials."""
import os
from pathlib import Path

def configure(home=None):
    root = Path(home) if home is not None else Path(os.environ.get("LOCALAPPDATA",str(Path.home()))) / "AZT_Mini_14Day_Trial"
    root = root.resolve()
    (root/"state").mkdir(parents=True, exist_ok=True)
    (root/"logs").mkdir(parents=True, exist_ok=True)
    os.environ.update(
        GOLD_AI_HOME=str(root),
        GOLD_AI_PROJECT_ROOT=str(root),
        GOLD_AI_STATE_DIR=str(root/"state"),
        GOLD_AI_DB_PATH=str(root/"state"/"gold_ai_server.db"),
        AZT_MINI_TRIAL="1",
        AZT_EXTERNAL_TELEGRAM="false",
        GOLD_AI_AI_MODE="OFF")
    for name in ("GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN","GOLD_AI_OWNER_TELEGRAM_BOT_TOKEN","AZT_TELEGRAM_SOURCE_ROOT","GOLD_AI_API_TOKEN"):
        os.environ.pop(name,None)
    os.chdir(root)
    return root
