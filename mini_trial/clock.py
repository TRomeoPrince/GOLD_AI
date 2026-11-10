"""Fail-closed HTTPS internet clock for the fixed-date AZT Mini trial."""
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from threading import Lock
import time
import urllib.request

EXPIRES_UTC = datetime(2026, 11, 17, 21, 0, tzinfo=timezone.utc)
CLOCK_URLS = ("https://www.google.com/generate_204", "https://www.cloudflare.com/cdn-cgi/trace")
CACHE_SECONDS = 25
_lock = Lock()
_verified_utc = None
_verified_monotonic = 0.0

class ClockUnavailable(RuntimeError):
    pass

class TrialExpired(RuntimeError):
    pass

def fetch_internet_utc(opener=None):
    opener = opener or urllib.request.urlopen
    for url in CLOCK_URLS:
        try:
            request = urllib.request.Request(url, headers={"User-Agent":"AZT-Mini-Trial/1.0","Cache-Control":"no-cache"})
            with opener(request, timeout=7) as response:
                raw = response.headers.get("Date")
            if not raw:
                continue
            value = parsedate_to_datetime(raw)
            if value.tzinfo is not None:
                return value.astimezone(timezone.utc)
        except (OSError, ValueError, TypeError, TimeoutError):
            continue
    raise ClockUnavailable("Cannot verify internet UTC over HTTPS. Trading is blocked.")

def verified_now(*, force=False, fetcher=None):
    global _verified_utc, _verified_monotonic
    with _lock:
        monotonic = time.monotonic()
        if not force and _verified_utc is not None and 0 <= monotonic - _verified_monotonic <= CACHE_SECONDS:
            return _verified_utc + timedelta(seconds=monotonic-_verified_monotonic)
        now = (fetcher or fetch_internet_utc)()
        if now.tzinfo is None:
            raise ClockUnavailable("Untrusted timestamp.")
        now = now.astimezone(timezone.utc)
        if _verified_utc is not None and now < _verified_utc - timedelta(seconds=120):
            raise ClockUnavailable("Internet clock moved backwards; trading blocked.")
        _verified_utc, _verified_monotonic = now, monotonic
        return now

def require_active(*, force=False, fetcher=None):
    now = verified_now(force=force, fetcher=fetcher)
    if now >= EXPIRES_UTC:
        raise TrialExpired("AZT Mini expired on 17 November 2026, 23:59 EAT.")
    return now

def reset_cache_for_tests():
    global _verified_utc, _verified_monotonic
    with _lock:
        _verified_utc, _verified_monotonic = None, 0.0
