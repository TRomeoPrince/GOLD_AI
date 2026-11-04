"""Single executable entry point. Services use private stdin for cooperative shutdown."""
from __future__ import annotations
import os
import sys
import threading
import subprocess
import socket
import time
from pathlib import Path
from contextlib import contextmanager


@contextmanager
def external_runtime(external):
    """Prevent frozen DLLs from leaking into the separate Python runtime."""
    reset=external and os.name=='nt' and getattr(sys,'frozen',False)
    if reset:
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.SetDllDirectoryW.argtypes=[ctypes.c_wchar_p]
        kernel.SetDllDirectoryW.restype=ctypes.c_int
        if not kernel.SetDllDirectoryW(None):
            raise OSError('Could not prepare external Telegram runtime.')
    try:
        yield
    finally:
        if reset:
            kernel.SetDllDirectoryW(str(sys._MEIPASS))


def owner_home():
    """Select persistent owner data independently of the executable location."""
    explicit = os.getenv("GOLD_AI_HOME", "").strip()
    override_db = os.getenv("GOLD_AI_DB_PATH", "").strip()
    if explicit:
        root = Path(explicit).expanduser().resolve()
    elif override_db:
        parent = Path(override_db).expanduser().resolve().parent
        root = parent.parent if parent.name.lower() == "server" else parent
    else:
        checkout = Path(__file__).resolve().parents[1]
        frozen = getattr(sys, "frozen", False)
        exe = Path(sys.executable).resolve()
        appdata = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "GOLD_AI"
        candidates = ((
            exe.parent.parent,
            exe.parent,
            Path.cwd(),
            Path.home() / "Desktop" / "Bots" / "Forex" / "AMD1",
            appdata,
        ) if frozen else (checkout, appdata))
        root = next((folder for folder in candidates
                     if (folder / "server" / "gold_ai_server.db").is_file()), None)
        if root is None:
            root = next((folder for folder in candidates
                         if (folder / ".env").is_file() and (folder / "server").is_dir()), None)
        if root is None:
            root = appdata if frozen else checkout
    return root.resolve()


def configure():
    root = owner_home()
    root.mkdir(parents=True, exist_ok=True)
    from dotenv import load_dotenv
    load_dotenv(root / ".env", override=False)
    state = Path(os.environ.get("GOLD_AI_STATE_DIR") or root / "server").expanduser().resolve()
    override_db = os.getenv("GOLD_AI_DB_PATH", "").strip()
    db = Path(override_db).expanduser().resolve() if override_db else state / "gold_ai_server.db"
    # Fail with a useful permissions error rather than sqlite3.OperationalError.
    state.mkdir(parents=True, exist_ok=True)
    db.parent.mkdir(parents=True, exist_ok=True)
    os.environ["GOLD_AI_DB_PATH"] = str(db)
    os.environ["GOLD_AI_STATE_DIR"] = str(state)
    os.environ.setdefault("GOLD_AI_PROJECT_ROOT", str(root))
    os.chdir(root)
    return root


