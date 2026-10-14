# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["../server/admin_gui.py"],
    pathex=[".."],
    binaries=[],
    datas=[],
    hiddenimports=["server.store"],
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
