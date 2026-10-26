"""Convert the live MT5 feed clock to UTC once at the data boundary.

Most feeds follow the documented UTC contract. Some servers encode their
wall clock in epoch fields. Clock calibration requires advancing live ticks;
we never infer an offset from an old candle or make a stale signal fresh.
"""
from __future__ import annotations
from dataclasses import dataclass
import logging
import math
import time

MAX_CLOCK_SKEW_SECONDS = 5


def tick_epoch(tick):
    if tick is None:
        raise RuntimeError("MT5 clock: no quote available.")
    msc = getattr(tick, "time_msc", 0)
    value = float(msc) / 1000 if isinstance(msc, (int, float)) and msc > 0 else float(tick.time)
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError("MT5 clock: invalid quote timestamp.")
    return value


@dataclass(frozen=True)
class BrokerClock:
    offset_seconds: int

    @classmethod
    def detect(cls, api, symbol, first_tick=None, *, now=None, sleep=None):
        now = now or time.time
        sleep = sleep or time.sleep
        first = tick_epoch(first_tick if first_tick is not None else api.symbol_info_tick(symbol))
        observed_now = now()
        offset = round((first - observed_now) / 900) * 900
        if abs(offset) > 14 * 3600 or abs(first - observed_now - offset) > MAX_CLOCK_SKEW_SECONDS:
            raise RuntimeError("MT5 clock cannot be established from a fresh quote. Check the UTC clock and broker feed.")
        # This is required even for zero: a cached broker-wall-clock quote can
        # accidentally resemble current UTC after an hour-offset-sized outage.
        for _ in range(50):
            sleep(.1)
            latest = tick_epoch(api.symbol_info_tick(symbol))
            if latest > first:
                if abs(latest - now() - offset) > MAX_CLOCK_SKEW_SECONDS:
                    raise RuntimeError("MT5 broker clock changed during calibration.")
                break
        else:
            raise RuntimeError("MT5 broker-clock calibration needs advancing live quotes; no offset was guessed.")
        logging.info("MT5 clock %s: raw feed minus UTC = %+d seconds", symbol, offset)
        return cls(int(offset))

    def to_utc_epoch(self, raw_epoch):
        return raw_epoch - self.offset_seconds

    def validate_tick(self, tick, *, now=None):
        utc = self.to_utc_epoch(tick_epoch(tick))
        age = (time.time() if now is None else now) - utc
        if not -MAX_CLOCK_SKEW_SECONDS <= age <= 120:
            raise RuntimeError("MT5 quote is stale or broker clock changed; reconnect to calibrate. No timestamp was rebased.")
        return utc


_clocks = {}


def tick_utc_epoch(api, symbol, tick):
    account, terminal = api.account_info(), api.terminal_info()
    if account is None or terminal is None:
        raise RuntimeError("MT5 terminal/account unavailable for clock validation.")
    key = (str(account.server), str(getattr(terminal, "path", "")), symbol)
    clock = _clocks.get(key)
    if clock is None:
        clock = BrokerClock.detect(api, symbol, tick)
        _clocks[key] = clock
    return clock.validate_tick(tick)