def telegram_source(root):
    explicit = os.getenv("AZT_TELEGRAM_SOURCE_ROOT", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    exe = Path(sys.executable).resolve()
    candidates = (root, exe.parent.parent, exe.parent) if getattr(sys, "frozen", False) else (root, Path(__file__).resolve().parents[1])
    return next((path for path in candidates
                 if (path / "server/admin_launcher.py").is_file()
                 and (path / ".venv/Scripts/python.exe").is_file()), root)

def worker(name):
    if getattr(sys, "frozen", False):
        # Windowed PyInstaller sets standard streams to None, even with redirected handles.
        import ctypes
        import msvcrt
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetStdHandle.restype = ctypes.c_void_p
        handle = kernel.GetStdHandle(-10)
        sys.stdin = os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY), "r")
        log = Path.cwd() / "logs" / (name + ".log")
        log.parent.mkdir(exist_ok=True)
        sys.stdout = sys.stderr = open(log, "a", encoding="utf-8", buffering=1)
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    logging.info("Starting background service: %s", name)
    if os.getenv("GOLD_AI_TEST_DIAGNOSTICS") == "1":
        import faulthandler
        faulthandler.dump_traceback_later(8, repeat=True, file=sys.stderr)
    stop = threading.Event()
    def watch():
        if os.name == "nt":
            # A blocking CRT stdin read can deadlock NumPy's Windows DLL load.
            # Poll the private pipe without reading or holding the CRT stream lock.
            import ctypes
            import msvcrt
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.PeekNamedPipe.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p]
            kernel.PeekNamedPipe.restype = ctypes.c_int
            handle = msvcrt.get_osfhandle(sys.stdin.fileno())
            available = ctypes.c_ulong()
            while not stop.is_set():
                ok = kernel.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None)
                if not ok or available.value:
                    stop.set()  # Parent pipe EOF, or an explicit stop byte.
                    return
                stop.wait(.2)
        else:
            sys.stdin.buffer.read(1)
            stop.set()
    threading.Thread(target=watch, daemon=True).start()
    if name == "api":
        import uvicorn
        server = uvicorn.Server(uvicorn.Config("server.app:app", host="127.0.0.1", port=int(os.getenv("GOLD_AI_API_PORT", "8765")), timeout_graceful_shutdown=10, timeout_keep_alive=2, log_config=None))
        def shutdown():
            stop.wait()
            server.should_exit = True
        threading.Thread(target=shutdown, daemon=True).start()
        server.run()
    elif name == "signal_engine":
        from server.signal_engine import main
        import MetaTrader5 as mt5
        try:
            main(stop)
        finally:
            mt5.shutdown()
    elif name == "personal":
        from server.personal_worker import run
        run(stop)
    elif name == "personal_probe":
        from server.personal_worker import probe
        probe()
    elif name == "notifications":
        from server.telegram_notifications import run
        run(stop)
    elif name == 'maintenance':
        from server.client_notifications import run_maintenance
        run_maintenance(stop)
    elif name.startswith('hosted_') and name[7:].isdigit():
        from server.hosted_worker import run
        run(int(name[7:]), stop)
    elif name == "telegram":
        from server.client_telegram import ClientTelegramBot
        bot = ClientTelegramBot()
        bot._stop = stop
        bot.run_forever()
    elif name == "probe":
        print("worker ready", flush=True)
        stop.wait()
    else:
        raise ValueError(name)


