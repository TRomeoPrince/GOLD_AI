from __future__ import annotations

import argparse

import json
from datetime import datetime, timezone

from .store import (
    client_by_name,
    create_client,
    enqueue_instruction,
    list_clients,
    set_status,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="GOLD_AI owner customer manager")
    sub = parser.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add")
    add.add_argument("--name", required=True)

    status = sub.add_parser("status")
    status.add_argument("--name", required=True)
    status.add_argument("--set", required=True, dest="new_status")

    sub.add_parser("list")

    test = sub.add_parser("test")
    test.add_argument("--name", required=True)

    args = parser.parse_args()

    if args.cmd == "add":
        client, code = create_client(args.name)
        print(f"Created : {client.name}")
        print(f"Status  : {client.status}")
        print(f"Pairing : {code}")
    elif args.cmd == "status":
        set_status(args.name, args.new_status)
        print(f"{args.name} -> {args.new_status.upper()}")
    elif args.cmd == "list":
        rows = list_clients()
        if not rows:
            print("No clients yet.")
        for row in rows:
            print(
                f"{row.id:03d}  {row.name:<20} {row.status:<8} "
                f"MT5={row.mt5_login or '-'}@{row.mt5_server or '-'} "
                f"TG=@{row.telegram_username or '-'}"
            )
    elif args.cmd == "test":
        client = client_by_name(args.name)
        if client is None:
            raise SystemExit(f"Unknown client: {args.name}")
        key = f"TEST|{args.name}|{datetime.now(timezone.utc).isoformat()}"
        payload = json.dumps({
            "kind": "TEST",
            "message": "GOLD_AI remote link test",
        })
        ok = enqueue_instruction(client.id, key, payload)
        print(f"Queued test for {client.name}: {'OK' if ok else 'DUPLICATE'}")


if __name__ == "__main__":
    main()
