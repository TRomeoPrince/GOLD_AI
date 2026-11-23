from __future__ import annotations

from math import isfinite


def target_at_executable_price(direction: str, price: float, stop_loss: float,
                               reward_r: float) -> float:
    """Keep the structural SL and calculate the target from the obtainable entry.

    The candle close is a *signal reference*, not an executable entry. Do not
    adjust the structural stop to make an otherwise invalid trade look valid.
    """
    price, stop_loss, reward_r = float(price), float(stop_loss), float(reward_r)
    if not all(isfinite(v) for v in (price, stop_loss, reward_r)):
        raise ValueError("Non-finite M15 execution geometry")
    if price <= 0 or stop_loss <= 0 or not 0 < reward_r <= 10:
        raise ValueError("Invalid M15 execution geometry")
    if direction == "BUY":
        if price <= stop_loss:
            raise ValueError("M15 BUY executable entry is at/below structural SL")
        return price + reward_r * (price - stop_loss)
    if direction == "SELL":
        if price >= stop_loss:
            raise ValueError("M15 SELL executable entry is at/above structural SL")
        return price - reward_r * (stop_loss - price)
    raise ValueError("Unsupported M15 trade direction")
