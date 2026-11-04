"""Owner-issued distributor trial leases; all timestamps are server-side UTC.

This entitlement is deliberately separate from AZT paid subscriptions.
Its gates apply at the server before any fresh client-PC order is issued.
It is never checked using a client-supplied time or a client-held secret.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone


def _now(now=None):
    value = now if now is not None else datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("Trial timestamps must be timezone-aware UTC.")
    return value.astimezone(timezone.utc)


def issue(client_id: int, days: int = 30):
    """Issue once; repeated issuance cannot silently reset the deadline."""
    from . import azt_store
    days = int(days)
    if days != 30:
        raise ValueError("Distributor edition is fixed to 30 days.")
    with azt_store._db() as con:
        con.execute("BEGIN IMMEDIATE")
        client = azt_store._client_row(con, client_id)
        if client["execution_mode"] != "CLIENT_PC":
            raise ValueError("Set this client to PC Client mode before issuing a distributor trial.")
        base = azt_store._base_subscription_summary(con, client_id, _now())
        if base["allowed"] and base["subscription"]["access_kind"] == "PAID":
            raise ValueError("This client already has an active paid subscription.")
        if con.execute("SELECT client_id FROM azt_distributor_trials WHERE client_id=?", (client_id,)).fetchone():
            raise ValueError("This client has already been issued a distributor trial.")
        con.execute("""INSERT INTO azt_distributor_trials
            (client_id,days,created_utc,activated_utc,expires_utc,revoked_utc,converted_utc)
            VALUES(?,30,?,'','','','')""", (client_id, _now().isoformat()))
    return {"client_id": client_id, "state": "PENDING_FIRST_PAIR", "days": days}


def activate(con, client_id: int, now=None):
    """Invoked on valid pairing; exactly one activation wins a database race."""
    current = _now(now)
    row = con.execute("SELECT * FROM azt_distributor_trials WHERE client_id=?", (client_id,)).fetchone()
    if row is None:
        return None
    if row["converted_utc"] or row["revoked_utc"]:
        return dict(row)
    if not row["activated_utc"]:
        con.execute("""UPDATE azt_distributor_trials
            SET activated_utc=?, expires_utc=?
            WHERE client_id=? AND activated_utc='' AND revoked_utc='' AND converted_utc=''""",
            (current.isoformat(), (current + timedelta(days=int(row["days"]))).isoformat(), client_id))
        row = con.execute("SELECT * FROM azt_distributor_trials WHERE client_id=?", (client_id,)).fetchone()
    return dict(row)


def apply_access(con, client_id: int, summary: dict, now=None):
    """Cap an individual trial client, without affecting normal subscriptions."""
    row = con.execute("SELECT * FROM azt_distributor_trials WHERE client_id=?", (client_id,)).fetchone()
    if row is None:
        return summary
    if row["converted_utc"]:
        if summary["subscription"]["access_kind"] == "PAID" or not summary["allowed"]:
            return summary
        return {**summary, "allowed": False, "effective_status": "PAYMENT_REQUIRED",
                "reason": "DISTRIBUTOR_TRIAL_CONVERTED_PAYMENT_REQUIRED"}
    current = _now(now)
    trial = dict(row)
    client = con.execute("SELECT status, execution_mode FROM clients WHERE id=?", (client_id,)).fetchone()
    expires = datetime.fromisoformat(trial["expires_utc"]) if trial["expires_utc"] else None
    if trial["revoked_utc"]:
        status, remaining, valid = "REVOKED", 0, False
    elif expires is None:
        status, remaining, valid = "PENDING_ACTIVATION", 0, False
    else:
        valid = current < expires
        remaining = max(0, int((expires - current).total_seconds()))
        status = "TRIAL" if valid else "EXPIRED"
    if client["status"] != "ACTIVE":
        status, valid = str(client["status"]), False
    elif client["execution_mode"] != "CLIENT_PC":
        status, valid = "CLIENT_PC_REQUIRED", False
    summary = dict(summary)
    subscription = dict(summary["subscription"])
    subscription.update(plan_code="DISTRIBUTOR_TRIAL", status=status,
                        starts_utc=trial["activated_utc"],
                        expires_utc=trial["expires_utc"], access_kind="DISTRIBUTOR_TRIAL")
    summary.update(subscription=subscription,
                   allowed=valid,
                   effective_status=status,
                   remaining_seconds=remaining,
                   reason="OK" if valid else "DISTRIBUTOR_TRIAL_" + status,
                   distributor_trial=True)
    return summary


def change(client_id, action: str):
    from . import azt_store
    action = action.lower()
    if action not in {"revoke", "convert"}:
        raise ValueError("Unknown action.")
    with azt_store._db() as con:
        con.execute("BEGIN IMMEDIATE")
        field = "revoked_utc" if action == "revoke" else "converted_utc"
        # Conversion lifts the separate distributor cap but DOES NOT activate a
        # paid subscription. Owner must separately approve/renew paid access.
        updated = con.execute(f"UPDATE azt_distributor_trials SET {field}=? WHERE client_id=? AND {field}=''",
                              (_now().isoformat(), client_id)).rowcount
        if not updated:
            raise ValueError("No change made; trial absent or already processed.")
    return {"client_id": client_id, "state": action.upper()}


def status(client_id):
    from . import azt_store
    with azt_store._db() as con:
        row = con.execute("SELECT * FROM azt_distributor_trials WHERE client_id=?", (client_id,)).fetchone()
        return dict(row) if row is not None else None


def main():
    parser = argparse.ArgumentParser(description="Local owner-only AZT 30-day distributor trial administration")
    parser.add_argument("action", choices=("issue","revoke","convert","status"))
    parser.add_argument("--client-id", type=int, required=True)
    options = parser.parse_args()
    if options.client_id < 1:
        parser.error("Client ID must be positive.")
    result = issue(options.client_id) if options.action == "issue" else (
        status(options.client_id) if options.action == "status" else change(options.client_id, options.action))
    print(result)


if __name__ == "__main__":
    main()
