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
