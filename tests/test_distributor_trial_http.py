"""HTTP-level proof that server UTC expiry gates orders while allowing renewal."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from server import store, trial_licenses, app


class TrialHTTPEndpoints(unittest.TestCase):
    def test_expired_trial_denies_new_order_but_allows_payment_access(self):
        with tempfile.TemporaryDirectory() as root, patch.object(store, "DB_PATH", Path(root) / "owner.db"):
            client, pairing = store.create_client("TestDistributor")
            trial_licenses.issue(client.id)
            with TestClient(app.app) as http:
                response = http.post("/v1/client/authorize", json={
                    "pairing_code": pairing,
                    "mt5_login": 123456,
                    "mt5_server": "TestBroker",
                })
                self.assertEqual(response.status_code, 200, response.text)
                token = response.json()["session_token"]
                self.assertTrue(response.json()["allowed"])
                initial_end = trial_licenses.status(client.id)["expires_utc"]
                self.assertTrue(initial_end)
                with store.connect() as con:
                    con.execute("UPDATE azt_distributor_trials SET expires_utc=? WHERE client_id=?",
                                ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), client.id))
                headers = {
                    "Authorization": f"Bearer {token}",
                    "X-Client-Time": "2026-01-01T00:00:00Z",  # Ignored spoofed PC clock.
                }
                denied = http.get("/v1/instructions/next", headers=headers)
                self.assertEqual(denied.status_code, 403, denied.text)
                self.assertIn("TRIAL_EXPIRED", denied.json()["detail"])
                risk = http.get("/v1/client/risk-policy", headers=headers)
                self.assertEqual(risk.status_code, 403)
                payment = http.get("/v1/azt/payment-methods", headers=headers)
                self.assertEqual(payment.status_code, 200, payment.text)
                info = http.get("/v1/azt/overview", headers=headers)
                self.assertEqual(info.status_code, 200, info.text)
                self.assertEqual(info.json()["subscription_status"], "EXPIRED")
                self.assertEqual(info.json()["remaining_seconds"], 0)
                again = http.post("/v1/client/authorize", json={"pairing_code": pairing})
                self.assertFalse(again.json()["allowed"])
                self.assertEqual(trial_licenses.status(client.id)["activated_utc"] != "", True)


if __name__ == "__main__":
    unittest.main()
