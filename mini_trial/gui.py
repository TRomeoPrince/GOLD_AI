"""Small Windows UI for account detection, local personal risk and trading."""
import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from mini_trial.clock import require_active, load_lease, ClockUnavailable, TrialExpired
from mini_trial.cleanup import start_uninstall
from mini_trial.manager import MiniManager
from server.personal_store import save_settings, load_settings
import os

class MiniGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AGORA ZION TRADER | Mini Trial (14 days)")
        self.geometry("790x550")
        self.minsize(690,485)
        self.home=Path(os.environ["GOLD_AI_HOME"])
        self.manager=MiniManager(self.home)
        self.busy=False
        self.closing=False
        self.status=tk.StringVar(value="Trading stopped. Configure MT5 first.")
        self.internet=tk.StringVar(value="Internet time verification pending.")
        self.worker_status=tk.StringVar(value="Workers stopped")
        self.fields={}
        self.build()
        self.protocol("WM_DELETE_WINDOW",self.close)
        self.verify_time()
        self.after(30000,self.periodic)
        self.after(2500,self.refresh)

    def build(self):
        page=ttk.Frame(self,padding=18)
        page.pack(fill="both",expand=True)
        ttk.Label(page,text="AZT MINI TRADER",font=("Segoe UI",20,"bold")).pack(anchor="w")
        ttk.Label(page,text="Local MT5 personal trading only • No client management or Owner API").pack(anchor="w")
        ttk.Label(page,text="14-DAY TRIAL • STARTS ON FIRST VERIFIED LAUNCH",font=("Segoe UI",11,"bold")).pack(anchor="w",pady=7)
        ttk.Label(page,textvariable=self.internet,wraplength=710).pack(anchor="w")
        try:
            saved=load_settings()
        except (OSError,ValueError,KeyError):
            saved={}
        box=ttk.LabelFrame(page,text="MT5 Account and Personal Risk",padding=12)
        box.pack(fill="x",pady=10)
        for index,(key,label,default) in enumerate((
            ("terminal_path","MT5 terminal64.exe",""),
            ("login","MT5 login",""),
            ("server","Broker server",""),
            ("risk_per_trade_pct","Risk per trade 0.1–2%","0.9"),
            ("max_open_risk_pct","Maximum open risk 5–40%","40"),
            ("max_daily_loss_pct","Maximum daily loss 2–10%","5"))):
            ttk.Label(box,text=label).grid(row=index,column=0,sticky="w",pady=3)
            self.fields[key]=tk.StringVar(value=str(saved.get(key,default)))
            ttk.Entry(box,textvariable=self.fields[key]).grid(row=index,column=1,padx=10,pady=3,sticky="ew")
            if key=="terminal_path":
                ttk.Button(box,text="Browse",command=self.browse).grid(row=index,column=2)
        box.columnconfigure(1,weight=1)
        actions=ttk.Frame(page)
        actions.pack(fill="x",pady=7)
        for text,action in (("Detect MT5",self.detect),("Save Risk",self.save),
                            ("Start Trading",self.start),("Stop Trading",self.stop)):
            ttk.Button(actions,text=text,command=action).pack(side="left",padx=(0,7))
        ttk.Label(page,textvariable=self.status,wraplength=710).pack(anchor="w",pady=5)
        ttk.Label(page,textvariable=self.worker_status).pack(anchor="w")
        ttk.Label(page,text="Online time checks are mandatory. Existing broker trades and SL/TP are not deleted on expiry.",wraplength=710).pack(anchor="w",pady=7)

    def browse(self):
        path=filedialog.askopenfilename(parent=self,title="Select terminal64.exe",filetypes=[("MetaTrader 5","terminal64.exe"),("Executables","*.exe")])
        if path:
            self.fields["terminal_path"].set(path)

    def background(self,action,done=None):
        if self.busy or self.closing:
            return
        self.busy=True
        def execute():
            try:
                result,error=action(),None
            except Exception as exc:
                result,error=None,str(exc)
            def finish():
                self.busy=False
                if self.closing:
                    return
                if error:
                    self.status.set("ERROR: "+error)
                elif done:
                    done(result)
            self.after(0,finish)
        threading.Thread(target=execute,daemon=True).start()

    def save(self):
        values={key:var.get().strip() for key,var in self.fields.items()}
        def action():
            if self.manager.status("personal") not in ("STOPPED",) and not self.manager.status("personal").startswith("FAILED"):
                raise RuntimeError("Stop personal trading before changing settings")
            require_active(force=True)
            return save_settings(values)
        self.background(action,lambda data:self.status.set(f"Saved {data['login']} @ {data['server']}"))

    def detect(self):
        terminal=self.fields["terminal_path"].get().strip()
        def action():
            if not Path(terminal).is_file():
                raise ValueError("Select an installed MetaTrader 5 terminal64.exe")
            self.manager.start("personal_probe",GOLD_AI_PERSONAL_PROBE_TERMINAL=terminal)
            self.manager.workers["personal_probe"].wait(timeout=25)
            data=json.loads((self.home/"logs"/"personal_probe_status.json").read_text(encoding="utf-8"))
            if data.get("state")!="DETECTED":
                raise RuntimeError(data.get("message","MT5 account detection failed"))
            return data
        def done(data):
            self.fields["login"].set(str(data["login"]))
            self.fields["server"].set(str(data["server"]))
            self.status.set(f"Detected {data['login']} ({data.get('currency','')}). Save settings to continue.")
        self.background(action,done)

    def start(self):
        def action():
            require_active(force=True)
            load_settings()
            self.manager.start("signal_engine")
            self.manager.start("personal")
        self.background(action,lambda _:self.status.set("Workers starting. Wait for READY/SCANNING."))

    def stop(self):
        self.background(lambda:self.manager.stop("personal","signal_engine"),
                        lambda _:self.status.set("Trading stopped. Broker positions and SL/TP remain."))

    def verify_time(self):
        if self.closing:
            return
        def action():
            try:
                now=require_active(force=True)
                deadline=load_lease()["expires_utc"]
                message=f"Verified internet UTC: {now:%Y-%m-%d %H:%M:%S} | Expires: {deadline:%Y-%m-%d %H:%M UTC}"
                expired=False
            except TrialExpired:
                message,expired="Trial expired; uninstalling",True
            except ClockUnavailable as exc:
                message,expired=str(exc),False
                self.manager.stop_all()
            def finish():
                if self.closing:
                    return
                self.internet.set(message)
                if expired:
                    self.expire()
            self.after(0,finish)
        threading.Thread(target=action,daemon=True).start()

    def periodic(self):
        if not self.closing:
            self.verify_time()
            self.after(30000,self.periodic)

    def refresh(self):
        if not self.closing:
            self.worker_status.set("Signal: "+self.manager.status("signal_engine")+
                                   " | Executor: "+self.manager.status("personal"))
            self.after(2500,self.refresh)

    def expire(self):
        if self.closing:
            return
        self.closing=True
        self.withdraw()
        def finish():
            self.manager.stop_all()
            start_uninstall()
            self.after(0,self.destroy)
        threading.Thread(target=finish,daemon=True).start()

    def close(self):
        if self.closing:
            return
        self.closing=True
        self.withdraw()
        def finish():
            self.manager.stop_all()
            self.after(0,self.destroy)
        threading.Thread(target=finish,daemon=True).start()
