from __future__ import annotations

import argparse

from .store import create_client, list_clients, set_status


def main() -> None:
    parser = argparse.ArgumentParser(description="GOLD_AI owner customer manager")
    sub = parser.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add")
    add.add_argument("--name", required=True)

    status = sub.add_parser("status")
    status.add_argument("--name", required=True)
    status.add_argument("--set", required=True, dest="new_status")

    sub.add_parser("list")

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


if __name__ == "__main__":
    main()
