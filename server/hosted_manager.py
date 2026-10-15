from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .store import (
    hosted_account_for_client,
    list_hosted_accounts,
    set_hosted_runtime,
    set_hosted_account_status,
)


def project_root() -> Path:
    override = os.getenv("GOLD_AI_PROJECT_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    candidate = Path.home() / "Desktop" / "Bots" / "Forex" / "AMD1"
    if candidate.exists():
        return candidate
    return Path(__file__).resolve().parent.parent


def hosted_root() -> Path:
    root = project_root() / "server" / "hosted_mt5"
    root.mkdir(parents=True, exist_ok=True)
    return root


def provision_instance(client_id: int, base_terminal_exe: str) -> str:
    record = hosted_account_for_client(client_id)
    if not record:
        raise ValueError("Hosted account request not found.")
    if record["status"] not in {"APPROVED", "PROVISIONED", "FAILED"}:
        raise ValueError("Approve the hosted MT5 request before provisioning.")

    source_exe = Path(base_terminal_exe).expanduser().resolve()
    if not source_exe.exists():
        raise ValueError("Selected MT5 terminal executable does not exist.")

    source_dir = source_exe.parent
    target_dir = hosted_root() / f"client_{int(client_id)}"
    target_exe = target_dir / source_exe.name

    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)

    set_hosted_runtime(
        client_id,
        terminal_path=str(target_exe),
        worker_pid=None,
        last_error="",
    )
    set_hosted_account_status(client_id, "PROVISIONED")
    return str(target_exe)


def _python_exe() -> Path:
    py = project_root() / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        raise RuntimeError(f"Owner Python environment not found: {py}")
    return py


def _pid_alive(pid: int) -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {int(pid)}"],
        capture_output=True,
        text=True,
    )
    return str(int(pid)) in result.stdout


def worker_log_path(client_id: int) -> Path:
    log_dir = project_root() / "server" / "hosted_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"client_{int(client_id)}.log"


def start_worker(client_id: int) -> int:
    record = hosted_account_for_client(client_id)
    if not record:
        raise ValueError("Hosted account request not found.")
    terminal_path = str(record.get("terminal_path") or "")
    if not terminal_path or not Path(terminal_path).exists():
        raise ValueError("Hosted MT5 instance is not provisioned.")

    existing_pid = record.get("worker_pid")
    if existing_pid and _pid_alive(int(existing_pid)):
        return int(existing_pid)
    if existing_pid:
        set_hosted_runtime(client_id, worker_pid=None)

    # Clear the previous error BEFORE spawning. Do not clear it after spawn:
    # the child may fail immediately and write a useful error to the database.
    set_hosted_runtime(client_id, worker_pid=None, last_error="")

    log_path = worker_log_path(client_id)
    log_handle = open(log_path, "a", encoding="utf-8", buffering=1)
    log_handle.write("\n=== GOLD_AI hosted worker starting ===\n")

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [
            str(_python_exe()),
            "-m",
            "server.hosted_worker",
            "--client-id",
            str(int(client_id)),
        ],
        cwd=str(project_root()),
        creationflags=creationflags,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    log_handle.close()

    # Give very-early startup failures time to report themselves.
    import time
    time.sleep(0.75)
    if process.poll() is not None:
        record = hosted_account_for_client(client_id) or {}
        error = str(record.get("last_error") or "").strip()
        if not error:
            error = f"Hosted worker exited during startup. See {log_path}"
            set_hosted_runtime(client_id, worker_pid=None, last_error=error)
        raise RuntimeError(error)

    set_hosted_runtime(client_id, worker_pid=int(process.pid))
    return int(process.pid)


def stop_worker(client_id: int) -> None:
    record = hosted_account_for_client(client_id)
    if not record:
        raise ValueError("Hosted account request not found.")
    pid = record.get("worker_pid")
    if pid:
        subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            capture_output=True,
            text=True,
        )
    set_hosted_runtime(client_id, worker_pid=None)
    if record["status"] == "ACTIVE":
        set_hosted_account_status(client_id, "PROVISIONED")


def start_all() -> None:
    for row in list_hosted_accounts():
        if row["status"] in {"PROVISIONED", "ACTIVE"} and row.get("terminal_path"):
            try:
                start_worker(int(row["client_id"]))
            except Exception as exc:
                set_hosted_runtime(
                    int(row["client_id"]),
                    worker_pid=None,
                    last_error=str(exc),
                )
                set_hosted_account_status(int(row["client_id"]), "FAILED")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-all", action="store_true")
    parser.add_argument("--client-id", type=int)
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()

    if args.start_all:
        start_all()
        return
    if args.client_id and args.stop:
        stop_worker(args.client_id)
        return
    if args.client_id:
        print(start_worker(args.client_id))
        return
    parser.print_help()


if __name__ == "__main__":
    main()
