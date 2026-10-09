from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization


PUBLIC_KEY_PEM = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAaVrTy4NLdd+xT+ifnTJgq0+nEUMoPvFAFmX8MNapxQM=\n-----END PUBLIC KEY-----"


@dataclass(frozen=True)
class LicenseInfo:
    mt5_account: int
    expires: date
    customer: str = ""


class LicenseError(RuntimeError):
    pass


def _canonical_payload(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_and_verify_license(path: str | Path, mt5_account: int) -> LicenseInfo:
    license_path = Path(path)
    if not license_path.exists():
        raise LicenseError(f"License file not found: {license_path}")

    try:
        document = json.loads(license_path.read_text(encoding="utf-8"))
        payload = document["payload"]
        signature = base64.b64decode(document["signature"], validate=True)
        account = int(payload["mt5_account"])
        expires = date.fromisoformat(str(payload["expires"]))
        customer = str(payload.get("customer", "")).strip()
    except Exception as exc:
        raise LicenseError("License file is malformed.") from exc

    public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode("ascii"))
    try:
        public_key.verify(signature, _canonical_payload(payload))
    except InvalidSignature as exc:
        raise LicenseError("License signature is invalid.") from exc

    if account != int(mt5_account):
        raise LicenseError(
            f"This license is for MT5 account {account}, not account {mt5_account}."
        )

    today_utc = datetime.now(timezone.utc).date()
    if today_utc > expires:
        raise LicenseError(f"License expired on {expires.isoformat()}.")

    return LicenseInfo(mt5_account=account, expires=expires, customer=customer)
