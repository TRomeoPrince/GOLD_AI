"""Mini entry: three local worker roles only, never customer/API/hosted/Telegram."""
import sys
from mini_trial.runtime import configure
from mini_trial.clock import require_active, TrialExpired, ClockUnavailable

def main():
    configure()
    if len(sys.argv)==3 and sys.argv[1]=="--service":
        if sys.argv[2] not in ("signal_engine","personal","personal_probe"):
            raise SystemExit("Unauthorized Mini worker")
        require_active(force=True)
        from server.admin_launcher import worker
        worker(sys.argv[2])
        return
    try:
        require_active(force=True)
    except TrialExpired:
        from mini_trial.cleanup import start_uninstall
        start_uninstall()
        return
    except ClockUnavailable as exc:
        from tkinter import messagebox
        messagebox.showerror("AZT Mini Trial",str(exc))
        return
    from mini_trial.gui import MiniGUI
    MiniGUI().mainloop()

if __name__=="__main__":
    main()
