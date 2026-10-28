"""Notification metadata collected after submission; never changes an order."""
from datetime import datetime, timezone
from math import isfinite


def finite(value):
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def execution_details(api, result, request, payload, *, ticket, risk_pct, portfolio_after_pct, max_open_risk_pct, verified_account=None):
    entry = finite(getattr(result, 'price', None))
    actual = entry is not None and entry > 0
    if not actual:
        entry = finite(request.get('price'))
    volume = finite(getattr(result, 'volume', None))
    if volume is None or volume <= 0:
        volume = finite(request.get('volume'))
    data = dict(ticket=str(ticket or ''), state='OPEN', symbol=str(request.get('symbol', '')),
                direction=str(payload.get('direction', '')).upper(), strategy=str(payload.get('strategy_id', '')),
                market=str(payload.get('market', '')), entry=entry, entry_basis='FILLED' if actual else 'REQUESTED',
                volume=volume, sl=finite(request.get('sl')), tp=finite(request.get('tp')),
                risk_pct=finite(risk_pct), portfolio_after_pct=finite(portfolio_after_pct),
                max_open_risk_pct=finite(max_open_risk_pct), executed_utc=datetime.now(timezone.utc).isoformat())
    same_account = False
    try:
        current = api.account_info()
        account = verified_account if verified_account is not None else current
        data['currency'] = str(getattr(account, 'currency', '') or '')
        data['account_key'] = f"{account.server}|{account.login}"
        same_account = (current.server,current.login)==(account.server,account.login)
    except Exception:
        pass
    for field in ('sl', 'tp'):
        estimate = None
        if same_account and entry and volume and data[field] and data[field] > 0:
            try:
                estimate = finite(api.order_calc_profit(request['type'], data['symbol'], volume, entry, data[field]))
            except Exception:
                pass
        data[field + '_pnl'] = estimate
    data['risk_cash'] = max(0, -data['sl_pnl']) if data['sl_pnl'] is not None else None
    return data


class SignalOutcome(tuple):
    """Preserve the existing (state, message) interface for callers."""
    def __new__(cls, state, message, details=None):
        result = super().__new__(cls, (state, message))
        result.details = details or {}
        return result
