# Latest patch: UTC timestamps and Windows status locks — 26 October 2026

Final EXE: C:\Users\USER\Desktop\Bots\Forex\AMD1\dist_utc\GOLD_AI_Admin.exe

SHA256: CC1E2787F1EA8DF189905C371D65DE27B6690CA4620B760A7313F03BF69AE6A8

Build PASS: PyInstaller 6.22.3, Python 3.13.15, windowed Windows x64 one-file bundle.

Root cause: broker/mt5_client.py applied pandas utc=True directly to raw feed seconds. Strategies copied that candle time into setup_time. A read-only JustMarkets-Live3 sample at true UTC 08:35:58 returned an advancing tick labelled 10:35:59, about 7,201 seconds ahead, and bars labelled 10:25/10:30/10:35. Those live bars correspond to 08:25/08:30/08:35 UTC. The adapter labelled broker wall-clock data as UTC instead of converting it. The engine also clamped negative signal age to zero and could publish future signals that the personal worker correctly rejected.

The vendor documents UTC feed times at https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrom_py . The observed feed differed from that contract. broker/clock.py now measures a bounded current offset from two advancing live quotes, even for an apparent zero offset. It never calibrates from an old candle or rebases a signal to now. UTC feeds stay unshifted; the adapter converts shifted live bars before strategy scanning and retains raw broker_time. Personal quote freshness uses the same clock. The existing personal 20-minute/60-second signal rules are unchanged; the engine now enforces both bounds before customer publication too.

Calibration uses the current live-feed offset and requires a correct local UTC clock. It does not reconstruct historical broker DST policies. A later read-only check found a non-advancing quote over two minutes old, and calibration correctly refused it. No live readiness claim is made from that stale sample; reconnect with fresh advancing market quotes.

Status-file root cause: fixed .tmp names and one-shot replacement could collide with Windows readers/scanners. The new atomic writer serializes strict complete JSON, creates a unique same-directory temp, flushes/fsyncs/closes it and retries Windows access/sharing/lock errors seven times. A persistent telemetry lock keeps the last valid snapshot, logs a throttled warning and lets the worker continue. Settings failures and unrelated I/O errors are reported, not silently accepted. The database execution journal remains separate.

Preserved: personal execution without client registration/subscription; customer generation without personal settings; risk/news and account checks; no backlog on start; durable duplicate claims. Legacy broker-labelled keys are checked before publishing corrected UTC keys, so the upgrade does not replay an already queued/recorded physical setup. Existing queue/journal rows were not rewritten or cleared.

Exact changed files:
- .gitignore
- broker/clock.py
- broker/mt5_client.py
- server/atomic_json.py
- server/hosted_executor.py
- server/personal_store.py
- server/signal_engine.py
- server/store.py
- scripts/restart_admin.ps1
- tests/test_atomic_status.py
- tests/test_clock_upgrade.py
- tests/test_mt5_clock.py
- tests/test_personal_trading.py
- ADMIN_LAUNCHER.md
- ADMIN_BUILD_RESULT.md

Validation PASS:
- Full suite: 40 tests, including fresh/stale/future age boundaries, source-to-strategy UTC conversion, advancing/unchanging clocks, duplicate/backlog behavior, legacy-key upgrade protection, concurrent JSON writers, permission retries, persistent lock preservation and a real Windows handle denying delete sharing during replacement.
- Source Admin lifecycle smoke.
- Final rebuilt EXE lifecycle smoke: isolated database, no enabled markets, substituted personal-start settings/process spawning, API health, engine Start/Stop/Start, unchanged seeded client/risk/subscription rows and clean shutdown without forced kill.
- Final frozen personal-worker missing-settings path: safe error exit without a terminal connection.
- Restart helper: PowerShell parser and -ValidateOnly check; no live app was closed or started.
- No live test orders were placed. Existing unrelated files and the client repo were unchanged.

Build/test commands from the owner repo:
```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist_utc --workpath build/admin_pyi build/GOLD_AI_Admin.spec
$env:GOLD_AI_TEST_EXE = 'dist_utc/GOLD_AI_Admin.exe'
.venv\Scripts\python.exe tests\smoke_admin_exe.py
.venv\Scripts\python.exe tests\smoke_personal_exe.py
```

Restart command in PowerShell:
```powershell
& 'C:\Users\USER\Desktop\Bots\Forex\AMD1\scripts\restart_admin.ps1'
```
The helper requests normal shutdown of only this checkout's GOLD_AI_Admin processes, waits up to 40 seconds and opens dist_utc/GOLD_AI_Admin.exe. It force-kills nothing and leaves shared ngrok alone. Personal trading remains off until explicitly started. The EXE is a local artifact outside the source commit; the source commit is provided in the task response and git log -1 --format=%H.

---

## Earlier build records

# Previous patch: personal Start button in packaged Admin — 26 October 2026

Artifact: dist_fixed/GOLD_AI_Admin.exe
SHA256: 0518a5bbf25ea10e1ce9531e7d1e48d183826de513c1ccfe6363f083be1ef88d

Fixed the packaged entry point's relative import in Services.start_personal. It previously raised “attempted relative import with no known parent package” before spawning the personal worker; Personal remained off. The import now uses the absolute server module path. Action feedback is visible below the service/personal controls, rather than only in the bottom status line.

