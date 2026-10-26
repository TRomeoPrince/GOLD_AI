# Admin launcher build result — 26 October 2026

Owner checkout: C:\Users\USER\Desktop\Bots\Forex\AMD1

Artifact: dist_buttons/GOLD_AI_Admin.exe (the running original was left untouched)

Build: PASS, PyInstaller 6.22.3, Python 3.13.15, Windows x64, windowed single-file bundle.

SHA256: 05113d15c56dd17ccc2b36b4f9da93345d8311d4d4ce8a21792709052139505d

Validation:
- Eight unittest cases passed: original lifecycle/configuration tests plus shared ngrok reuse, scheduled-task preference, independent fallback and task-permission failure.
- Frozen EXE integration PASS: Admin UI startup, isolated API health HTTP 200, engine startup with no enabled markets, manual trading Start/Stop/Start, automatic UI close, cooperative API shutdown, no forced termination log, unchanged seeded client/risk/subscription records.
- Same integration passed from source.
- Verified frozen entrypoint bytecode matches current source.
- Scheduled-task PowerShell syntax parsing and git diff whitespace checks passed.
- No live trade, broker account or Telegram delivery test performed. Scheduled task not installed or boot-tested; requires private ngrok config and elevated setup.
- Existing API at 127.0.0.1:8765 left running untouched. Close old stack before launching this version on that port.

Changed files:
.gitignore
START_GOLD_AI.bat
build/GOLD_AI_Admin.spec
build/build_admin.bat
server/admin_gui.py
server/admin_launcher.py
server/run_owner_stack.bat
server/signal_engine.py
scripts/install_shared_ngrok.ps1
scripts/shared-ngrok.example.yml
tests/test_admin_launcher.py
tests/smoke_admin_exe.py
ADMIN_LAUNCHER.md
ADMIN_BUILD_RESULT.md

Button update: opening Admin starts API/Telegram only. Start Automated Trading starts the engine; Stop stops generation but leaves queued instructions and open positions unchanged. Start ngrok reuses or launches independent shared ngrok. API shutdown has a bounded drain wait. The final frozen integration passed without forced termination; live trading and ngrok network activation were not exercised.

Additional files changed in this update:
server/ngrok_start.py
tests/test_ngrok_start.py

Rebuild this output:
.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist_buttons --workpath build/admin_pyi build/GOLD_AI_Admin.spec

Test it in PowerShell:
$env:GOLD_AI_TEST_EXE = 'dist_buttons/GOLD_AI_Admin.exe'
.venv\Scripts\python.exe tests/smoke_admin_exe.py

Run after closing the old Admin:
Start-Process 'C:\Users\USER\Desktop\Bots\Forex\AMD1\dist_buttons\GOLD_AI_Admin.exe'

The generated EXE remains a local build artifact, outside the source commit. Existing unrelated local reports and files are untouched. No client-repo files changed. See ADMIN_LAUNCHER.md for exact setup/build/test/run commands and detailed current client behavior. The source commit is available with git log -1 --format=%H.
