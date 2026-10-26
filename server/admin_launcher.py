"""Single executable entry point. Services use private stdin for cooperative shutdown."""
from __future__ import annotations
import os
import sys
import threading
import subprocess
import socket
import time
from pathlib import Path


def configure():
    root = Path(os.environ.get("GOLD_AI_HOME", Path(sys.executable).resolve().parent.parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent)).resolve()
    from dotenv import load_dotenv
    load_dotenv(root / ".env", override=False)
    os.environ.setdefault("GOLD_AI_DB_PATH", str(root / "server" / "gold_ai_server.db"))
    os.environ.setdefault("GOLD_AI_STATE_DIR", str(root / "server"))
    os.environ.setdefault("GOLD_AI_PROJECT_ROOT", str(root))
    os.chdir(root)
    return root


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
        self.health = "API: checking | ngrok: checking"
        self.monitor_stop = threading.Event()
        threading.Thread(target=self.monitor, daemon=True).start()
        self.logs = root / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)

    def start(self, names=("api", "signal_engine", "telegram"), extra_env=None):
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
            try:
                (self.logs / (name + "_status.json")).unlink(missing_ok=True)
                with open(self.logs / (name + ".log"), "ab", buffering=0) as log:
                    log.write(b"\n=== service starting ===\n")
                    self.processes[name] = subprocess.Popen(args, cwd=self.root, stdin=subprocess.PIPE, stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", **(extra_env or {})})
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
        from .personal_store import load_settings
        load_settings()  # Validated before starting either service.
        self.start(("signal_engine", "personal"))

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
        return self.health + " | Engine: " + self.runtime_status("signal_engine") + " | Personal: " + self.runtime_status("personal") + " | " + " | ".join(rows + [f"{k}: {v}" for k, v in self.errors.items()])

    def stop_named(self, names):
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
        messagebox.showinfo("GOLD_AI", "GOLD_AI Admin is already running.")
        return
    services = Services(root)
    try:
        from server.admin_gui import GoldAIAdmin
        app = GoldAIAdmin(services)
        services.start(("api", "telegram"))
        if "--smoke-test" in sys.argv:
            assert "signal_engine" not in services.processes
            assert "personal" not in services.processes
            phase = [0]
            def smoke_actions():
                if app.control_busy:
                    app.after(100, smoke_actions)
                    return
                process = services.processes.get("signal_engine")
                if phase[0] == 0:
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
