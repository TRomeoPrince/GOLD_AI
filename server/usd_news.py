"""Always-on USD high-impact event guard; manual News Lock is independent.

The public weekly Forex Factory export is fetched at most once per 30 minutes.
Dates MUST have timezone offsets. On a missing/stale/unparseable feed, fail
closed for new entries while preserving each account's desired running state.
Existing broker positions are never touched.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import threading
import time
from urllib.request import Request, urlopen

SOURCE = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
REFRESH_SECONDS = 30 * 60
MAX_STALE_SECONDS = 2 * 60 * 60
NEWS_WINDOW = timedelta(minutes=20)

_lock = threading.Lock()
_events = ()
_fetched_monotonic = None
_next_check = 0.0
_last_error = "Calendar not loaded."


def _parse_events(raw):
    if not isinstance(raw, list):
        raise ValueError("Calendar JSON is not an event array.")
    if not raw:
        raise ValueError("Calendar has no events; refuse an unverified empty week.")
    events = []
    for event in raw:
        if not isinstance(event, dict):
            continue
        if str(event.get("country", "")).strip().upper() != "USD":
            continue
        impact = str(event.get("impact", "")).strip().casefold()
        if impact not in {"high", "red", "3"}:
            continue
        title = str(event.get("title", "High-impact USD event")).strip()[:160]
        date = str(event.get("date", ""))
        try:
            stamp = datetime.fromisoformat(date.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("Calendar event timezone missing.")
            stamp = stamp.astimezone(timezone.utc)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"High-impact USD event has no reliable schedule: {title}") from exc
        events.append((stamp, title))
    return tuple(sorted(events))


def _download():
    request = Request(SOURCE, headers={"User-Agent": "AZT-USD-NewsGuard/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=4) as response:
        if int(response.status) != 200:
            raise ValueError("Unexpected economic calendar HTTP response.")
        raw = json.loads(response.read(512 * 1024))
    return _parse_events(raw)


def block_status(now=None):
    """Return (blocked, reason), inclusive 20m before and after each event."""
    global _events, _fetched_monotonic, _next_check, _last_error
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("News checks require timezone-aware UTC timestamps.")
    now = now.astimezone(timezone.utc)
    monotonic = time.monotonic()
    with _lock:
        if monotonic >= _next_check:
            _next_check = monotonic + REFRESH_SECONDS
            try:
                _events = _download()
                _fetched_monotonic = monotonic
                _last_error = ""
            except (OSError, ValueError, json.JSONDecodeError, TimeoutError) as exc:
                _last_error = f"{type(exc).__name__}: {exc}"
                logging.warning("USD news calendar unavailable (%s). New entries will be blocked if cache expires.", _last_error)
        if _fetched_monotonic is None or monotonic - _fetched_monotonic > MAX_STALE_SECONDS:
            return True, "USD_NEWS_CALENDAR_UNAVAILABLE: new entries blocked until feed recovery."
        # A weekly feed must include today's date in its week (Monday-Sunday).
        # Refresh failures are tolerated briefly, but not across feed weeks.
        for when, title in _events:
            if abs(now - when) <= NEWS_WINDOW:
                return True, f"HIGH_IMPACT_USD_NEWS: {title} at {when.isoformat()} (20m either side)."
    return False, ""