class Services:
    def __init__(self, root):
        self.port = int(os.getenv("GOLD_AI_API_PORT", "8765"))
        self.root = root
        self.processes = {}
        self.errors = {}
        self.lifecycle_lock = threading.RLock()
        self.logs = root / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.telegram_generation = self._telegram_generation()
        self.health = "API: checking | ngrok: checking"
        self.monitor_stop = threading.Event()
        threading.Thread(target=self.monitor, daemon=True).start()

    def _telegram_generation(self):
        import json
        try:
            data=json.loads((self.logs/'telegram_reload.json').read_text(encoding='utf-8'))
            return str(data.get('generation','')) if isinstance(data,dict) else ''
        except (OSError,ValueError):
            return ''

    def _reload_telegram(self):
        generation=self._telegram_generation()
        if not generation or generation==self.telegram_generation or self.monitor_stop.is_set():
            return
        self.telegram_generation=generation
        with self.lifecycle_lock:
            names=tuple(name for name in ('telegram','notifications','maintenance') if name in self.processes or name in self.errors)
            self.stop_named(names)
            if not self.monitor_stop.is_set():
                self.start(names)

    def start(self, names=("api", "signal_engine", "telegram", "notifications", "maintenance"), extra_env=None):
        with self.lifecycle_lock:
            return self._start(names,extra_env)

    def _start(self,names,extra_env=None):
        # Do not attach to or kill an independently launched API.
        api = self.processes.get("api")
        if "api" in names and (api is None or api.poll() is not None):
            with socket.socket() as sock:
                try:
                    sock.bind(("127.0.0.1", self.port))
                except OSError:
                    self.errors["stack"] = "API port occupied. Close the old owner stack first."
                    return
        self.errors.pop("stack", None)
        for name in names:
            if name in self.processes and self.processes[name].poll() is None:
                continue
            if name == "telegram" and not os.getenv("GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN", "").strip():
                self.errors[name] = "Not configured: set token in .env"
                continue
            args = [sys.executable, "--service", name] if getattr(sys, "frozen", False) else [sys.executable, "-m", "server.admin_launcher", "--service", name]
            mode = os.getenv("AZT_EXTERNAL_TELEGRAM", "auto").strip().lower()
            source_root = telegram_source(self.root)
            python = source_root / ".venv/Scripts/python.exe"
            external = (name in {"telegram", "notifications", "maintenance"}
                        and mode not in {"0", "false", "no", "off"}
                        and (mode != "auto" or python.is_file()))
            if external:
                if not python.is_file():
                    self.errors[name]='External Telegram runtime missing: install owner requirements into .venv, then retry.'
                    continue
                args=[str(python),'-m','server.admin_launcher','--service',name]
            try:
                (self.logs / (name + "_status.json")).unlink(missing_ok=True)
                with open(self.logs / (name + ".log"), "ab", buffering=0) as log:
                    log.write(b"\n=== service starting ===\n")
                    module_root=source_root if external else Path(__file__).resolve().parents[1]
                    env={**os.environ, "GOLD_AI_HOME":str(self.root), "PYTHONPATH":str(module_root), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", **(extra_env or {})}
                    if external and getattr(sys,'frozen',False):
                        bundle=str(Path(sys._MEIPASS).resolve()).casefold()
                        env['PATH']=os.pathsep.join(p for p in env.get('PATH','').split(os.pathsep) if not str(Path(p).resolve()).casefold().startswith(bundle))
                        env.pop('PYTHONHOME',None)
                    with external_runtime(external):
                        self.processes[name] = subprocess.Popen(args, cwd=source_root if external else self.root, stdin=subprocess.PIPE, stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env=env)
                self.errors.pop(name, None)
            except Exception as exc:
                self.errors[name] = str(exc)

    def monitor(self):
        import urllib.request
        import json
        while not self.monitor_stop.is_set():
            values = []
            for label, url in (("API", f"http://127.0.0.1:{self.port}/health"), ("ngrok", "http://127.0.0.1:4040/api/tunnels")):
                try:
                    with urllib.request.urlopen(url, timeout=1) as response:
                        data = json.load(response)
                    if label == "ngrok":
                        urls = [t["public_url"] for t in data.get("tunnels", []) if str(self.port) in str(t.get("config", {}).get("addr", ""))]
                        values.append("ngrok: " + (", ".join(urls) if urls else f"no tunnel to {self.port}"))
                    else:
                        values.append("API: healthy")
                except Exception:
                    values.append(label + ": unavailable")
            self.health = " | ".join(values)
            self._reload_telegram()
            self.monitor_stop.wait(3)

    def detect_personal(self, terminal):
        import json
        self.start(("personal_probe",), extra_env={"GOLD_AI_PERSONAL_PROBE_TERMINAL": terminal})
        process = self.processes.get("personal_probe")
        if process is None:
            raise RuntimeError(self.errors.get("personal_probe", "Could not start MT5 detection."))
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.stop_named(("personal_probe",))
            raise RuntimeError("MT5 detection timed out. Log in to the selected terminal and retry.")
        finally:
            if process.stdin:
                process.stdin.close()
        path = self.logs / "personal_probe_status.json"
        if not path.exists():
            raise RuntimeError("MT5 detection failed; see personal_probe.log.")
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("state") != "DETECTED":
            raise RuntimeError(result.get("message", "MT5 detection failed."))
        return result

    def start_personal(self):
        from server.personal_store import load_settings
        load_settings()  # Validated before starting either service.
        self.start(("signal_engine", "personal", "notifications"))

    def runtime_status(self, name):
        import json
        process = self.processes.get(name)
        if process is None:
            return "off"
        if process.poll() is not None:
            try:
                value = json.loads((self.logs / (name + "_status.json")).read_text(encoding="utf-8"))
                return "stopped: " + value.get("message", "see service log")
            except (OSError, ValueError):
                return "stopped; see service log"
        try:
            value = json.loads((self.logs / (name + "_status.json")).read_text(encoding="utf-8"))
            stale = time.time() - value.get("updated", 0) > 30
            return value.get("state", "") + (" (status stale)" if stale else "") + ": " + str(value.get("message", value.get("login", "")))
        except (OSError, ValueError):
            return "starting" if self.processes.get(name) and self.processes[name].poll() is None else "off"

    def status(self):
        rows = [f"{name}: " + (f"Running (PID {p.pid})" if p.poll() is None else f"Exited ({p.returncode}); see logs") for name, p in self.processes.items()]
        return self.health + " | Engine: " + self.runtime_status("signal_engine") + " | Personal: " + self.runtime_status("personal") + " | Telegram: " + self.runtime_status("telegram") + " | Owner alerts: " + self.runtime_status("notifications") + " | " + " | ".join(rows + [f"{k}: {v}" for k, v in self.errors.items()])

    def stop_named(self, names):
        with self.lifecycle_lock:
            return self._stop_named(names)

    def _stop_named(self,names):
        processes = [p for name, p in self.processes.items() if name in names]
        for p in processes:
            if p.poll() is None:
                try:
                    p.stdin.close()
                except OSError:
                    pass
        deadline = time.monotonic() + 25
        for p in processes:
            try:
                p.wait(timeout=max(0.1, deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                with open(self.logs / "launcher.log", "a") as log:
                    log.write(f"Forced shutdown PID {p.pid} after 25 seconds\n")
                p.kill()
                p.wait()

    def stop(self):
        self.monitor_stop.set()
        self.stop_named(tuple(self.processes))


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--verify-signal-bundle":
        # Import-only packaged-EXE check: no MT5 login, no market scan, no orders.
        # It catches missing dependencies that pass source-level tests but fail
        # inside a frozen signal_engine service subprocess.
        if not getattr(sys, "frozen", False):
            raise RuntimeError("Signal bundle verification must run in the packaged EXE.")
        import pandas as pd
        import numpy as np
        from server.signal_engine import MT5Client, StrategyRegistry
        from strategies.m15_breakout import M15BreakoutStrategy
        assert pd.DataFrame({"v": [1, 2, 3]})["v"].sum() == 6
        assert np.asarray([1, 2, 3]).sum() == 6
        assert StrategyRegistry(market="GOLD").models
        assert M15BreakoutStrategy is not None and MT5Client is not None
        proof = os.environ.get("AZT_SIGNAL_BUNDLE_PROBE", "").strip()
        if proof:
            Path(proof).write_text(f"signal_engine imports OK; pandas={pd.__version__}; numpy={np.__version__}\\n", encoding="utf-8")
        return
    root = configure()
    if len(sys.argv) == 3 and sys.argv[1] == "--service":
        try:
            worker(sys.argv[2])
        except Exception:
            import logging
            logging.exception("Background service failed")
            raise SystemExit(1)
        return
    # File lock prevents duplicate signal engines, even when API failed to start.
    import msvcrt
    lock = open(root / ".admin.lock", "a+b")
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        from tkinter import messagebox
        messagebox.showinfo("AZT", "AGORA ZION TRADER Admin is already running.")
        return
    services = Services(root)
    try:
        from server.admin_gui import GoldAIAdmin
        app = GoldAIAdmin(services)
        services.start(("api", "telegram", "notifications", "maintenance") if '--smoke-test' in sys.argv else ("api", "signal_engine", "telegram", "notifications", "maintenance"))
        if "--smoke-test" in sys.argv:
            assert "signal_engine" not in services.processes
            assert "personal" not in services.processes
            phase = [0]
            smoke_state = {}
            def smoke_actions():
                if app.control_busy:
                    app.after(100, smoke_actions)
                    return
                process = services.processes.get("signal_engine")
                if phase[0] == 0:
                    # All workspace pages must remain navigable at common laptop
                    # sizes. Controls wrap inside scrollable pages; footer stays.
                    app.state('normal')
                    for size in ('1024x768','1280x800','1366x768','1440x900'):
                        app.geometry(size)
                        app.update_idletasks()
                        for page in ('Dashboard','Clients','Trades','Journal','Telegram','Risk','Settings'):
                            app.show_page(page)
                            app.update_idletasks()
                            assert app.pages[page].winfo_width()>500
                        assert app.status_label.winfo_rooty()+app.status_label.winfo_height() <= app.winfo_rooty()+app.winfo_height()
                    app.show_page('Dashboard')
                    # Exercise this controller from the packaged script entry point,
                    # where relative imports have no package context. Never spawn
                    # a personal worker or use real settings in this regression check.
                    from server import personal_store
                    original_loader = personal_store.load_settings
                    original_start = services.start
                    requests = []
                    personal_store.load_settings = lambda: {}
                    services.start = lambda names: requests.append(tuple(names))
                    try:
                        services.start_personal()
                    finally:
                        personal_store.load_settings = original_loader
                        services.start = original_start
                    assert requests == [("signal_engine", "personal", "notifications")]
                    app.personal_settings()
                    for child in app.winfo_children():
                        if child.winfo_class() == "Toplevel":
                            child.destroy()
                    app.start_trading()
                    phase[0] = 1
                elif phase[0] == 1 and services.runtime_status("signal_engine").startswith("SCANNING"):
                    app.stop_trading()
                    phase[0] = 2
                elif phase[0] == 2 and process is not None and process.poll() is not None:
                    app.start_trading()
                    phase[0] = 3
                elif phase[0] == 3 and services.runtime_status("signal_engine").startswith("SCANNING"):
                    from server.telegram_admin import request_reload
                    smoke_state.update(api=services.processes['api'],engine=process,maintenance=services.processes['maintenance'])
                    request_reload(root)
                    phase[0]=4
                elif phase[0] == 4 and services.processes.get('maintenance') is not smoke_state['maintenance']:
                    assert smoke_state['maintenance'].poll() is not None
                    assert services.processes['api'] is smoke_state['api'] and smoke_state['api'].poll() is None
                    assert services.processes['signal_engine'] is smoke_state['engine'] and smoke_state['engine'].poll() is None
                    app.close_app()
                    return
                app.after(200, smoke_actions)
            app.after(300, smoke_actions)
        app.mainloop()
    finally:
        services.stop()
        lock.close()


if __name__ == "__main__":
    main()
