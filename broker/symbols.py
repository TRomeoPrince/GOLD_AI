"""Resolve a market against the connected broker's own tradable contracts.

An upstream broker's suffix is a hint about a market, never a destination symbol.
No order is sent by this module.
"""
from __future__ import annotations

import math
import re


def canonical_market(hint: str) -> str:
    value = str(hint or "GOLD").upper().strip()
    if "XAUUSD" in value or re.search(r"(?:^|[._#-])GOLD(?:$|[._#-])", value) or value == "GOLD":
        return "GOLD"
    return re.split(r"[._#-]", value)[0]


def _matches(name: str, market: str) -> bool:
    value = name.upper()
    if market == "GOLD":
        if any(other in value for other in ("XAUEUR", "XAUGBP", "GOLDEUR", "GOLDGBP", "GOLDINDEX")):
            return False
        # Broker prefixes/suffixes are accepted; a different metal/currency is not.
        return bool(re.fullmatch(r"[A-Z0-9._#-]{0,8}(?:XAUUSD|GOLD)(?:USD)?[A-Z0-9._#-]{0,8}", value))
    return bool(re.fullmatch(r"[A-Z0-9._#-]{0,6}" + re.escape(market) + r"[A-Z0-9._#-]{0,6}", value))


def _valid_contract(info, market: str) -> bool:
    if info is None:
        return False
    for field in ("volume_min", "volume_max", "volume_step", "trade_contract_size", "point"):
        value = getattr(info, field, None)
        if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0):
            return False
    if getattr(info, "trade_mode", None) == 0:
        return False
    path = str(getattr(info, "path", "")).lower()
    if any(word in path for word in ("options", "futures", "shares", "etfs")):
        return False
    if market == "GOLD":
        base = str(getattr(info, "currency_base", "") or "").upper()
        quote = str(getattr(info, "currency_profit", "") or "").upper()
        if base and base not in {"XAU", "GOLD"}:
            return False
        if quote and quote != "USD":
            return False
    return True


def resolve_symbol(api, market_or_hint: str = "GOLD") -> str:
    market = canonical_market(market_or_hint)
    candidates = []
    for item in api.symbols_get() or ():
        name = str(item.name)
        if not _matches(name, market):
            continue
        info = api.symbol_info(name)
        if not _valid_contract(info, market):
            continue
        # Prefer canonical contracts, then visible short broker variants. Never
        # prefer the owner's suffix merely because it was present upstream.
        rank = (0 if name.upper() in {market, "XAUUSD" if market == "GOLD" else market} else 1,
                0 if bool(getattr(info, "visible", False)) else 1, len(name), name.upper())
        candidates.append((rank, name, info))
    for _, name, info in sorted(candidates, key=lambda row: row[0]):
        if not bool(getattr(info, "visible", False)) and not api.symbol_select(name, True):
            continue
        return name
    raise RuntimeError(f"No valid tradable local broker contract found for market {market}.")
