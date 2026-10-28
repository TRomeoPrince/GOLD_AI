# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

PROJECT_ROOT = str(Path(SPECPATH).resolve().parent)
ENTRYPOINT = str(Path(PROJECT_ROOT) / "server" / "admin_launcher.py")

a = Analysis(
    [ENTRYPOINT],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[(str(Path(PROJECT_ROOT) / 'IMAGES'), 'IMAGES')],
    hiddenimports=["server", "server.store", "server.credential_vault", "server.hosted_manager", "server.admin_gui", "server.app", "server.signal_engine", "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on"],
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
    name="AZT_Admin",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
