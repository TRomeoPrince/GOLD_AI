from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5

from .credential_vault import decrypt_secret
from .hosted_executor import execute_instruction
from .store import (
    acknowledge_instruction,
    client_by_id,
    effective_risk_policy,
    hosted_account_secret_for_client,
    next_instruction,
    set_hosted_account_status,
    set_hosted_runtime,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kill_terminal_by_path(terminal_path: Path) -> None:
    escaped = str(terminal_path).replace("'", "''")
    command = (
        "$target = '" + escaped + "'; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.ExecutablePath -eq $target } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
    )


def _launch_terminal(terminal_path: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [str(terminal_path), "/portable"],
        cwd=str(terminal_path.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _attach_mt5(terminal_path: Path) -> None:
    last_error = None
    for attempt in range(1, 4):
        mt5.shutdown()
        ok = mt5.initialize(
            str(terminal_path),
            timeout=120000,
            portable=True,
        )
        if ok:
            return
        last_error = mt5.last_error()
        time.sleep(5 * attempt)
    raise RuntimeError(f"MT5 IPC attach failed after 3 attempts: {last_error}")


def connect_mt5(client_id: int):
    set_hosted_account_status(client_id, "CONNECTING")
    set_hosted_runtime(
        client_id,
        last_error="",
        last_seen_utc=utc_now(),
        account_balance=None,
        account_equity=None,
    )
    hosted = hosted_account_secret_for_client(client_id)
    if not hosted:
        raise RuntimeError("Hosted MT5 account not found.")

    terminal_path = str(hosted.get("terminal_path") or "")
    if not terminal_path or not Path(terminal_path).exists():
        raise RuntimeError("Provisioned MT5 terminal was not found.")

    terminal = Path(terminal_path)

    # Force one clean hosted MT5 instance, then attach IPC before logging in.
    _kill_terminal_by_path(terminal)
    time.sleep(1)
    process = _launch_terminal(terminal)
    time.sleep(6)

    if process.poll() is not None:
        raise RuntimeError(
            f"Hosted MT5 terminal exited during startup with code {process.returncode}."
        )

    _attach_mt5(terminal)

    password = decrypt_secret(str(hosted["password_ciphertext"]))
    try:
        if not mt5.login(
            int(hosted["mt5_login"]),
            password=password,
            server=str(hosted["mt5_server"]),
            timeout=60000,
        ):
            raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")
    finally:
        password = ""

    account = mt5.account_info()
    if account is None:
        raise RuntimeError(f"MT5 account info unavailable: {mt5.last_error()}")
    if int(account.login) != int(hosted["mt5_login"]):
        raise RuntimeError(
            f"MT5 login mismatch: expected {hosted['mt5_login']}, got {account.login}"
        )
    return hosted, account


def run(client_id: int) -> None:
    try:
        hosted, account = connect_mt5(client_id)
        set_hosted_account_status(client_id, "ACTIVE")
        set_hosted_runtime(
            client_id,
            last_error="",
            last_seen_utc=utc_now(),
            account_balance=float(account.balance),
            account_equity=float(account.equity),
        )

        while True:
            client = client_by_id(client_id)
            if client is None:
                raise RuntimeError("Client record was removed.")
            if client.status != "ACTIVE":
                time.sleep(2)
                continue
            if client.execution_mode != "HOSTED":
                raise RuntimeError("Client execution mode is no longer HOSTED.")

            info = mt5.account_info()
            if info is None:
                raise RuntimeError(f"Lost MT5 connection: {mt5.last_error()}")

            set_hosted_runtime(
                client_id,
                last_seen_utc=utc_now(),
                account_balance=float(info.balance),
                account_equity=float(info.equity),
            )

            row = next_instruction(client_id)
            if row is None:
                time.sleep(2)
                continue

            payload = json.loads(str(row["payload_json"]))
            try:
                if str(payload.get("kind", "")).upper() == "TEST":
                    ack_status = "TEST_OK"
                    ack_message = str(
                        payload.get("message", "Hosted remote link test received.")
                    )
                else:
                    policy = effective_risk_policy(client)
                    result = execute_instruction(
                        payload,
                        policy["risk_per_trade_pct"],
                        policy["max_open_risk_pct"],
                        policy["max_daily_loss_pct"],
                        policy["daily_profit_target_enabled"],
                        policy["daily_profit_target_pct"],
                    )
                    ack_status = "EXECUTED" if result.sent else "REJECTED"
                    ack_message = (
                        f"{result.message} | ticket={result.ticket or '-'} "
                        f"| volume={result.volume} "
                        f"| risk={result.planned_risk_pct:.3f}% "
                        f"| portfolio_after={result.portfolio_after_pct:.3f}%"
                    )
            except Exception as exc:
                ack_status = "REJECTED"
                ack_message = f"HOSTED_EXECUTION_ERROR: {exc}"

            acknowledge_instruction(
                client_id,
                int(row["id"]),
                ack_status,
                ack_message,
            )

    except Exception as exc:
        set_hosted_runtime(
            client_id,
            worker_pid=None,
            last_error=str(exc),
            last_seen_utc=utc_now(),
        )
        try:
            set_hosted_account_status(client_id, "FAILED")
        except Exception:
            pass
        raise
    finally:
        mt5.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-id", type=int, required=True)
    args = parser.parse_args()
    run(args.client_id)


if __name__ == "__main__":
    main()
