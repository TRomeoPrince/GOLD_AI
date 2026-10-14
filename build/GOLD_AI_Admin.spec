# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

PROJECT_ROOT = str(Path(SPECPATH).resolve().parent)
ENTRYPOINT = str(Path(PROJECT_ROOT) / "server" / "admin_gui.py")

a = Analysis(
    [ENTRYPOINT],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=["server", "server.store"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GOLD_AI_Admin",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
