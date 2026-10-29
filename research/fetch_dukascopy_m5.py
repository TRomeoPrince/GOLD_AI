"""Read-only Dukascopy BID minute-candle loader for historical AZT research.

This is NOT the user's MT5 broker feed. Download raw Dukascopy daily BI5
records, validate prices/times, then aggregate COMPLETE UTC M5 candles.
Never writes to MT5 or connects to a trading account.
"""
from __future__ import annotations
import argparse
from datetime import date, timedelta
import lzma
from pathlib import Path
import struct
import time
import urllib.error
import urllib.request

import pandas as pd

RECORD = struct.Struct(">IIIIIf")
BASE = "https://datafeed.dukascopy.com/datafeed/XAUUSD"
PRICE_SCALE = 1000.0


def one_day(d: date, retries: int = 3) -> pd.DataFrame:
    url = f"{BASE}/{d.year}/{d.month - 1:02}/{d.day:02}/BID_candles_min_1.bi5"
    blob = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "AZT-research/1.0"}), timeout=30
            ) as response:
                blob = response.read()
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 403):
                return pd.DataFrame()
            if attempt == retries - 1:
                raise
        except (TimeoutError, OSError):
            if attempt == retries - 1:
                raise
        time.sleep(1 + attempt)
    if not blob:
        return pd.DataFrame()
    decoded = lzma.decompress(blob)
    if len(decoded) % RECORD.size:
        raise ValueError(f"Unexpected Dukascopy candle file length on {d}.")
    data = []
    base = pd.Timestamp(d, tz="UTC")
    for i in range(0, len(decoded), RECORD.size):
        sec, op, cl, lo, hi, volume = RECORD.unpack_from(decoded, i)
        if sec >= 86400 or sec % 60:
            raise ValueError(f"Invalid minute offset on {d}: {sec}.")
        values = [op / PRICE_SCALE, hi / PRICE_SCALE, lo / PRICE_SCALE, cl / PRICE_SCALE]
        if min(values) < 200 or max(values) > 20000 or values[1] < max(values[0], values[2], values[3]) or values[2] > min(values[0], values[1], values[3]):
            raise ValueError(f"Invalid XAUUSD OHLC from Dukascopy on {d}.")
        data.append((base + pd.Timedelta(seconds=sec), values[0], values[1], values[2], values[3]))
    return pd.DataFrame(data, columns=["time", "open", "high", "low", "close"])


def fetch(start: date, end: date) -> pd.DataFrame:
    if start > end:
        raise ValueError("Start after end.")
    frames = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            day = one_day(d)
            if not day.empty:
                frames.append(day)
                print(f"{d}: {len(day)} M1 bid candles", flush=True)
        d += timedelta(days=1)
    if not frames:
        raise RuntimeError("No historical Dukascopy XAUUSD candles found; cannot backtest.")
    one = pd.concat(frames).drop_duplicates("time").sort_values("time").set_index("time")
    five = one.resample("5min", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"), count=("close", "count"))
    # Discard incomplete 5-minute samples to avoid invented prices
    five = five[five["count"] == 5].drop(columns=["count"]).reset_index()
    if len(five) < 500:
        raise RuntimeError("Fewer than 500 complete M5 bars; refuse meaningless report.")
    return five


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="start", required=True)
    p.add_argument("--to", dest="end", required=True)
    p.add_argument("--output", default="data/dukascopy_xauusd_bid_m5.csv")
    args = p.parse_args()
    f = fetch(date.fromisoformat(args.start), date.fromisoformat(args.end))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    f.to_csv(output, index=False)
    print(f"DATASET: rows={len(f)} start={f.time.min()} end={f.time.max()} bid M5 complete only", flush=True)
    print(f"FILE={output}", flush=True)


if __name__ == "__main__":
    main()
