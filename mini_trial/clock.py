"""14-day AZT Mini lease starting on the first verified internet-UTC launch.

No owner server/pairing needed. HTTPS time gates every trade while a durable
per-user lease survives uninstall/reinstall. The PC's wall clock grants no time.
"""
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import Lock
import json
import os
import time
import urllib.request

TRIAL_DAYS = 14
TRIAL_LENGTH = timedelta(days=TRIAL_DAYS)
CLOCK_URLS = ("https://www.google.com/generate_204",
              "https://www.cloudflare.com/cdn-cgi/trace")
CACHE_SECONDS = 25
_lock = Lock()
_lease_lock = Lock()
_verified_utc = None
_verified_monotonic = 0.0


class ClockUnavailable(RuntimeError):
    pass


class TrialExpired(RuntimeError):
    pass


def lease_path(override=None):
    if override is not None:
        return Path(override)
    root = os.environ.get("GOLD_AI_STATE_DIR")
    if not root:
        root = str(Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
                   / "AZT_Mini_14Day_Trial" / "state")
    return Path(root) / "trial_lease.json"


def _parse_utc(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("UTC timezone required")
        return stamp.astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise ClockUnavailable("Mini trial state has an invalid UTC timestamp; trading blocked.") from exc


def load_lease(*, path=None):
    """Read-only: importantly, scheduled expiry checks never activate a trial."""
    target = lease_path(path)
    if not target.exists():
        return None
    try:
        lease = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(lease, dict) or lease.get("edition") != "AZT_MINI_14":
            raise ValueError("Invalid edition")
        first = _parse_utc(lease["activated_utc"])
        expiry = _parse_utc(lease["expires_utc"])
        if expiry - first != TRIAL_LENGTH:
            raise ValueError("Unexpected trial duration")
        return {"activated_utc": first, "expires_utc": expiry}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ClockUnavailable("Mini trial activation record is damaged; trading blocked. Contact AZT support.") from exc


def start_lease(now, *, path=None):
    target = lease_path(path)
    with _lease_lock:
        previous = load_lease(path=target)
        if previous is not None:
            return previous
        target.parent.mkdir(parents=True, exist_ok=True)
        record = {"edition": "AZT_MINI_14", "activated_utc": now.isoformat(),
                  "expires_utc": (now + TRIAL_LENGTH).isoformat()}
        # O_EXCL avoids restarting a trial if two workers race first activation.
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return load_lease(path=target)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(record, file, sort_keys=True)
            file.flush()
            os.fsync(file.fileno())
        return {"activated_utc": now, "expires_utc": now + TRIAL_LENGTH}


def fetch_internet_utc(opener=None):
    opener = opener or urllib.request.urlopen
    for url in CLOCK_URLS:
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "AZT-Mini-Trial/2.0",
                              "Cache-Control": "no-cache"})
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


def require_active(*, force=False, fetcher=None, path=None):
    """First valid internet UTC call activates trial; fail closed at exact 14 days."""
    now = verified_now(force=force, fetcher=fetcher)
    record = start_lease(now, path=path)
    if now >= record["expires_utc"]:
        raise TrialExpired("AZT Mini 14-day trial expired at "
                           + record["expires_utc"].strftime("%Y-%m-%d %H:%M UTC") + ".")
    return now


def expired_existing_lease(*, fetcher=None, path=None):
    """Expiry-check task can uninstall an activated lease, never start a new one."""
    record = load_lease(path=path)
    if record is None:
        return False
    return verified_now(force=True, fetcher=fetcher) >= record["expires_utc"]


def reset_cache_for_tests():
    global _verified_utc, _verified_monotonic
    with _lock:
        _verified_utc, _verified_monotonic = None, 0.0
