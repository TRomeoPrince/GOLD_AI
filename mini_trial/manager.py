"""Only local Mini workers. Cooperative shutdown and isolated logs."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from threading import RLock
from mini_trial.clock import require_active

class MiniManager:
    def __init__(self, home):
        self.home=Path(home)
        self.workers={}
        self.logs={}
        self.lock=RLock()

    def start(self,name,**extras):
        if name not in ("signal_engine","personal","personal_probe"):
            raise ValueError("The Mini edition has no API, client, hosted or Telegram workers.")
        require_active(force=True)
        with self.lock:
            p=self.workers.get(name)
            if p is not None and p.poll() is None:
                return
            if name=="personal":
                from server.personal_store import load_settings
                load_settings()
            args=([sys.executable,"--service",name] if getattr(sys,"frozen",False)
                  else [sys.executable,"-m","mini_trial.entry","--service",name])
            log=open(self.home/"logs"/(name+".log"),"ab",buffering=0)
            project=str(Path(__file__).resolve().parents[1])
            env={**os.environ,"PYTHONPATH":os.pathsep.join(filter(None,(project,os.environ.get("PYTHONPATH","")))),**extras}
            try:
                p=subprocess.Popen(args,cwd=self.home,env=env,stdin=subprocess.PIPE,
                                   stdout=log,stderr=log,
                                   creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
                self.workers[name]=p
                self.logs[name]=log
            except BaseException:
                log.close()
                raise

    def stop(self,*names):
        with self.lock:
            for name in names:
                p=self.workers.get(name)
                if p and p.poll() is None and p.stdin:
                    try:
                        p.stdin.close()
                    except OSError:
                        pass
            for name in names:
                p=self.workers.get(name)
                if p and p.poll() is None:
                    try:
                        p.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        p.kill()
                        p.wait(timeout=5)
                log=self.logs.pop(name,None)
                if log:
                    log.close()

    def stop_all(self):
        self.stop("personal_probe","personal","signal_engine")

    def status(self,name):
        p=self.workers.get(name)
        if p is None:
            return "STOPPED"
        if p.poll() is not None:
            return "STOPPED" if p.returncode==0 else f"FAILED ({p.returncode})"
        try:
            obj=json.loads((self.home/"logs"/(name+"_status.json")).read_text(encoding="utf-8"))
            if time.time()-float(obj["updated"])>30:
                return "STALE"
            return str(obj.get("state","RUNNING"))
        except (OSError,ValueError,TypeError,KeyError):
            return "STARTING"
