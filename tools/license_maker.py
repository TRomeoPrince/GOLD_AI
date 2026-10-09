from __future__ import annotations

import argparse
import base64
import json
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives import serialization


def _canonical_payload(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def create_license(
    private_key_path: Path,
    output_path: Path,
    mt5_account: int,
    expires: date,
    customer: str,
) -> None:
    private_key = serialization.load_pem_private_key(
        private_key_path.read_bytes(),
        password=None,
    )
    payload = {
        "mt5_account": int(mt5_account),
        "expires": expires.isoformat(),
        "customer": customer.strip(),
    }
    signature = private_key.sign(_canonical_payload(payload))
    document = {
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    output_path.write_text(
        json.dumps(document, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _interactive() -> tuple[int, date, str]:
    print("=" * 36)
    print("       GOLD_AI LICENSE MAKER")
    print("=" * 36)
    account = int(input("MT5 Account Number: ").strip())
    expires = date.fromisoformat(input("Expiry Date (YYYY-MM-DD): ").strip())
    customer = input("Customer/Name (optional): ").strip()
    return account, expires, customer


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a signed GOLD_AI license.")
    parser.add_argument("--account", type=int)
    parser.add_argument("--expires", help="YYYY-MM-DD")
    parser.add_argument("--customer", default="")
    parser.add_argument("--key", default="GOLD_AI_OWNER_PRIVATE_KEY.pem")
    parser.add_argument("--output", default="license.gold")
    args = parser.parse_args()

    if args.account is None or not args.expires:
        account, expires, customer = _interactive()
    else:
        account = args.account
        expires = date.fromisoformat(args.expires)
        customer = args.customer

    key_path = Path(args.key)
    if not key_path.exists():
        raise SystemExit(
            f"Private signing key not found: {key_path}\n"
            "Keep GOLD_AI_OWNER_PRIVATE_KEY.pem beside the License Maker on the owner's PC only."
        )

    output = Path(args.output)
    create_license(key_path, output, account, expires, customer)
    print()
    print("LICENSE CREATED")
    print(f"Account : {account}")
    print(f"Expires : {expires.isoformat()}")
    print(f"Output  : {output.resolve()}")


if __name__ == "__main__":
    main()
