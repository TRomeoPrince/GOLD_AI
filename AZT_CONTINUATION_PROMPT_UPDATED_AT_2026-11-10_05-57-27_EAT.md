# Continue AGORA ZION TRADER (AZT)

Updated 2026-11-10 05:57:27 EAT (UTC+03:00).

Continue from the verified Windows Owner installation. Read [the hosted repair and cutover report](AZT_HOSTED_MT5_REPAIR_REPORT.md) and inspect the current runtime before acting. Use the Owner repo `TRomeoPrince/GOLD_AI` on `fix/hosted-mt5-start-20261110`. The installed application code is `d72c474`. The Client repo is `TRomeoPrince/GOLD_AI_client` and was outside this hosted repair.

## Installed system

- Owner home is `C:\Users\USER\Desktop\Gold_AI`. Launch `START_GOLD_AI.bat` from that folder when an approved restart is needed. The launcher pins the database to `server\gold_ai_server.db`. The Owner source checkout is `C:\Users\USER\Desktop\Bots\Forex\AMD1`.
- The verified `AZT_Admin.exe` SHA256 is `B031B03CDD4C7394447150C36737434DD9020A73218B43F3DB39A6D97FD3AF25`. The full Owner suite passed 264 tests, the isolated EXE smoke check passed, and 13 hosted attachment tests passed against the packaged worker.
- `hosted_2` uses `server\hosted_mt5\client_2\terminal64.exe` in portable mode. The saved server's ASCII case difference caused a false account-change stop. The fix accepts that spelling difference at initial attach, requires the same login and portable paths, and holds both spellings' account locks before becoming active. Identity, risk, News Lock, and execution-ledger safeguards remain in force.
- The Desktop database is the reconciled runtime database. Preserve its matching vault key and terminal profile. Keep both original sources and the verified merge under `server\backups\hosted-cutover-20261110-050612`. Preserve the newer 5% personal maximum open risk setting. Keep all databases, tokens, credentials, logs, and terminal profiles private.

## Last observed state

- The read-only readiness check confirmed the correct hosted account and portable paths. `hosted_2` subsequently reached Active. All 10 expired instructions were skipped and there were no pending hosted entries at the later snapshot.
- At the timestamp above, GOLD was scanning, hosted execution was Active, Personal MT5 was Ready, and News Lock was off. Verify these live values again before taking any action. The earlier locked readiness checks placed no orders.
- The API and shared ngrok route were healthy. Telegram was connected and the notification worker had delivered a recent alert. A Failed badge can reflect six historical outbox failures, so check the latest heartbeat, delivery, and pending count before changing the worker or retrying any alert.

## How to pick up safely

1. Read the current Git status and verify the running Admin path, API health, News Lock, worker status and timestamps, and the dedicated portable MT5 path. Use read-only SQLite inspection when comparing state.
2. Work on the repair branch or a separate branch. Keep main and the protected recovery commits intact. Ask for explicit approval before restarting production, changing live trading controls, or replacing the installed build.
3. If hosted MT5 fails again, distinguish identity/path, permission, and connectivity errors from the latest sanitized logs. Keep the account identity and duplicate protections in place. Preserve the ledger and existing positions.
4. For source fixes, reproduce the issue with mocks, run `python -m unittest discover -s tests -q` with temporary Owner state, and verify any rebuilt Admin in isolation. Use no live test orders. Record the commit, validation results, EXE hash, and next step in GitHub.
