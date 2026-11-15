# AZT Mini 14-Day Friends Trial (standalone Windows)

**Release:** Experimental test build. **Never overwrite/deploy the production Owner or Client from this branch.** The fixed-deadline Mini Trial that expires on 17 November 2026 remains on its prior feature branch, unchanged.

## Friend setup and expiry

- Download **AZT_Mini_14Day_Trial_Setup.exe** from the private preview release. The bare PyInstaller executable is *not* a complete installer and cannot auto-uninstall; distribute the Setup EXE only.
- Requires Windows x64, locally installed **MetaTrader 5**, a broker account, and internet access for trusted UTC time checks. No AZT pairing code, customer API, owner-server access, hosted worker, Telegram credentials or subscription is required.
- Select the MT5 \`terminal64.exe\`, use **Detect MT5**, set local risk, **Save Risk**, and **Start Trading**. Start with a **DEMO** account; neither backtests nor CI validate live results.
- Each friend gets **14 full days starting from their first successful HTTPS internet-UTC verification**. Downloading/installing the EXE does not begin the 14-day period. Activation and expiry are saved in \`%LOCALAPPDATA%\AZT_Mini_14Day_Trial\state\trial_lease.json\`, which is *intentionally* preserved by uninstall/reinstall. The existing Mini edition uses a different storage directory.
- Internet UTC is checked at startup, periodically while open, and just before each MT5 order. If verification fails or the period expires, **no new orders** are permitted. No local PC clock can extend the lease. Trading safety and broker checks from the previous Mini code are retained.
- Installer registers a visible **AZT Mini 14-Day Expiry** per-user Windows scheduled task, checking every **30 minutes**. The check does **not** activate an unstarted trial. After verified expiry, the Mini workers stop and a delayed helper uninstalls only this edition once the EXE has exited. If Windows is off, offline, the user is logged out, the task is blocked, or the GUI remains open, local removal occurs at a later eligible check. The user can uninstall earlier in Windows Settings.
- The uninstaller **does not remove** MT5, open broker positions, broker SL/TP, your saved configuration or any execution history. The user must monitor open positions independently on expiry. Never delete execution journals to replay uncertain trades.

## Technical trust limitations

This standalone test edition is *not* a cryptographically enforced, tamper-proof license. It uses HTTPS response Date with monotonic in-process caching and a preserved local activation record. A technically capable user who alters or deletes local state can still bypass a client-only trial. A server-issued entitlement would be required for strong license enforcement, but would change the no-pairing-code standalone test design.

## Verification and build

\`\`\`powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_mini_trial.py -v
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --distpath dist_mini --workpath build/mini_pyi build/AZT_Mini_Trial.spec
& "$env:ProgramFiles\Inno Setup 6\ISCC.exe" build\AZT_Mini_Trial.iss
\`\`\`

On GitHub, run **Build AZT Mini 14-Day Trial (Windows)** from branch \`feature/azt-mini-14day-auto-uninstall-20261116\`. It must pass unit tests, frozen import verification, Inno compilation, Windows Task Scheduler registration, the unactivated task-check test, and an installer/uninstaller smoke test. The compiled private preview release asset is **AZT_Mini_14Day_Trial_Setup.exe**. It is not code-signed. No CI workflow places a real MT5 order or Telegram message.

## Historical Mini proof

The preceding **fixed-date** Mini edition, built on \`feature/azt-mini-trial-20261110\`, passed 8 unit tests, Windows PyInstaller import smoke and a delayed cleanup smoke in GitHub Actions run [42704174921](https://github.com/TRomeoPrince/GOLD_AI/actions/runs/42704174921). That older run does **not** verify the new 14-day build; use the new branch's workflow results.
