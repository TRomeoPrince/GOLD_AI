"""Read-only MT5 snapshots and UTC trade history for AZT views and journals.

Telemetry never submits, modifies or closes an order. API callers must derive
client/account scope from their authenticated session before calling ingest.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone as utc_timezone
import json
import hashlib
import math
import sqlite3
from zoneinfo import ZoneInfo

from .store import DB_PATH


def utc_iso(value=None):
    if value is None:
        return datetime.now(utc_timezone.utc).isoformat()
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError("Invalid UTC timestamp.")
        return datetime.fromtimestamp(value, utc_timezone.utc).isoformat()
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Trade timestamps must include an explicit UTC offset.")
    return parsed.astimezone(utc_timezone.utc).isoformat()


def display_time(value, timezone="UTC"):
    if not value:
        return "—"
    return datetime.fromisoformat(utc_iso(value)).astimezone(ZoneInfo(timezone)).isoformat()


def _scope(client_id):
    return "personal" if client_id is None else f"client:{int(client_id)}"


@contextmanager
def _connection(database=None):
    con = sqlite3.connect(database if database is not None else DB_PATH, timeout=1)
    con.row_factory = sqlite3.Row
    try:
        con.execute("CREATE TABLE IF NOT EXISTS azt_account_snapshots(scope TEXT NOT NULL,account_key TEXT NOT NULL,observed_utc TEXT NOT NULL,account_json TEXT NOT NULL,PRIMARY KEY(scope,account_key))")
        if "first_observed_utc" not in {row[1] for row in con.execute("PRAGMA table_info(azt_account_snapshots)")}:
            con.execute("ALTER TABLE azt_account_snapshots ADD COLUMN first_observed_utc TEXT")
            con.execute("UPDATE azt_account_snapshots SET first_observed_utc=observed_utc")
        con.execute("CREATE TABLE IF NOT EXISTS azt_trades(scope TEXT NOT NULL,account_key TEXT NOT NULL,kind TEXT NOT NULL,ticket TEXT NOT NULL,payload_json TEXT NOT NULL,observed_utc TEXT NOT NULL,PRIMARY KEY(scope,account_key,kind,ticket))")
        con.execute("CREATE TABLE IF NOT EXISTS azt_execution_details(scope TEXT NOT NULL,account_key TEXT NOT NULL,ticket TEXT NOT NULL,details_json TEXT NOT NULL,PRIMARY KEY(scope,account_key,ticket))")
        con.execute("CREATE TABLE IF NOT EXISTS azt_stop_events(event_key TEXT PRIMARY KEY,scope TEXT NOT NULL,account_key TEXT NOT NULL,ticket TEXT NOT NULL,observed_utc TEXT NOT NULL,payload_json TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS azt_stop_observations(scope TEXT NOT NULL,account_key TEXT NOT NULL,ticket TEXT NOT NULL,observed_utc TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(scope,account_key,ticket))")
        con.execute("CREATE INDEX IF NOT EXISTS azt_trade_scope ON azt_trades(scope,kind)")
        con.commit()
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _number(value, default=0):
    if value is None:
        return default
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Trade values must be finite.")
    return number


def _trade(item, kind):
    ticket = str(item.get("ticket") or item.get("position_id") or "").strip()
    if not ticket or len(ticket) > 80:
        raise ValueError("Trade ticket is required.")
    result = {"ticket": ticket, "position_id": str(item.get("position_id") or ticket),
              "symbol": str(item.get("symbol", ""))[:60], "direction": str(item.get("direction", ""))[:8],
              "strategy": str(item.get("strategy") or "—")[:100], "state": kind,
              "notes": str(item.get("notes") or "")[:1000]}
    result["is_partial_close"] = bool(item.get("is_partial_close", False))
    for name in ("volume", "entry", "exit", "current_price", "sl", "tp", "pnl", "profit", "risk_pct", "sl_pnl", "tp_pnl", "risk_cash", "portfolio_after_pct", "max_open_risk_pct"):
        result[name] = _number(item.get(name), None)
    result['entry_basis'] = {'FILLED': 'ACTUAL_FILL', 'ACTUAL_FILL': 'ACTUAL_FILL',
                             'REQUESTED': 'REQUESTED'}.get(item.get('entry_basis'), '')
    result['executed_utc'] = utc_iso(item['executed_utc']) if item.get('executed_utc') else None
    if result["pnl"] is None:
        result["pnl"] = result["profit"] if result["profit"] is not None else 0
    result["profit"] = result["pnl"]
    for name in ("opened_utc", "closed_utc"):
        result[name] = utc_iso(item[name]) if item.get(name) else None
    if kind == "CLOSED" and not result["closed_utc"]:
        raise ValueError("Closed trades require a UTC close timestamp.")
    reason = str(item.get("close_reason") or "")
    result["close_reason"] = reason if reason in {"TP HIT", "SL HIT", "STOP OUT"} else ""
    result["result"] = (result["close_reason"] or ("PROFIT" if result["pnl"] > 0 else "LOSS" if result["pnl"] < 0 else "BREAKEVEN")) if kind == "CLOSED" else "OPEN"
    return result


def record_execution(client_id, account_key, ticket, payload, *, risk_pct=None, trade_details=None, database=None):
    if not ticket:
        return
    details = {"strategy": str(payload.get("strategy_id") or "—"),
               "sl": _number(payload.get("stop_loss"), None), "tp": _number(payload.get("take_profit"), None),
               "risk_pct": _number(risk_pct, None)}
    supplied = trade_details if isinstance(trade_details, dict) else {}
    for name in ('entry','sl','tp','sl_pnl','tp_pnl','risk_cash','portfolio_after_pct','max_open_risk_pct','volume'):
        if supplied.get(name) is not None:
            details[name] = _number(supplied[name], None)
    for name in ('currency','symbol','direction','market'):
        if supplied.get(name):
            details[name] = str(supplied[name])[:80]
    if supplied.get('entry_basis') in {'FILLED', 'ACTUAL_FILL', 'REQUESTED'}:
        details['entry_basis'] = 'ACTUAL_FILL' if supplied['entry_basis'] == 'FILLED' else supplied['entry_basis']
    if supplied.get('executed_utc'):
        details['executed_utc'] = utc_iso(supplied['executed_utc'])
    with _connection(database) as con:
        con.execute("INSERT OR IGNORE INTO azt_execution_details VALUES(?,?,?,?)", (_scope(client_id), str(account_key), str(ticket), json.dumps(details, allow_nan=False)))


def _stop_event(con, scope, account_key, previous, current, observed, currency):
    """Persist an observed change, never claim who moved the broker's stop."""
    old_sl, new_sl = previous.get('sl'), current.get('sl')
    if old_sl is None or new_sl is None or old_sl == new_sl:
        return None
    signature = json.dumps([scope, account_key, current['ticket'], observed, old_sl, new_sl], separators=(',',':'))
    event_key = 'sl-update:' + hashlib.sha256(signature.encode('utf-8')).hexdigest()
    event = dict(current, state='SL_UPDATED', result='SL UPDATED', event_key=event_key,
                 account_key=account_key, scope=scope,
                 client_id=int(scope.split(':')[1]) if scope.startswith('client:') else None,
                 currency=currency or 'UNKNOWN', observed_utc=observed,
                 old_sl=old_sl, new_sl=new_sl, old_sl_pnl=previous.get('sl_pnl'),
                 new_sl_pnl=current.get('sl_pnl'), old_volume=previous.get('volume'),
                 change_source='OBSERVED', trailing_confirmed=False)
    inserted = con.execute('INSERT OR IGNORE INTO azt_stop_events VALUES(?,?,?,?,?,?)',
                           (event_key,scope,account_key,current['ticket'],observed,json.dumps(event,allow_nan=False))).rowcount
    return event if inserted else None


