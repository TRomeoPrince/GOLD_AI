"""Read-only MT5 cent-account suitability check. NEVER sends orders."""
from __future__ import annotations

import argparse

import MetaTrader5 as mt5


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only MT5 cent account and gold risk check")
    parser.add_argument("--symbol", default="XAUUSD", help="Preferred symbol or symbol substring")
    parser.add_argument("--risk", type=float, default=0.9, help="Risk percent of equity")
    args = parser.parse_args()
    if not (0 < args.risk <= 100):
        parser.error("--risk must be between 0 and 100")

    if not mt5.initialize():
        raise SystemExit(f"MT5 connection failed: {mt5.last_error()}")
    try:
        account = mt5.account_info()
        if account is None:
            raise SystemExit(f"No account information: {mt5.last_error()}")
        symbols = mt5.symbols_get() or ()
        candidates = [s.name for s in symbols if args.symbol.upper() in s.name.upper()]
        if not candidates:
            raise SystemExit(f"No symbols containing {args.symbol!r}. Check Market Watch.")
        exact = [name for name in candidates if name.upper() == args.symbol.upper()]
        chosen = exact[0] if exact else sorted(candidates, key=len)[0]
        if not mt5.symbol_select(chosen, True):
            raise SystemExit(f"Cannot select {chosen}: {mt5.last_error()}")
        info = mt5.symbol_info(chosen)
        tick = mt5.symbol_info_tick(chosen)
        if info is None or tick is None:
            raise SystemExit(f"No symbol specifications or tick for {chosen}")

        equity = float(account.equity)
        risk_budget = equity * args.risk / 100
        minimum = float(info.volume_min)
        ask = float(tick.ask)
        print("GOLD_AI - HEADWAY ACCOUNT CHECK (READ-ONLY)")
        print("NO TRADES WILL BE PLACED.")
        print(f"Broker server    : {account.server}")
        print(f"Account type     : {('DEMO' if int(account.trade_mode) == int(mt5.ACCOUNT_TRADE_MODE_DEMO) else 'REAL/OTHER')}")
        print(f"Account currency : {account.currency}")
        print(f"Balance          : {account.balance:.6f} {account.currency}")
        print(f"Equity           : {equity:.6f} {account.currency}")
        print(f"Free margin      : {account.margin_free:.6f} {account.currency}")
        print(f"Risk budget      : {risk_budget:.6f} {account.currency} ({args.risk}%)")
        print(f"Candidate symbols: {', '.join(candidates[:12])}")
        print(f"Selected symbol  : {chosen}")
        print(f"Contract size    : {info.trade_contract_size}")
        print(f"Min/step/max lot : {info.volume_min} / {info.volume_step} / {info.volume_max}")
        print(f"Stops level      : {info.trade_stops_level} points")
        print(f"Point/tick size  : {info.point} / {info.trade_tick_size}")
        print(f"Bid/ask          : {tick.bid} / {ask}")
        margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, chosen, minimum, ask)
        print(f"Min-lot margin   : {margin if margin is not None else 'unavailable'} {account.currency}")
        print()
        print("ESTIMATED MIN-LOT STOP LOSSES (not strategy SLs):")
        for distance in (1.0, 3.0, 5.0, 10.0):
            result = mt5.order_calc_profit(
                mt5.ORDER_TYPE_BUY, chosen, minimum, ask, ask - distance
            )
            if result is None:
                print(f"  {distance:>4.1f} gold points : unavailable {mt5.last_error()}")
                continue
            loss = max(0.0, -float(result))
            pct = (loss / equity * 100) if equity > 0 else float("inf")
            permitted = loss <= risk_budget and loss > 0
            print(
                f"  {distance:>4.1f} gold points : {loss:.6f} {account.currency}"
                f" ({pct:.2f}% of equity) -> {'WITHIN BUDGET' if permitted else 'EXCEEDS BUDGET'}"
            )
        print()
        print("This is a diagnostic, not permission to trade live.")
        print("Do not override minimum-lot risk checks to force an order.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
