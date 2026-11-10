"""No live brokers, external clock calls, or Telegram messages in this suite."""
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from mini_trial import clock, runtime
from mini_trial.cleanup import start_uninstall
from mini_trial.manager import MiniManager

class ClockTests(unittest.TestCase):
    def setUp(self):
        clock.reset_cache_for_tests()

    def test_before_expiry(self):
        now=datetime(2026,11,17,20,59,tzinfo=timezone.utc)
        self.assertEqual(clock.require_active(force=True,fetcher=lambda:now),now)

    def test_expired(self):
        with self.assertRaises(clock.TrialExpired):
            clock.require_active(force=True,fetcher=lambda:clock.EXPIRES_UTC)

    def test_offline_fails_closed(self):
        with self.assertRaises(clock.ClockUnavailable):
            clock.require_active(force=True,fetcher=lambda:(_ for _ in ()).throw(clock.ClockUnavailable("offline")))

    def test_rollback_fails_closed(self):
        clock.require_active(force=True,fetcher=lambda:datetime(2026,11,16,12,tzinfo=timezone.utc))
        with self.assertRaises(clock.ClockUnavailable):
            clock.require_active(force=True,fetcher=lambda:datetime(2026,11,15,12,tzinfo=timezone.utc))

    def test_fresh_time_required(self):
        with patch.object(clock.time,"monotonic",side_effect=[500,560]):
            clock.require_active(force=True,fetcher=lambda:datetime(2026,11,17,20,59,40,tzinfo=timezone.utc))
            with self.assertRaises(clock.ClockUnavailable):
                clock.require_active(fetcher=lambda:(_ for _ in ()).throw(clock.ClockUnavailable("offline")))

class IsolationTests(unittest.TestCase):
    def test_owns_separate_database(self):
        with TemporaryDirectory() as d, patch.dict(os.environ,{"GOLD_AI_DB_PATH":"C:/owner/private.db"}):
            old=Path.cwd()
            keys=("GOLD_AI_HOME","GOLD_AI_PROJECT_ROOT","GOLD_AI_STATE_DIR","GOLD_AI_DB_PATH","AZT_MINI_TRIAL")
            values={k:os.environ.get(k) for k in keys}
            try:
                root=runtime.configure(Path(d))
                self.assertEqual(os.environ["GOLD_AI_DB_PATH"],str(root/"state"/"gold_ai_server.db"))
                self.assertEqual(os.environ["AZT_MINI_TRIAL"],"1")
            finally:
                os.chdir(old)
                for k,val in values.items():
                    if val is None: os.environ.pop(k,None)
                    else: os.environ[k]=val

    def test_rejects_owner_services(self):
        with TemporaryDirectory() as d:
            m=MiniManager(Path(d))
            for role in ("api","telegram","notifications","hosted_1","maintenance"):
                with self.assertRaises(ValueError):
                    m.start(role)

    def test_no_uninstall_without_installer(self):
        with patch("mini_trial.cleanup.Path.is_file",return_value=False):
            self.assertFalse(start_uninstall())

if __name__=="__main__":
    unittest.main()
