from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
HEALTH = "http://127.0.0.1:8765/health"


def healthy() -> bool:
    try:
        with urllib.request.urlopen(HEALTH, timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def start_api() -> subprocess.Popen:
    return subprocess.Popen(
        [
            str(PYTHON),
            "-m",
            "uvicorn",
            "server.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
        ],
        cwd=str(ROOT),
    )


def main() -> None:
    print("GOLD_AI API watchdog started.")
    process: subprocess.Popen | None = None

    while True:
        if healthy():
            time.sleep(5)
            continue

        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

        print("GOLD_AI API is offline. Starting/restarting it...")
        process = start_api()

        for _ in range(15):
            time.sleep(1)
            if healthy():
                print("GOLD_AI API healthy on http://127.0.0.1:8765")
                break
        else:
            print("GOLD_AI API did not become healthy; retrying.")

        time.sleep(2)


if __name__ == "__main__":
    main()
