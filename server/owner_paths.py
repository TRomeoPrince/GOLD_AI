"""Resolve owner paths consistently across the launcher and service entry points."""

import os
import sys
from pathlib import Path


CHECKOUT = Path(__file__).resolve().parents[1]


def resolve_path(value, root):
    path = Path(os.path.expandvars(str(value))).expanduser()
    return (root / path).resolve()


def owner_home():
    explicit = os.getenv("GOLD_AI_HOME", "").strip()
    if explicit:
        return resolve_path(explicit, Path.cwd())
    override = os.getenv("GOLD_AI_DB_PATH", "").strip()
    if override and Path(os.path.expandvars(override)).expanduser().is_absolute():
        parent = resolve_path(override, Path.cwd()).parent
        return parent.parent if parent.name.lower() == "server" else parent

    appdata = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "GOLD_AI"
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates = (exe_dir, exe_dir.parent, Path.cwd(), appdata)
    else:
        candidates = (CHECKOUT, appdata)
    for root in candidates:
        if (root / "server/gold_ai_server.db").is_file():
            return root.resolve()
    for root in candidates:
        if (root / ".env").is_file() and (root / "server").is_dir():
            return root.resolve()
    return (appdata if getattr(sys, "frozen", False) else CHECKOUT).resolve()


def project_root(root):
    return resolve_path(os.getenv("GOLD_AI_PROJECT_ROOT", "").strip() or root, root)


def state_directory(root):
    return resolve_path(os.getenv("GOLD_AI_STATE_DIR", "").strip() or "server", root)


def database_path(root):
    value = os.getenv("GOLD_AI_DB_PATH", "").strip()
    return resolve_path(value, root) if value else state_directory(root) / "gold_ai_server.db"


def service_home():
    # A direct source import without configuration stays in its checkout.
    if os.getenv("GOLD_AI_HOME", "").strip() or getattr(sys, "frozen", False):
        return owner_home()
    return CHECKOUT
