from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5

from .credential_vault import decrypt_secret
from .hosted_executor import execute_instruction
from .store import (
    acknowledge_instruction,
    client_by_id,
    hosted_account_secret_for_client,
    next_instruction,
    set_hosted_account_status,
    set_hosted_runtime,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_mt5(client_id: int):
    hosted = hosted_account_secret_for_client(client_id)
    if not hosted:
        raise RuntimeError("Hosted MT5 account not found.")

    terminal_path = str(hosted.get("terminal_path") or "")
    if not terminal_path or not Path(terminal_path).exists():
        raise RuntimeError("Provisioned MT5 terminal was not found.")

    password = decrypt_secret(str(hosted["password_ciphertext"]))
    ok = mt5.initialize(
        terminal_path,
        login=int(hosted["mt5_login"]),
        password=password,
        server=str(hosted["mt5_server"]),
        timeout=60000,
        portable=True,
    )
    password = ""
    if not ok:
        raise RuntimeError(f"MT5 initialize/login failed: {mt5.last_error()}")

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
                    result = execute_instruction(
                        payload,
                        client.risk_per_trade_pct,
                        client.max_open_risk_pct,
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
