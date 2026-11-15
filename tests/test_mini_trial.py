"""Mini trial tests: no real broker, external network or Telegram calls."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mini_trial import clock, runtime
from mini_trial.cleanup import start_uninstall
from mini_trial.manager import MiniManager


class ClockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="azt-mini-14day-test-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "state" / "trial_lease.json"
        self.now = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
        clock.reset_cache_for_tests()

    def activate(self):
        return clock.require_active(force=True, fetcher=lambda: self.now, path=self.path)

    def test_first_verified_launch_starts_exactly_fourteen_days(self):
        self.assertEqual(self.activate(), self.now)
        data = clock.load_lease(path=self.path)
        self.assertEqual(data["activated_utc"], self.now)
        self.assertEqual(data["expires_utc"], self.now + timedelta(days=14))
        self.assertTrue(self.path.is_file())

    def test_exact_expiry_blocks_trading(self):
        self.activate()
        clock.reset_cache_for_tests()
        before = self.now + timedelta(days=14) - timedelta(seconds=1)
        self.assertEqual(clock.require_active(force=True, fetcher=lambda: before, path=self.path), before)
        with self.assertRaises(clock.TrialExpired):
            clock.require_active(force=True, fetcher=lambda: self.now + timedelta(days=14), path=self.path)

    def test_reinstall_and_late_start_cannot_reset_existing_deadline(self):
        self.activate()
        clock.reset_cache_for_tests()
        after_seven = self.now + timedelta(days=7)
        self.assertEqual(clock.require_active(force=True, fetcher=lambda: after_seven, path=self.path), after_seven)
        self.assertEqual(clock.load_lease(path=self.path)["activated_utc"], self.now)
        self.assertEqual(clock.load_lease(path=self.path)["expires_utc"], self.now + timedelta(days=14))

    def test_scheduled_check_cannot_start_trial_before_friend_first_opens_app(self):
        self.assertFalse(clock.expired_existing_lease(path=self.path))
        self.assertFalse(self.path.exists())
        self.activate()
        clock.reset_cache_for_tests()
        self.assertFalse(clock.expired_existing_lease(
            fetcher=lambda: self.now + timedelta(days=13), path=self.path))
        self.assertTrue(clock.expired_existing_lease(
            fetcher=lambda: self.now + timedelta(days=14), path=self.path))

    def test_offline_fails_closed_without_consuming_trial(self):
        with self.assertRaises(clock.ClockUnavailable):
            clock.require_active(force=True, path=self.path,
                fetcher=lambda: (_ for _ in ()).throw(clock.ClockUnavailable("offline")))
        self.assertFalse(self.path.exists())

    def test_rollback_fails_closed(self):
        self.activate()
        with self.assertRaises(clock.ClockUnavailable):
            clock.require_active(force=True,
                fetcher=lambda: self.now - timedelta(days=1), path=self.path)

    def test_fresh_time_required(self):
        with patch.object(clock.time, "monotonic", side_effect=[500, 560]):
            self.activate()
            with self.assertRaises(clock.ClockUnavailable):
                clock.require_active(path=self.path,
                    fetcher=lambda: (_ for _ in ()).throw(clock.ClockUnavailable("offline")))

    def test_corrupted_lease_is_blocked_not_restarted(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{invalid", encoding="utf-8")
        with self.assertRaises(clock.ClockUnavailable):
            clock.require_active(force=True, fetcher=lambda: self.now, path=self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{invalid")


class IsolationTests(unittest.TestCase):
    def test_owns_separate_database(self):
        with TemporaryDirectory() as d, patch.dict(os.environ, {"GOLD_AI_DB_PATH": "C:/owner/private.db"}):
            old = Path.cwd()
            keys = ("GOLD_AI_HOME", "GOLD_AI_PROJECT_ROOT", "GOLD_AI_STATE_DIR", "GOLD_AI_DB_PATH", "AZT_MINI_TRIAL")
            values = {k: os.environ.get(k) for k in keys}
            try:
                root = runtime.configure(Path(d))
                self.assertEqual(os.environ["GOLD_AI_DB_PATH"], str(root / "state" / "gold_ai_server.db"))
                self.assertEqual(os.environ["AZT_MINI_TRIAL"], "1")
            finally:
                os.chdir(old)
                for k, val in values.items():
                    if val is None: os.environ.pop(k, None)
                    else: os.environ[k] = val

    def test_rejects_owner_services(self):
        with TemporaryDirectory() as d:
            m = MiniManager(Path(d))
            for role in ("api", "telegram", "notifications", "hosted_1", "maintenance"):
                with self.assertRaises(ValueError):
                    m.start(role)

    def test_no_uninstall_without_installer(self):
        with patch("mini_trial.cleanup.Path.is_file", return_value=False):
            self.assertFalse(start_uninstall())


if __name__ == "__main__":
    unittest.main()
