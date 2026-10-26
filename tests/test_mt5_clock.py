from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import unittest
import pandas as pd
from broker.clock import BrokerClock
from broker import mt5_client
from strategies.momentum_scalp import MomentumScalpStrategy

NOW=datetime(2026,10,26,8,27,tzinfo=timezone.utc).timestamp()

class BrokerClockTests(unittest.TestCase):
    def test_utc_feed_is_not_shifted(self):
        api=Mock()
        api.symbol_info_tick.side_effect=[NS(time=NOW),NS(time=NOW+1)]
        times=iter([NOW,NOW+1])
        clock=BrokerClock.detect(api,'GOLD',now=lambda:next(times),sleep=lambda _:None)
        self.assertEqual(clock.offset_seconds,0)
        self.assertEqual(clock.to_utc_epoch(NOW-300),NOW-300)
    def test_two_hour_server_clock_requires_advancing_ticks(self):
        api=Mock()
        api.symbol_info_tick.side_effect=[NS(time=NOW+7200),NS(time=NOW+7201)]
        times=iter([NOW,NOW+1])
        clock=BrokerClock.detect(api,'GOLD',now=lambda:next(times),sleep=lambda _:None)
        self.assertEqual(clock.offset_seconds,7200)
        raw=datetime(2026,10,26,10,25,tzinfo=timezone.utc).timestamp()
        self.assertEqual(datetime.fromtimestamp(clock.to_utc_epoch(raw),timezone.utc).isoformat(),'2026-10-26T08:25:00+00:00')
    def test_cached_stale_quote_never_calibrates_as_another_timezone(self):
        api=Mock()
        api.symbol_info_tick.return_value=NS(time=NOW+3600)
        with self.assertRaisesRegex(RuntimeError,'advancing live quotes'):
            BrokerClock.detect(api,'GOLD',now=lambda:NOW,sleep=lambda _:None)
    def test_cached_shifted_quote_cannot_masquerade_as_current_utc(self):
        api=Mock()
        api.symbol_info_tick.return_value=NS(time=NOW)
        with self.assertRaisesRegex(RuntimeError,'advancing live quotes'):
            BrokerClock.detect(api,'GOLD',now=lambda:NOW,sleep=lambda _:None)

    def test_inconsistent_or_nonfinite_clock_is_rejected(self):
        api=Mock()
        api.symbol_info_tick.side_effect=[NS(time=NOW+7200),NS(time=NOW+8200)]
        with self.assertRaisesRegex(RuntimeError,'changed during calibration'):
            BrokerClock.detect(api,'GOLD',now=lambda:NOW,sleep=lambda _:None)
        api.symbol_info_tick.side_effect=None
        api.symbol_info_tick.return_value=NS(time=float('nan'))
        with self.assertRaisesRegex(RuntimeError,'invalid'):
            BrokerClock.detect(api,'GOLD',now=lambda:NOW)
    def test_old_and_future_quotes_fail_without_rebasing(self):
        clock=BrokerClock(7200)
        for raw in (NOW+7200-121,NOW+7200+6):
            with self.subTest(raw=raw),self.assertRaises(RuntimeError):
                clock.validate_tick(NS(time=raw),now=NOW)
        self.assertEqual(clock.offset_seconds,7200)
    def test_normalized_candles_reach_strategy_setup_time_as_true_utc(self):
        forming=datetime(2026,10,26,10,25,tzinfo=timezone.utc).timestamp()
        rates=[dict(time=forming-(24-i)*300,open=100,high=101,low=99,close=100,tick_volume=1) for i in range(25)]
        rates[-2].update(high=110,low=99,close=109)
        client=mt5_client.MT5Client()
        client.symbol='XAUUSD.c'
        client.clock=BrokerClock(7200)
        with patch.object(mt5_client.mt5,'copy_rates_from_pos',return_value=rates),patch.object(mt5_client.mt5,'symbol_info_tick',return_value=NS(time=NOW+7200)),patch('broker.clock.time.time',return_value=NOW):
            frame=client.candles(5,25)
        self.assertEqual(str(frame.iloc[-1]['time']),'2026-10-26 08:25:00+00:00')
        self.assertEqual(frame.iloc[-1]['broker_time'],forming)
        signals=MomentumScalpStrategy().scan(frame)
        self.assertEqual(len(signals),1)
        self.assertEqual(signals[0].setup_time,'2026-10-26 08:20:00+00:00')
        self.assertEqual((pd.Timestamp(NOW,unit='s',tz='UTC')-pd.Timestamp(signals[0].setup_time)).total_seconds(),420)

if __name__=='__main__':unittest.main()
