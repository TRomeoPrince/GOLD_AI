"""Atomic JSON replacement with bounded Windows sharing-lock retries."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
import time


class FileBusyError(PermissionError):
    """The destination remained locked after all replacement attempts."""


def atomic_write_json(path: Path, value, *, attempts=7):
    if attempts < 1:
        raise ValueError("attempts must be positive")
    # Serialize before touching files; refuse NaN/Infinity and partial JSON.
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.stem + ".", suffix=".tmp", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(attempts):
            try:
                os.replace(temp, path)
                return
            except OSError as exc:
                if not isinstance(exc, PermissionError) and getattr(exc, "winerror", None) not in {5, 32, 33}:
                    raise
                if attempt == attempts - 1:
                    raise FileBusyError(f"JSON destination stayed locked after {attempts} attempts: {path}") from exc
                time.sleep(min(.02 * 2 ** attempt, .25))
    finally:
        # The unique temp is ours only. Never remove or truncate the live target.
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            import logging
            logging.warning("Could not remove temporary JSON file %s", temp, exc_info=True)
