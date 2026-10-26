# Admin launcher build result — 26 October 2026

Owner checkout: C:\Users\USER\Desktop\Bots\Forex\AMD1

Artifact: dist/GOLD_AI_Admin.exe

Build: PASS, PyInstaller 6.22.3, Python 3.13.15, Windows x64, windowed single-file bundle.

SHA256: a846e14fc173abc136a6448239666fbd24a232a1e93387ff92fa56dc1ea6aacd

Validation:
- Four unittest cases passed: child lifecycle/logging, missing Telegram token, occupied API port, retry while owned API is running.
- Frozen EXE integration PASS: Admin UI startup, isolated API health HTTP 200, engine startup with no enabled markets, automatic UI close, cooperative API shutdown, no forced termination log, unchanged seeded client/risk/subscription records.
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

The generated EXE remains a local build artifact, outside the source commit. Existing unrelated local reports and files are untouched. No client-repo files changed. See ADMIN_LAUNCHER.md for exact setup/build/test/run commands and detailed current client behavior. The source commit is available with git log -1 --format=%H.