def list_stop_updates(client_id=None, *, account_key=None, after_utc=None, limit=100, database=None):
    """Durable events let an external sender recover after a producer exits."""
    clauses, values = [], []
    if client_id is not None:
        clauses.append('scope=?'); values.append(_scope(client_id))
    if account_key:
        clauses.append('account_key=?'); values.append(str(account_key))
    if after_utc:
        clauses.append('observed_utc>=?'); values.append(utc_iso(after_utc))
    where = ' WHERE '+' AND '.join(clauses) if clauses else ''
    with _connection(database) as con:
        rows=con.execute('SELECT payload_json FROM azt_stop_events'+where+' ORDER BY observed_utc DESC LIMIT ?',(*values,max(1,min(5000,int(limit))))).fetchall()
    return [json.loads(row['payload_json']) for row in rows]


def pending_stop_updates(*, limit=25, database=None):
    """Return a bounded recovery batch not yet present in its scoped outbox.

    Queued failures/holds count as queued: retries remain the outbox's job. A
    missing outbox table is normal before its destination is configured.
    """
    with _connection(database) as con:
        tables = {row['name'] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        owner_missing = "NOT EXISTS(SELECT 1 FROM owner_telegram_outbox q WHERE q.event_key=e.event_key)" if 'owner_telegram_outbox' in tables else '1'
        client_missing = "NOT EXISTS(SELECT 1 FROM azt_telegram_delivery q WHERE q.event_key=e.event_key)" if 'azt_telegram_delivery' in tables else '1'
        rows = con.execute(
            "SELECT e.payload_json FROM azt_stop_events e WHERE "
            f"(e.scope='personal' AND {owner_missing}) OR "
            f"(e.scope LIKE 'client:%' AND {client_missing}) "
            "ORDER BY e.observed_utc,e.event_key LIMIT ?",
            (max(1, min(25, int(limit))),)).fetchall()
    return [json.loads(row['payload_json']) for row in rows]


def observe_stored_stop_updates(*, database=None):
    """Observe persisted snapshots from an older EXE without attaching MT5.

    The first external observation is a silent baseline. New EXE ingests and this
    optional observer use identical event keys, so they cannot duplicate a change.
    """
    events=[]
    with _connection(database) as con:
        con.execute('BEGIN IMMEDIATE')
        currencies={(row['scope'],row['account_key']):json.loads(row['account_json']).get('currency') or 'UNKNOWN' for row in con.execute('SELECT * FROM azt_account_snapshots')}
        active=[]
        for record in con.execute("SELECT * FROM azt_trades WHERE kind='OPEN'").fetchall():
            scope,key,ticket=record['scope'],record['account_key'],record['ticket']
            active.append((scope,key,ticket))
            current=json.loads(record['payload_json'])
            prior=con.execute('SELECT * FROM azt_stop_observations WHERE scope=? AND account_key=? AND ticket=?',(scope,key,ticket)).fetchone()
            if prior and record['observed_utc'] > prior['observed_utc']:
                # A new producer may have observed this change before a later,
                # unchanged snapshot reached the external observer. Its durable
                # event remains authoritative even when observation times differ.
                recorded = con.execute(
                    "SELECT 1 FROM azt_stop_events WHERE scope=? AND account_key=? AND ticket=? "
                    "AND observed_utc>? AND observed_utc<=? AND json_extract(payload_json,'$.new_sl') IS ? LIMIT 1",
                    (scope, key, ticket, prior['observed_utc'], record['observed_utc'], current.get('sl'))).fetchone()
                event = None if recorded else _stop_event(con,scope,key,json.loads(prior['payload_json']),current,record['observed_utc'],currencies.get((scope,key),'UNKNOWN'))
                if event:
                    events.append(event)
            if prior is None or record['observed_utc'] > prior['observed_utc']:
                con.execute('INSERT INTO azt_stop_observations VALUES(?,?,?,?,?) ON CONFLICT(scope,account_key,ticket) DO UPDATE SET observed_utc=excluded.observed_utc,payload_json=excluded.payload_json',(scope,key,ticket,record['observed_utc'],record['payload_json']))
        active=set(active)
        for old in con.execute('SELECT scope,account_key,ticket FROM azt_stop_observations').fetchall():
            identity=(old['scope'],old['account_key'],old['ticket'])
            if identity not in active:
                con.execute('DELETE FROM azt_stop_observations WHERE scope=? AND account_key=? AND ticket=?',identity)
    return events


def ingest_snapshot(client_id, account_key, snapshot, *, database=None):
    key = str(account_key).strip()
    if not key or len(key) > 200:
        raise ValueError("A scoped account key is required.")
    observed = utc_iso(snapshot.get("observed_utc"))
    account = snapshot.get("account") or {}
    try:
        login = int(account.get("login", 0))
    except (TypeError, ValueError):
        raise ValueError("Telemetry account identity is invalid.") from None
    server = str(account.get("server") or "").strip()
    if login <= 0 or not server or key != f"{server}|{login}":
        raise ValueError("Telemetry does not match the scoped MT5 account.")
    # Explicit allow-list: never persist passwords or arbitrary client objects.
    summary = {name: account.get(name) for name in ("login", "server", "currency", "balance", "equity", "margin", "margin_free")}
    for name in ("balance", "equity", "margin", "margin_free"):
        summary[name] = _number(summary[name], None)
    positions = [_trade(row, "OPEN") for row in list(snapshot.get("positions") or [])[:1000]]
    history = sorted(list(snapshot.get("trades") or []), key=lambda row: utc_iso(row["closed_utc"]) if row.get("closed_utc") else "", reverse=True)
    trades = [_trade(row, "CLOSED") for row in history[:5000]]
    scope = _scope(client_id)
    new_closed, new_open, new_stop_updates = [], [], []
    with _connection(database) as con:
        con.execute("BEGIN IMMEDIATE")
        previous = con.execute("SELECT observed_utc,first_observed_utc,account_json FROM azt_account_snapshots WHERE scope=? AND account_key=?", (scope, key)).fetchone()
        if previous and observed <= previous["observed_utc"]:
            return {"accepted": False, "new_closed": [], "new_open": [], "new_stop_updates": []}
        prior_summary = json.loads(previous["account_json"]) if previous else {}
        history_sync = snapshot.get("history_sync", "UNKNOWN")
        if not isinstance(history_sync, str) or history_sync not in {"OK", "DEGRADED", "UNAVAILABLE", "UNKNOWN"}:
            raise ValueError("Invalid history synchronization status.")
        summary["history_sync"] = history_sync
        failures = snapshot.get("history_window_failures", 0)
        if type(failures) is not int or not 0 <= failures <= 2:
            raise ValueError("Invalid history window failure count.")
        summary["history_window_failures"] = failures
        if history_sync == "UNAVAILABLE":
            trades = []
        # A failed poll must not overwrite the last verified history refresh.
        summary["history_last_success_utc"] = observed if history_sync in {"OK", "DEGRADED"} else prior_summary.get("history_last_success_utc")
        summary["history_last_full_utc"] = observed if history_sync == "OK" else prior_summary.get("history_last_full_utc")
        previous_open = {row["ticket"]: json.loads(row["payload_json"]) for row in con.execute("SELECT ticket,payload_json FROM azt_trades WHERE scope=? AND account_key=? AND kind='OPEN'", (scope, key))}
        execution_details = {row["ticket"]: json.loads(row["details_json"]) for row in con.execute("SELECT ticket,details_json FROM azt_execution_details WHERE scope=? AND account_key=?", (scope, key))}
        for row in positions + trades:
            details = execution_details.get(row["position_id"], execution_details.get(row["ticket"], {}))
            for name in ("sl", "tp", "risk_pct", "risk_cash", "portfolio_after_pct", "max_open_risk_pct", "executed_utc"):
                if row.get(name) is None and details.get(name) is not None:
                    row[name] = details[name]
            if row["strategy"] == "—" and details.get("strategy"):
                row["strategy"] = details["strategy"]
            if row.get('entry') is None and details.get('entry') is not None:
                row['entry'] = details['entry']
                row['entry_basis'] = details.get('entry_basis','')
        baseline = (previous["first_observed_utc"] or previous["observed_utc"]) if previous else observed
        for row in trades:
            if history_sync == "DEGRADED":
                row["history_partial"] = True
            prior = previous_open.get(row["position_id"], {})
            for name in ("entry", "sl", "tp", "risk_pct", "opened_utc"):
                if row.get(name) is None and prior.get(name) is not None:
                    row[name] = prior[name]
            if row["strategy"] == "—" and prior.get("strategy"):
                row["strategy"] = prior["strategy"]
            existing = con.execute(
                """SELECT json_extract(payload_json,'$.history_partial') FROM azt_trades
                   WHERE scope=? AND account_key=? AND kind='CLOSED' AND ticket=?""",
                (scope, key, row["ticket"]),
            ).fetchone()
            # First snapshot is history synchronization, not a burst of old alerts.
            if previous and history_sync != "DEGRADED" and (existing is None or existing[0]) and row["closed_utc"] >= baseline:
                new_closed.append(row)
        for row in positions:
            if previous and row["ticket"] not in previous_open and row.get("opened_utc") and row["opened_utc"] >= baseline:
                new_open.append(row)
            elif previous and row['ticket'] in previous_open:
                event=_stop_event(con,scope,key,previous_open[row['ticket']],row,observed,summary.get('currency'))
                if event:
                    new_stop_updates.append(event)
        con.execute("INSERT INTO azt_account_snapshots(scope,account_key,observed_utc,account_json,first_observed_utc) VALUES(?,?,?,?,?) ON CONFLICT(scope,account_key) DO UPDATE SET observed_utc=excluded.observed_utc,account_json=excluded.account_json", (scope, key, observed, json.dumps(summary, allow_nan=False), baseline))
        con.execute("DELETE FROM azt_trades WHERE scope=? AND account_key=? AND kind='OPEN'", (scope, key))
        for kind, rows in (("OPEN", positions), ("CLOSED", trades)):
            # A recent-only query may miss opening deals and their costs. Keep
            # stored closes intact until a complete poll can reconcile them.
            on_conflict = ("DO NOTHING" if kind == "CLOSED" and history_sync == "DEGRADED"
                           else "DO UPDATE SET payload_json=excluded.payload_json,observed_utc=excluded.observed_utc")
            for row in rows:
                con.execute("INSERT INTO azt_trades VALUES(?,?,?,?,?,?) ON CONFLICT(scope,account_key,kind,ticket) " + on_conflict, (scope, key, kind, row["ticket"], json.dumps(row, allow_nan=False), observed))
    for row in new_open + new_closed:
        row.update(account_key=key, currency=summary.get("currency") or "UNKNOWN", observed_utc=observed, client_id=client_id)
    return {"accepted": True, "new_closed": new_closed, "new_open": new_open, "new_stop_updates": new_stop_updates}


def list_trades(client_id=None, *, account_key=None, state=None, limit=500, database=None):
    clauses, params = [], []
    # None means owner-wide view. Personal-only callers can set account_key.
    if client_id is not None:
        clauses.append("scope=?")
        params.append(_scope(client_id))
    if account_key:
        clauses.append("account_key=?")
        params.append(str(account_key))
    if state:
        clauses.append("kind=?")
        params.append("OPEN" if str(state).upper() in {"OPEN", "FLOATING"} else "CLOSED")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with _connection(database) as con:
        records = con.execute("SELECT * FROM azt_trades" + where + " ORDER BY COALESCE(json_extract(payload_json,'$.closed_utc'),json_extract(payload_json,'$.opened_utc'),observed_utc) DESC LIMIT ?", (*params, min(5000, max(1, int(limit))))).fetchall()
        currencies = {(row["scope"], row["account_key"]): json.loads(row["account_json"]).get("currency") or "UNKNOWN"
                      for row in con.execute("SELECT * FROM azt_account_snapshots")}
    rows = []
    for record in records:
        row = json.loads(record["payload_json"])
        row.update(account_key=record["account_key"], client_id=int(record["scope"].split(":")[1]) if record["scope"].startswith("client:") else None, observed_utc=record["observed_utc"])
        row["currency"] = currencies.get((record["scope"], record["account_key"]), "UNKNOWN")
        rows.append(row)
    return sorted(rows, key=lambda row: row.get("closed_utc") or row.get("opened_utc") or "", reverse=True)


def daily_journal(client_id=None, date=None, timezone="UTC", *, account_key=None, database=None):
    zone = ZoneInfo(timezone)
    day = datetime.fromisoformat(str(date)).date() if date else datetime.now(zone).date()
    rows = [row for row in list_trades(client_id, account_key=account_key, state="CLOSED", limit=5000, database=database)
            if datetime.fromisoformat(row["closed_utc"]).astimezone(zone).date() == day]
    position_results, position_risks = {}, {}
    for row in rows:
        key = (row["account_key"], row["position_id"])
        position_results[key] = position_results.get(key, 0) + row["pnl"]
        if row.get("risk_pct") is not None:
            position_risks[key] = row["risk_pct"]
    wins, losses = sum(value > 0 for value in position_results.values()), sum(value < 0 for value in position_results.values())
    known_risk = list(position_risks.values())
    pnl_by_currency = {}
    for row in rows:
        pnl_by_currency[row["currency"]] = pnl_by_currency.get(row["currency"], 0) + row["pnl"]
    return {"date": day.isoformat(), "timezone": timezone, "trades_taken": len(position_results), "closed_deals": len(rows), "wins": wins,
            "losses": losses, "pnl": round(sum(row["pnl"] for row in rows), 8) if len(pnl_by_currency) <= 1 else None,
            "pnl_by_currency": pnl_by_currency,
            "win_rate": 100 * wins / len(position_results) if position_results else 0,
            "risk_used": sum(known_risk) if known_risk else None,
            "strategies_used": sorted({row["strategy"] for row in rows if row["strategy"] != "—"}), "trades": rows}


def account_snapshots(client_id=None, *, database=None):
    with _connection(database) as con:
        rows = con.execute("SELECT * FROM azt_account_snapshots" + (" WHERE scope=?" if client_id is not None else ""), (_scope(client_id),) if client_id is not None else ()).fetchall()
    return [dict(json.loads(row["account_json"]), account_key=row["account_key"], observed_utc=row["observed_utc"]) for row in rows]


def overview(client_id=None, timezone="UTC", *, database=None):
    accounts = account_snapshots(client_id, database=database)
    positions = list_trades(client_id, state="OPEN", database=database)
    journal = daily_journal(client_id, timezone=timezone, database=database)
    floating_by_currency = {}
    for row in positions:
        floating_by_currency[row["currency"]] = floating_by_currency.get(row["currency"], 0) + row["pnl"]
    return {"accounts": accounts, "positions": positions, "open_positions": len(positions),
            "floating_pnl": sum(row["pnl"] for row in positions) if len(floating_by_currency) <= 1 else None,
            "floating_pnl_by_currency": floating_by_currency, "today_pnl": journal["pnl"], "today_pnl_by_currency": journal["pnl_by_currency"],
            "journal": journal, "recent_trades": list_trades(client_id, state="CLOSED", limit=20, database=database)}


def capture_mt5(api, *, clock_offset_seconds=0, lookback_days=30):
    """Snapshot an already attached, verified account. Does not initialize MT5.

    Pass the connection's calibrated raw-feed-minus-UTC offset. No historical
    time is re-labelled as local time or adjusted using an old candle.
    """
    account = api.account_info()
    terminal = api.terminal_info()
    if account is None or terminal is None or not bool(getattr(terminal, "connected", False)):
        raise RuntimeError("MT5 telemetry unavailable while disconnected.")
    if not isinstance(getattr(account, "login", None), int):
        raise RuntimeError("MT5 telemetry requires a real verified account identity.")
    now = datetime.now(utc_timezone.utc)
    positions = api.positions_get()
    if positions is None:
        raise RuntimeError("MT5 open positions unavailable; last snapshot retained.")

    # MT5 broker feeds may encode their wall-clock time in raw epoch seconds.
    # The timestamp() function below subtracts the calibrated feed offset.
    # The HISTORY QUERY needs the same offset, or a deal closed now can lie
    # outside the request's UTC end and today's results appear to be missing.
    if not isinstance(clock_offset_seconds, (int, float)) or not math.isfinite(clock_offset_seconds) or abs(clock_offset_seconds) > 14 * 3600:
        raise ValueError("Invalid calibrated MT5 broker offset.")
    feed_now = now + timedelta(seconds=clock_offset_seconds)
    periods = (
        (feed_now - timedelta(days=max(1, min(365, lookback_days))), feed_now + timedelta(minutes=2)),
        (feed_now - timedelta(days=2), feed_now + timedelta(minutes=2)),
    )
    deals = ()
    failed_windows = 0
    for start, end in periods:
        try:
            result = api.history_deals_get(start, end)
        except (RuntimeError, OSError, ValueError):
            result = None
        if result is None:
            failed_windows += 1
            continue
        deals = result
        break
    history_status = "OK" if failed_windows == 0 else "DEGRADED" if failed_windows < len(periods) else "UNAVAILABLE"
    # Even when both history ranges fail, open positions must be refreshed;
    # existing closed deals remain in the DB and will be reconciled later.

    def timestamp(item, name="time"):
        value = float(getattr(item, name, 0) or 0)
        return utc_iso(value - clock_offset_seconds) if value > 0 else None
    def strategy(item):
        comment = str(getattr(item, "comment", "") or "")
        return comment.split(":", 1)[1] if comment.startswith(("GOLD_AI:", "AZT:")) else "—"
    open_rows = []
    for item in positions:
        order_type = int(getattr(api,'ORDER_TYPE_BUY',0)) if int(item.type)==int(api.POSITION_TYPE_BUY) else int(getattr(api,'ORDER_TYPE_SELL',1))
        def price_pnl(price):
            try:
                if not math.isfinite(float(price)) or float(price)<=0:
                    return None
                value=api.order_calc_profit(order_type,str(item.symbol),float(item.volume),float(item.price_open),float(price))
                return _number(value,None)
            except (AttributeError, OSError, TypeError, ValueError, OverflowError, RuntimeError):
                return None
        open_rows.append({"ticket": str(item.ticket), "position_id": str(item.ticket), "symbol": str(item.symbol),
                          "direction": "BUY" if int(item.type) == int(api.POSITION_TYPE_BUY) else "SELL",
                          "volume": float(item.volume), "entry": float(item.price_open),
                          "current_price": float(item.price_current), "sl": float(item.sl), "tp": float(item.tp),
                          "pnl": float(item.profit) + float(getattr(item, "swap", 0) or 0),
                          "sl_pnl": price_pnl(item.sl), "tp_pnl": price_pnl(item.tp),
                          "entry_basis": 'ACTUAL_FILL',
                          "strategy": strategy(item), "opened_utc": timestamp(item)})
    grouped = {}
    for deal in deals:
        if int(getattr(deal, "type", -1)) not in {int(getattr(api, "DEAL_TYPE_BUY", 0)), int(getattr(api, "DEAL_TYPE_SELL", 1))}:
            continue
        grouped.setdefault(str(deal.position_id), []).append(deal)
    closed = []
    open_ids = {row["position_id"] for row in open_rows}
    for position_id, group in grouped.items():
        entries = [deal for deal in group if int(getattr(deal, "entry", -1)) in {int(getattr(api, "DEAL_ENTRY_IN", 0)), int(getattr(api, "DEAL_ENTRY_INOUT", 2))}]
        exits = [deal for deal in group if int(getattr(deal, "entry", -1)) in {int(getattr(api, "DEAL_ENTRY_OUT", 1)), int(getattr(api, "DEAL_ENTRY_OUT_BY", 3))}]
        if not exits:
            continue
        first = min(entries or group, key=lambda item: item.time)
        volume_in = sum(float(item.volume) for item in entries)
        entry_cost = sum(float(getattr(item, field, 0) or 0) for item in entries for field in ("commission", "swap", "fee"))
        volume_closed = 0
        for last in sorted(exits, key=lambda item: item.time):
            # Each confirmed exit deal is immutable. This includes realized PnL
            # from partial closes while the rest remains in the open-position view.
            portion = min(1, float(last.volume) / volume_in) if volume_in > 0 else 0
            volume_closed += float(last.volume)
            partial = volume_closed + 1e-8 < volume_in if volume_in > 0 else position_id in open_ids
            pnl = sum(float(getattr(last, field, 0) or 0) for field in ("profit", "commission", "swap", "fee")) + entry_cost * portion
            closed.append({"ticket": str(getattr(last, "ticket", position_id)), "position_id": position_id, "symbol": str(first.symbol),
                           "direction": "SELL" if int(last.type) == int(getattr(api, "DEAL_TYPE_BUY", 0)) else "BUY",
                           "volume": float(last.volume), "entry": sum(float(item.price) * float(item.volume) for item in entries) / volume_in if volume_in > 0 else None,
                           "exit": float(last.price), "pnl": pnl, "profit": pnl, "strategy": strategy(first),
                           "opened_utc": timestamp(first) if entries else None, "closed_utc": timestamp(last),
                           "is_partial_close": partial,
                           "notes": "Partial close; remaining volume was retained at this exit." if partial else "",
                           "close_reason": {int(getattr(api, "DEAL_REASON_SL", 4)): "SL HIT", int(getattr(api, "DEAL_REASON_TP", 5)): "TP HIT", int(getattr(api, "DEAL_REASON_SO", 6)): "STOP OUT"}.get(int(getattr(last, "reason", -1)), "")})
    summary = {name: getattr(account, name, None) for name in ("login", "server", "currency", "balance", "equity", "margin", "margin_free")}
    return {"observed_utc": now.isoformat(), "account": summary, "positions": open_rows, "trades": closed,
            "history_sync": history_status, "history_window_failures": failed_windows}
