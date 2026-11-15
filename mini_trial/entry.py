"""Mini entry: three local worker roles only, never customer/API/hosted/Telegram."""
import sys
from mini_trial.runtime import configure
from mini_trial.clock import require_active, expired_existing_lease, TrialExpired, ClockUnavailable

def main():
    # Packaging verification: import the frozen execution stack without MT5
    # initialization, signal publication, external messages or trade placement.
    if len(sys.argv) == 2 and sys.argv[1] == "--verify-bundle":
        try:
            import server.signal_engine
            import server.personal_worker
            import broker.mt5_client
            import strategies
        except BaseException:
            from pathlib import Path
            import traceback
            Path("mini_verify_error.log").write_text(traceback.format_exc(), encoding="utf-8")
            raise
        return
    configure()
    # The Windows scheduled check never starts the clock for someone who
    # downloaded/installed but has not actually opened the trial.
    if len(sys.argv) == 2 and sys.argv[1] == "--expiry-check":
        try:
            if expired_existing_lease():
                from mini_trial.cleanup import start_uninstall
                start_uninstall()
        except ClockUnavailable:
            # An offline/uncertain internet clock blocks trades. Retry cleanup
            # at the next scheduled check rather than guessing the date.
            pass
        return
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
