"""Admin reconnect regression tests. Pure state machine; no trading or network."""
import unittest
from server.reconnect import RetryState, RetryPolicy

class AdminConnectionRegressionTests(unittest.TestCase):
    def test_failures_degrade_after_threshold_and_backoff_is_bounded(self):
        state = RetryState(RetryPolicy(interval=1, cap=4, alert_after=3, alert_cooldown=20))
        self.assertEqual(state.state, "RECONNECTING")
        self.assertEqual(state.failed(), 1)
        self.assertEqual(state.failed(), 2)
        self.assertEqual(state.state, "RECONNECTING")
        self.assertEqual(state.failed(), 4)
        self.assertEqual(state.state, "DEGRADED")
        self.assertEqual(state.failed(), 4)
    def test_alert_is_rate_limited(self):
        state = RetryState(RetryPolicy(interval=1, cap=4, alert_after=1, alert_cooldown=20))
        state.failed()
        self.assertTrue(state.should_alert(now=100))
        self.assertFalse(state.should_alert(now=101))
        self.assertTrue(state.should_alert(now=120))

if __name__ == "__main__":
    unittest.main()
