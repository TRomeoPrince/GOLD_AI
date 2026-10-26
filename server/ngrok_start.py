"""Start shared ngrok without making it part of Admin service lifetime."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path


def start_ngrok(logs: Path, port: int) -> str:
    # Reuse an existing agent, even if its tunnel belongs to another project.
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as response:
            tunnels = json.load(response).get("tunnels", [])
        matches = [t.get("public_url", "") for t in tunnels if str(port) in str(t.get("config", {}).get("addr", ""))]
        if matches:
            return "ngrok is already running: " + ", ".join(matches)
        return "ngrok is already running, but has no tunnel to this API port. Add GOLD_AI to its shared config and restart that agent."
    except (OSError, ValueError):
        pass
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    powershell = shutil.which("powershell.exe")
    if powershell:
        result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command",
            "$ErrorActionPreference='Stop'; $t=Get-ScheduledTask -TaskName 'Shared-ngrok' -ErrorAction SilentlyContinue; if($null -eq $t){exit 3}; Start-ScheduledTask -TaskName 'Shared-ngrok'"],
            capture_output=True, text=True, creationflags=flags, timeout=15)
        if result.returncode == 0:
            return "Shared-ngrok startup requested. Tunnel status will update shortly."
        if result.returncode != 3:
            raise RuntimeError("Could not start Shared-ngrok task. Check its permissions in Task Scheduler; use the elevated setup instructions if needed.")
    exe = os.getenv("GOLD_AI_NGROK_EXE", "").strip() or shutil.which("ngrok.exe")
    if not exe or not Path(exe).is_file():
        raise RuntimeError("ngrok was not found. Install ngrok or set GOLD_AI_NGROK_EXE in .env.")
    config = os.getenv("GOLD_AI_NGROK_CONFIG", "").strip()
    if config:
        if not Path(config).is_file():
            raise RuntimeError("GOLD_AI_NGROK_CONFIG does not point to an existing config file.")
        args = [exe, "start", "--all", "--config", config]
    else:
        url = os.getenv("GOLD_AI_NGROK_URL", "https://grandpa-skier-sphere.ngrok-free.dev")
        args = [exe, "http", "--url", url, str(port)]
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / "ngrok.log", "ab", buffering=0) as log:
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=flags | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0), close_fds=True)
    # This agent is intentionally not registered with Services.stop().
    return f"ngrok starting independently (PID {process.pid}); see ngrok.log if no tunnel appears."
