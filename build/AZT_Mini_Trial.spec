# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
ROOT = Path(SPECPATH).resolve().parent
ENTRY = str(ROOT / "mini_trial" / "entry.py")
a = Analysis(
    [ENTRY], pathex=[str(ROOT)], binaries=[], datas=[],
    hiddenimports=[
        "mini_trial.entry", "mini_trial.gui", "mini_trial.manager", "mini_trial.clock",
        "server.admin_launcher", "server.personal_worker", "server.personal_store",
        "server.signal_engine", "server.hosted_executor", "server.store", "server.azt_store",
        "server.trade_telemetry", "server.client_notifications", "server.telegram_notifications",
        "broker.mt5_client", "broker.clock", "strategies", "MetaTrader5", "pandas", "numpy"],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="AZT_Mini_Trial",
          console=False, debug=False, bootloader_ignore_signals=False, strip=False, upx=False)
