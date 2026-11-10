# AZT Mini Trial (standalone Windows edition)

**Status:** experimental feature branch; NOT an approved production build.

- User-selected MT5 terminal and automatically detected account, personal risk settings, local signal engine and personal MT5 order executor. NO customer API, Owner server, hosted workers, ngrok or Telegram is started.
- Installer: `AZT_Mini_Trial_Setup.exe`, produced by the Windows GitHub Actions workflow `Build AZT Mini Trial (Windows)`; action artifact does not imply Windows end-to-end or live MT5 verification.
- Trial ends **17 November 2026, 23:59:59 Africa/Kampala** (cutoff 2026-11-17 21:00:00 UTC). Trusted HTTPS Date time is required at startup, periodically while open and immediately before MT5 order submission. Failed verification blocks new orders. No local-PC date can extend the trial.
- On expiry, the app cooperatively stops its owned workers and launches a separately installed batch helper. That helper launches a separate delayed (eight-second) PowerShell process, exits before its own removal, and invokes the Inno Setup uninstaller. Only the application installation is removed; local state and broker positions / SL/TP remain. Windows user permissions or an unexpected process lock can prevent automatic removal.
- Per-user state lives in `%LOCALAPPDATA%\AZT_Mini_Trial\state`. **Never delete its execution journal** to retry ambiguous trades.
- The existing Owner signal and personal workers are reused. Isolated Mini scope is selected by `AZT_MINI_TRIAL=1`, which has an additional fail-closed order-submission guard. Existing #WORKING Owner and Client commit SHA references remain intact.
- Python/PyInstaller one-file EXE packages the included strategies; no Python-only packaging can make strategy code completely unrecoverable. The trial is standalone except for internet time verification.
- This release intentionally keeps strict broker, UTC, news, exposure, stop loss, account and daily risk checks from Owner code. Account lock remains shared with Owner.
- No local/CI smoke test should send real orders or Telegram messages. Do not distribute an EXE or start automated trading until the Windows build, startup, MT5 probe, risk, order guard and expiry uninstall have been verified with consent.

Build locally on Windows:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_mini_trial.py -v
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --distpath dist_mini --workpath build/mini_pyi build/AZT_Mini_Trial.spec
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" "build/AZT_Mini_Trial.iss"
```

**Known limitations:** HTTPS response time is not tamper-proof against a determined user; the trial makes no server licensing calls. Installed state intentionally remains after uninstall for financial safety. This fixed-date trial cannot be extended by reinstalling; offline mode blocks orders.

## Successful Windows build and safe install/uninstall smoke

GitHub Actions [run 42704174921](https://github.com/TRomeoPrince/GOLD_AI/actions/runs/42704174921) succeeded against application commit `d647a09f17fc2e45ba55deeb7fec498fba8d561a` on `feature/azt-mini-trial-20261110`.

- Isolated Mini tests: **8 passed**.
- PyInstaller x64 windowed EXE: **built**, frozen signal/personal import verification passed without connecting to MT5.
- Inno Setup: **built** per-user installer.
- Installation/uninstallation smoke: installed to a temporary Windows directory, verified the executable and delayed batch helper, launched the detached cleanup, then verified the installed executable was removed. **Passed**. Existing account state was not used.
- Live broker execution, actual internet-date availability on customer networks, and live trading performance: **not verified**.

| Artifact | GitHub Actions download | SHA256 (inner EXE) |
| --- | --- | --- |
| Installer | [AZT-Mini-Trial-Setup](https://github.com/TRomeoPrince/GOLD_AI/actions/runs/42704174921/artifacts/13713131705) | `14D32B87C198204C2CB79B94C1C6FA40F4AC386948F46D42DCB26F3A31F4B641` |
| Standalone executable | [AZT-Mini-Trial-EXE](https://github.com/TRomeoPrince/GOLD_AI/actions/runs/42704174921/artifacts/13712866631) | `B8D748F2A4E16137DEB0A3A40D2D14F52F4B6C0D908B5D7CA864B07FBFF5AA63` |

Artifacts are ZIP downloads containing the named EXE, not signed retail releases. The checksums refer to the EXE files inside the ZIPs, not the GitHub-generated ZIP archives. No real broker order or real Telegram message was sent by CI.
