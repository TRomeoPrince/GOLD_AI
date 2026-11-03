"""Research-only S/R M5 confirmation and same-strategy lock tests."""
import unittest
import pandas as pd
from strategies.base import StrategySignal
from research.sr_m5_confirmation_backtest import (
    ConfirmedSupportResistance, close_trade, select_trades,
    pairwise_backtest, summarize,
)


def visible(prev, current, *, altered_dummy=False):
    f = []
    for i in range(70):
        f.append({"time":pd.Timestamp("2026-10-01",tz="UTC")+pd.Timedelta(minutes=5*i),
                  "open":99.8,"high":100.3,"low":99.3,"close":99.8})
    for i,c in enumerate([prev,current]):
        f.append({"time":pd.Timestamp("2026-10-01",tz="UTC")+pd.Timedelta(minutes=5*(70+i)),
                  **dict(zip(("open","high","low","close"),c))})
    f.append({"time":pd.Timestamp("2026-10-01",tz="UTC")+pd.Timedelta(minutes=5*72),
              "open":50000 if altered_dummy else 99.8,
              "high":60000 if altered_dummy else 99.8,
              "low":1 if altered_dummy else 99.8,
              "close":800 if altered_dummy else 99.8})
    return pd.DataFrame(f)


def model():
    m=ConfirmedSupportResistance(min_stop_atr=1.5)
    m._pivots=lambda history: ([100.,100.],[95.,95.])
    return m


class ConfirmationTests(unittest.TestCase):
    def test_bull_breakout_is_close_confirmed(self):
        f=visible((99.8,100.1,99.4,99.9),(100.0,102.3,99.8,102.0))
        signal=model().scan(f)
        self.assertEqual(len(signal),1)
        self.assertEqual(signal[0].direction,"BUY")
        self.assertEqual(signal[0].reason,"M5_CONFIRMED_BREAKOUT")
        self.assertLess(signal[0].stop_loss,signal[0].entry)

    def test_bull_rejection_or_engulfing_at_support(self):
        reject=visible((95.5,96.2,94.9,95.5),(95.1,96.1,94.1,95.7))
        got=model().scan(reject)
        self.assertEqual(got[0].reason,"M5_CONFIRMED_REJECTION")
        engulf=visible((95.9,96.0,95.0,95.2),(95.1,96.2,94.9,96.1))
        got=model().scan(engulf)
        self.assertEqual(got[0].reason,"M5_CONFIRMED_ENGULFING")

    def test_bear_breakdown_and_resistance_rejection(self):
        breakdown=visible((95.7,96.0,95.2,95.5),(95.3,95.5,93.0,93.3))
        got=model().scan(breakdown)
        self.assertEqual(got[0].reason,"M5_CONFIRMED_BREAKOUT")
        self.assertEqual(got[0].direction,"SELL")
        reject=visible((99.8,100.3,99.5,99.8),(100.2,101.5,99.4,99.6))
        got=model().scan(reject)
        self.assertEqual(got[0].reason,"M5_CONFIRMED_REJECTION")
        self.assertEqual(got[0].direction,"SELL")

    def test_forming_bar_is_never_used_to_confirm(self):
        prior=(99.8,100.1,99.4,99.9)
        last=(100.,102.3,99.8,102.)
        a=model().scan(visible(prior,last,altered_dummy=False))
        b=model().scan(visible(prior,last,altered_dummy=True))
        self.assertEqual(a,b)

    def test_wick_through_resistance_without_close_does_not_buy(self):
        base=visible((99.8,100.1,99.4,99.8),(99.8,101.1,99.7,99.95))
        self.assertEqual(model().scan(base),[])


class DirectionLockTests(unittest.TestCase):
    def setUp(self):
        self.data=pd.DataFrame([{
            "time": pd.Timestamp("2026-10-01",tz="UTC")+pd.Timedelta(minutes=5*i),
            "open":100.,"high":100.5,"low":99.5,"close":100.,
        } for i in range(150)])

    def signal(self, side, i):
        return StrategySignal("SUPPORT_RESISTANCE",side,"M5",
            str(self.data.at[i-1,"time"]),100.,
            90. if side=="BUY" else 110.,
            115. if side=="BUY" else 85.,"SYNTHETIC",{"reward_r":1.5})

    def test_lock_blocks_opposite_only_while_active(self):
        candidates=[(100,self.signal("BUY",100)),(102,self.signal("SELL",102)),
                    (121,self.signal("SELL",121))]
        all_trades, skip_none=select_trades(self.data,candidates,max_hold=20,
                                          cost_price=.5,direction_lock=False)
        locked, skipped=select_trades(self.data,candidates,max_hold=20,
                                     cost_price=.5,direction_lock=True)
        self.assertEqual(len(all_trades),3)
        self.assertEqual(skip_none,0)
        self.assertEqual(skipped,1)
        self.assertEqual(len(locked),2)
        self.assertEqual(locked[0]["exit_index"],119)

    def test_same_direction_stacking_is_unchanged(self):
        c=[(100,self.signal("BUY",100)),(102,self.signal("BUY",102))]
        accepted,skipped=select_trades(self.data,c,max_hold=20,cost_price=.5,
                                       direction_lock=True)
        self.assertEqual(skipped,0)
        self.assertEqual(len(accepted),2)

    def test_risk_outcomes_do_not_access_future_for_entry(self):
        result=close_trade(self.data,self.signal("BUY",100),100,hold=20,roundtrip_price_cost=.5)
        self.assertEqual(result["entry"],100.)
        self.assertEqual(result["exit_type"],"TIME")
        self.assertEqual(result["exit_index"],119)

    def test_all_modes_comparable_without_real_orders(self):
        t,c=pairwise_backtest(self.data,warmup=100,history_window=90,max_hold=20,cost_price=.5)
        self.assertEqual(len(c),4)
        summary=summarize(t,c,balance=2000,risk_pct=1.)
        self.assertEqual(set(summary["mode"]),set(c["mode"]))
        self.assertEqual(len(t),0)


if __name__ == "__main__":
    unittest.main()
