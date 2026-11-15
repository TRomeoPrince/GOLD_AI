"""One-time 30-day distributor trial: owner clock and server-side instruction gate."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from server import azt_store, store, trial_licenses


class DistributorTrialsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dbpatch = patch.object(store, "DB_PATH", Path(self.tmp.name) / "server" / "trials.db")
        self.dbpatch.start()
        self.client, self.code = store.create_client("AZT trial test")
        self.client_id = self.client.id

    def tearDown(self):
        self.dbpatch.stop()
        self.tmp.cleanup()

    def test_first_pair_starts_once_from_server_utc(self):
        trial_licenses.issue(self.client_id)
        with self.assertRaises(ValueError):
            trial_licenses.issue(self.client_id)
        self.assertFalse(azt_store.subscription_summary(self.client_id)["allowed"])
        started = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
        with store.connect() as con:
            trial_licenses.activate(con, self.client_id, now=started)
        row = trial_licenses.status(self.client_id)
        self.assertEqual(row["activated_utc"], started.isoformat())
        self.assertEqual(row["expires_utc"], (started + timedelta(days=30)).isoformat())
        with store.connect() as con:
            trial_licenses.activate(con, self.client_id, now=started + timedelta(days=25))
        self.assertEqual(trial_licenses.status(self.client_id)["expires_utc"], row["expires_utc"])
        with store.connect() as con:
            just_before = azt_store._subscription_summary(con, self.client_id, now=started + timedelta(days=29))
            expired = azt_store._subscription_summary(con, self.client_id, now=started + timedelta(days=30))
        self.assertTrue(just_before["allowed"])
        self.assertEqual(just_before["subscription"]["plan_code"], "DISTRIBUTOR_TRIAL")
        self.assertFalse(expired["allowed"])
        self.assertEqual(expired["reason"], "DISTRIBUTOR_TRIAL_EXPIRED")

    def test_revocation_blocks_early_and_conversion_never_renews_paid_access(self):
        trial_licenses.issue(self.client_id)
        started = datetime.now(timezone.utc)
        with store.connect() as con:
            trial_licenses.activate(con, self.client_id, now=started)
        self.assertTrue(azt_store.subscription_summary(self.client_id)["allowed"])
        trial_licenses.change(self.client_id, "revoke")
        self.assertEqual(azt_store.subscription_summary(self.client_id)["reason"], "DISTRIBUTOR_TRIAL_REVOKED")
        trial_licenses.change(self.client_id, "convert")
        summary = azt_store.subscription_summary(self.client_id)
        self.assertFalse(summary.get("distributor_trial", False))
        self.assertNotEqual(summary["subscription"]["plan_code"], "DISTRIBUTOR_TRIAL")
        self.assertFalse(summary["allowed"])
        self.assertEqual(summary["effective_status"], "PAYMENT_REQUIRED")
        azt_store.renew_subscription(self.client_id, 30, paid=True)
        self.assertTrue(azt_store.subscription_summary(self.client_id)["allowed"])

    def test_trial_does_not_affect_standard_clients_or_client_suspensions(self):
        standard, _ = store.create_client("Untouched standard")
        self.assertFalse(azt_store.subscription_summary(standard.id).get("distributor_trial", False))
        trial_licenses.issue(self.client_id)
        with store.connect() as con:
            trial_licenses.activate(con, self.client_id)
        store.set_status(self.client.name, "REVOKED")
        self.assertFalse(azt_store.subscription_summary(self.client_id)["allowed"])

    def test_reminders_follow_distributor_expiry(self):
        trial_licenses.issue(self.client_id)
        started = datetime.now(timezone.utc)
        with store.connect() as con:
            trial_licenses.activate(con, self.client_id, now=started)
            con.execute("UPDATE subscriptions SET expires_utc=? WHERE client_id=?",
                        ((started - timedelta(days=1)).isoformat(), self.client_id))
        with patch.object(azt_store, "_telegram"):
            self.assertEqual(azt_store.maintenance_tick()["reminders"], 0)
            with patch.object(azt_store, "utc_now", return_value=started + timedelta(days=30)):
                self.assertEqual(azt_store.maintenance_tick()["reminders"], 1)
                self.assertEqual(azt_store.maintenance_tick()["reminders"], 0)
        self.assertEqual(azt_store.messages(self.client_id)[0]["title"], "30-day trial expired")


    def test_friends_fourteen_day_trial_starts_on_first_pair_without_extending(self):
        trial_licenses.issue(self.client_id, days=14)
        begun = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
        with store.connect() as con:
            trial_licenses.activate(con, self.client_id, now=begun)
            trial_licenses.activate(con, self.client_id, now=begun + timedelta(days=7))
        row = trial_licenses.status(self.client_id)
        self.assertEqual(row["days"], 14)
        self.assertEqual(row["expires_utc"], (begun + timedelta(days=14)).isoformat())
        with store.connect() as con:
            before = azt_store._subscription_summary(con, self.client_id, now=begun + timedelta(days=13))
            after = azt_store._subscription_summary(con, self.client_id, now=begun + timedelta(days=14))
        self.assertTrue(before["allowed"])
        self.assertFalse(after["allowed"])
        self.assertEqual(after["reason"], "DISTRIBUTOR_TRIAL_EXPIRED")

    def test_friends_trial_reminder_uses_fourteen_day_label(self):
        trial_licenses.issue(self.client_id, days=14)
        begun = datetime.now(timezone.utc) - timedelta(days=14, seconds=1)
        with store.connect() as con:
            trial_licenses.activate(con, self.client_id, now=begun)
        with patch.object(azt_store, "_telegram"):
            azt_store.maintenance_tick()
        self.assertEqual(azt_store.messages(self.client_id)[0]["title"], "14-day trial expired")

    def test_no_naive_or_invalid_duration(self):
        with self.assertRaises(ValueError):
            trial_licenses.issue(self.client_id, 31)
        with self.assertRaises(ValueError):
            trial_licenses._now(datetime(2026,10,30,12))


if __name__ == "__main__":
    unittest.main()