Validation PASS:
- 23 unit tests, including a script-entrypoint personal-start regression.
- Source and final frozen EXE lifecycle tests. The frozen smoke now exercises the personal-start controller with isolated mocked settings/process spawning before testing real engine Start/Stop/Start, API health and clean shutdown.
- Frozen personal worker missing-settings failure path.
- Seeded client/risk/subscription rows preserved. No real personal worker or broker order was activated during verification.

Changed: server/admin_launcher.py, server/admin_gui.py, tests/test_admin_launcher.py, ADMIN_LAUNCHER.md and this report.

The running dist/GOLD_AI_Admin.exe was left untouched. Close it before launching the corrected build:
Start-Process 'C:\Users\USER\Desktop\Bots\Forex\AMD1\dist_fixed\GOLD_AI_Admin.exe'

Build:
.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist_fixed --workpath build/admin_pyi build/GOLD_AI_Admin.spec

Test:
$env:GOLD_AI_TEST_EXE = 'dist_fixed/GOLD_AI_Admin.exe'
.venv\Scripts\python.exe tests\smoke_admin_exe.py
.venv\Scripts\python.exe tests\smoke_personal_exe.py

## Previous personal build record

# GOLD_AI Admin personal trading build — 26 October 2026

Build PASS: Python 3.13.15, PyInstaller 6.22.3, windowed Windows x64 one-file bundle.

Verified artifact: dist_personal/GOLD_AI_Admin.exe. Identical verified copies installed at dist/GOLD_AI_Admin.exe and dist_buttons/GOLD_AI_Admin.exe after confirming neither destination was running.

SHA256: 633ec35b59912fc58abc48e898e6a77a2208d8d9f75ac6398f9088e9164f5b07

Behavior:
- Customer signal generation is independent of personal account configuration and never starts personal execution implicitly.
- Personal MT5 Settings selects an explicit installed terminal, detects its current account and saves expected account/server and risk limits locally. Start My MT5 Trading starts a hidden worker and common signal engine; Stop My MT5 Trading leaves the engine/customer signals running.
- Personal trading has no client registration, pairing, subscription or ngrok requirement. Market-data MT5 is still required by the common engine.
- Account identity and permissions, global and local risk limits, news lock, daily loss/profit, portfolio risk and fresh prices are enforced. Personal account risk includes manual positions. Per-account durable claims prevent automatic retries of uncertain submissions.
- A matching active customer/hosted execution route blocks the personal worker until paused/stopped to avoid duplicates.
- Added real engine/personal readiness to the status bar. Fixed a startup deadlock caused by a blocking Windows CRT stdin watcher during NumPy native-library imports; shutdown now watches the private pipe without blocking that stream lock.

Verification:
- 22 unittest cases PASS, including owner signals with zero customers, personal execution with no client/subscription tables, durable duplicate prevention, account switching/stop guards, global risk clamp, minimum-lot ceiling, manual unprotected positions, stale quotes/missing history, ambiguous submission and original launcher/ngrok behavior.
- Source integration PASS: personal settings dialog creation, no personal autostart, actual engine SCANNING, Start/Stop/Start, API health, preserved seeded client/risk/subscription rows and shutdown.
- Final frozen EXE integration PASS for the same lifecycle and preservation checks. Existing Windows asyncio connection resets during aggressive test health polling may require the configured 10-second API drain timeout; there was no forced process kill in the final pass.
- Frozen personal worker failure-path PASS: missing settings produces visible runtime ERROR and exit 1, without attempting an MT5 connection or showing an unhandled-error popup.
- No live order or real-account execution was performed. Personal order processing is tested with a simulated MT5 interface. ngrok startup setup remains as documented; no Windows task was installed during this change.

Files changed for personal trading:
.gitignore
server/admin_gui.py
server/admin_launcher.py
server/signal_engine.py
server/hosted_executor.py
server/personal_store.py
server/personal_worker.py
tests/test_personal_trading.py
tests/smoke_admin_exe.py
tests/smoke_personal_exe.py
ADMIN_LAUNCHER.md
ADMIN_BUILD_RESULT.md

Build/test commands:
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist_personal --workpath build/admin_pyi build/GOLD_AI_Admin.spec
$env:GOLD_AI_TEST_EXE = 'dist_personal/GOLD_AI_Admin.exe'
.venv\Scripts\python.exe tests\smoke_admin_exe.py
.venv\Scripts\python.exe tests\smoke_personal_exe.py

Run after closing any older Admin:
Start-Process 'C:\Users\USER\Desktop\Bots\Forex\AMD1\dist\GOLD_AI_Admin.exe'

First setup: Personal MT5 Settings > Browse > Detect Logged-in Account > review account and limits > Save Settings > Start My MT5 Trading. Wait for Personal: READY and Engine: SCANNING. See ADMIN_LAUNCHER.md for details, logs, shared ngrok setup and current separate client behavior.

Generated executables are local artifacts outside the source commit. Unrelated files, existing client records/subscriptions and the separate GOLD_AI_client repository were not changed. Get the source commit with git log -1 --format=%H.
