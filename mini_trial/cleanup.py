"""Start only the Inno Setup uninstaller; never delete MT5 or trade data."""
import subprocess
import sys
from pathlib import Path

def start_uninstall():
    exe = Path(sys.executable).resolve().parent / "unins000.exe"
    helper = exe.parent / "expire_uninstall.cmd"
    if not exe.is_file() or not helper.is_file():
        return False
    subprocess.Popen(["cmd.exe","/d","/c",str(helper)],cwd=str(exe.parent),
                     creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    return True
