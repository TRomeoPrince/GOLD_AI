"""Standalone EXE DB startup regression; no MT5, Telegram, or live trades."""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from server import admin_launcher, store


class StandaloneDBTests(unittest.TestCase):
    def test_frozen_downloads_uses_persistent_appdata_not_downloads_parent(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            downloads = base / "Downloads"
            downloads.mkdir()
            exe = downloads / "AZT_Admin.exe"
            exe.touch()
            state = base / "LocalAppData"
            saved = Path.cwd()
            try:
                with patch.object(sys, "frozen", True, create=True), \
                     patch.object(sys, "executable", str(exe)), \
                     patch.dict(os.environ, {"LOCALAPPDATA": str(state)}, clear=False):
                    for name in ("GOLD_AI_HOME", "GOLD_AI_DB_PATH", "GOLD_AI_STATE_DIR", "GOLD_AI_PROJECT_ROOT"):
                        os.environ.pop(name, None)
                    root = admin_launcher.configure()
                    expected = state / "GOLD_AI"
                    self.assertEqual(root, expected)
                    self.assertTrue((root / "server").is_dir())
                    self.assertEqual(Path(os.environ["GOLD_AI_DB_PATH"]), root / "server" / "gold_ai_server.db")
                    self.assertFalse((downloads / "server").exists())
                    with patch.object(store, "DB_PATH", root / "server" / "gold_ai_server.db"):
                        with store.connect() as con:
                            self.assertEqual(con.execute("SELECT value FROM server_settings WHERE key='news_lock'").fetchone()[0], "0")
            finally:
                os.chdir(saved)

    def test_existing_legacy_database_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AMD1"
            old = root / "server"
            old.mkdir(parents=True)
            db = old / "gold_ai_server.db"
            with sqlite3.connect(db) as con:
                con.execute("CREATE TABLE preserve_me(x INTEGER)")
                con.execute("INSERT INTO preserve_me VALUES(123456)")
            dist = root / "dist_telegram_style"
            dist.mkdir()
            exe = dist / "AZT_Admin.exe"
            exe.touch()
            saved = Path.cwd()
            try:
                with patch.object(sys,"frozen",True,create=True), \
                     patch.object(sys,"executable",str(exe)), \
                     patch.dict(os.environ, {"LOCALAPPDATA": str(Path(td)/"NewLocal")},clear=False):
                    for name in ("GOLD_AI_HOME", "GOLD_AI_DB_PATH", "GOLD_AI_STATE_DIR", "GOLD_AI_PROJECT_ROOT"):
                        os.environ.pop(name, None)
                    selected = admin_launcher.configure()
                    self.assertEqual(selected,root)
                    self.assertEqual(Path(os.environ["GOLD_AI_DB_PATH"]),db)
                    with sqlite3.connect(db) as con:
                        self.assertEqual(con.execute("SELECT x FROM preserve_me").fetchone()[0],123456)
            finally:
                os.chdir(saved)

    def test_store_connect_creates_explicit_nested_parent(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "new" / "nested" / "owner.db"
            with patch.object(store,"DB_PATH",db):
                with store.connect() as con:
                    self.assertIsNotNone(con.execute("SELECT name FROM sqlite_master WHERE name='clients'").fetchone())
            self.assertTrue(db.is_file())


if __name__ == "__main__":
    unittest.main()
