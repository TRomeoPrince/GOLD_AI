# AZT Telegram presentation update

Telegram execution alerts now describe the instrument/direction, strategy, ticket, account, size, fill (or explicitly requested price), SL/TP, broker-calculated cash estimates when available, planned risk and planned portfolio exposure. Values retain their native currency: USC is never silently presented as USD.

`/positions [page]` and `/journal [YYYY-MM-DD] [page]` provide readable details and cards. `/pnl` opens today's journal. Accounts remain scoped to the linked client; only the configured owner chat can request the owner-wide view. Display time uses the workspace/client timezone, with freshness clearly marked. Mixed currencies are totaled separately. Missing information is shown as unavailable.

Observed SL changes generate SL-update cards with old/new levels and known cash estimates. The initial snapshot is silent; stale/invalid snapshots do not generate a change. An observed change is not described as automatic trailing unless its source is known. This update adds reporting, not an SL-modification algorithm.

## Install the launcher integration once

The older frozen Admin contains its own Telegram code. This release needs one new launcher build to move Telegram command handling, owner notifications and client notification/maintenance delivery into hidden source workers. The Admin interface is unchanged. API, strategy and execution workers retain their existing process lifecycle and trading safeguards.

The source checkout and its `.venv` are now required on this owner machine. Keep them together with the data directory. From PowerShell:

```powershell
Set-Location 'C:\Users\USER\Desktop\Bots\Forex\AMD1'
.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\Users\USER\Desktop\Bots\Forex\AMD1\scripts\restart_admin.ps1'
```

The restart helper closes the old Admin window and waits for its children to exit. It does not force-kill trading workers or close broker positions. Resolve any open Admin dialogs if it cannot exit. This process-level execution-policy option does not change the system's saved policy. Personal trading must be explicitly started again after restarting Admin.

Final executable: `C:\Users\USER\Desktop\Bots\Forex\AMD1\dist_telegram_style\AZT_Admin.exe`.

## Later Telegram-only updates

Edit/update the source Telegram formatter, card renderer, command handler or delivery modules, then:

```powershell
Set-Location 'C:\Users\USER\Desktop\Bots\Forex\AMD1'
.venv\Scripts\python.exe -m server.telegram_admin reload
```

The running integrated Admin gracefully stops the three Telegram/maintenance workers, waits for them to exit, then starts their new source. API, signal engine, personal/hosted execution and ngrok remain running. Queued events are retained; their styles are generated at delivery. Previously delivered Telegram messages are not rewritten. A remote-send timeout remains potentially ambiguous and follows the existing bounded retry policy.

Defaults: `AZT_EXTERNAL_TELEGRAM=true`; optional `AZT_TELEGRAM_SOURCE_ROOT` selects another source checkout. Setting `AZT_EXTERNAL_TELEGRAM=false` deliberately uses the frozen Telegram code and requires an EXE rebuild for those changes. Do not run an extra standalone command poller with the same token.

## Validation and build

All tests use temporary databases, mock transports and simulated broker data. No live test orders or Telegram messages are sent.

```powershell
Set-Location 'C:\Users\USER\Desktop\Bots\Forex\AMD1'
.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -q
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --distpath dist_telegram_style --workpath build/telegram_style_pyi build/GOLD_AI_Admin.spec
$env:GOLD_AI_TEST_EXE='C:\Users\USER\Desktop\Bots\Forex\AMD1\dist_telegram_style\AZT_Admin.exe'
.venv\Scripts\python.exe tests/smoke_admin_exe.py
```

Read-only cash estimates are gross broker estimates and may differ from realized results after fees, swap and slippage. Older Client EXE snapshots without these fields show unavailable estimates rather than fabricated numbers. No Client EXE rebuild is required for this update.

## Release verification

- Owner full suite: **220 tests passed**.
- Client full suite: **33 tests passed**, Client repository unchanged.
- Source Admin isolation check: passed. Final frozen Admin isolation check: passed, including API health, all workspace pages, trading Start/Stop/Start, Telegram-only reload without restarting API/engine, client/risk/subscription preservation, and child shutdown without forced termination.
- Final PyInstaller build: passed, Windows x64 / Python 3.13.15 / PyInstaller 6.22.3. SHA256: `729F57C2B20B500FD164156402309A5A3E8F00C597399811EBC2D1026C00587C`.
- Restart helper `-ValidateOnly`: passed; no running production application was stopped or started.
- Simulated visual previews reviewed in `logs/telegram_preview/`; reproduce with `.venv\Scripts\python.exe -m tests.render_telegram_preview`. No real test messages or orders were sent.
- The rapid-loopback-polling smoke logs include a Windows connection-reset callback and Uvicorn's bounded 10-second shutdown timeout; API exited with code 0, its endpoint closed, and the launcher did not force-kill any worker.

The previous `dist_azt/AZT_Admin.exe` remains unchanged (SHA256 `EDB3A78A8C328EE656220627A771396BAB717538BCB717D8E19628C48A54C340`).

## Exact files changed

```
.gitignore
README.md
TELEGRAM_UPDATE.md
scripts/restart_admin.ps1
server/admin_launcher.py
server/app.py
server/client_notifications.py
server/client_telegram.py
server/hosted_executor.py
server/hosted_worker.py
server/personal_store.py
server/personal_worker.py
server/pnl_cards.py
server/telegram_admin.py
server/telegram_delivery.py
server/telegram_notifications.py
server/telegram_presentation.py
server/trade_events.py
server/trade_telemetry.py
tests/render_telegram_preview.py
tests/smoke_admin_exe.py
tests/test_telegram_card_styles.py
tests/test_telegram_event_queue.py
tests/test_telegram_presentation.py
tests/test_telegram_sidecars.py
tests/test_telegram_telemetry.py
tests/test_trade_event_details.py
```
