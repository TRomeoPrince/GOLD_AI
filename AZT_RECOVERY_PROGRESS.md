# AZT recovery progress

## Baseline checkpoint

- Date: 2026-11-08, Africa/Kampala.
- Owner repository: `TRomeoPrince/GOLD_AI`. Recovery branch `recovery/azt-system-20261108` started at `2625689`; remote main at `c5bb4a3`.
- Client repository: `TRomeoPrince/GOLD_AI_client`. Recovery branch `recovery/azt-2026-11-08` started at `a5ab196`; remote main at `ad49d96`.
- Fetched both remotes. Local November 4 integrations are present. The October 28 release and October 29 cleanup are historical baselines.
- Windows target: `C:\Users\USER\Desktop\Gold_AI`. At intake it contains legacy Admin/Client EXEs and an APK. Existing owner configuration and database are in `%LOCALAPPDATA%\GOLD_AI`. No owner listener on 8765 or matching launcher process was found at intake.
- Sanitized status reads found previous STOPPED Telegram/notification state and old SCANNING/READY records. A stale file alone does not establish a process failure. Historical engine logs include missing-pandas failures. Current source already contains the packaging fix; re-verify the binary.
- No trading or Telegram test sends. No production database contents queried or modified at intake.
- Next: finish isolated baseline suites, reproduce regressions, preserve legacy data before staging the Desktop installation, then exercise binaries and the combined API.
- Budget snapshot: 4% of the short Codex window and 1% of the weekly window consumed at initial check. Reserve capacity for verification and handover.

## Repair checkpoint

The owner baseline passed 237 tests. Baseline reproductions with temporary databases and simulated MT5 found four owner failures: a 1.0% broker minimum accepted against a 0.9% selected cap, a 6% simulated daily loss missed by an unadjusted broker-time query, a corrupt risk setting widening the cap to 2%, and an SQLite BUSY exception stopping the signal engine after one durable write. The repairs passed 97 targeted owner risk and signal tests. Current signal age, account identity, idempotency and absolute risk ceilings remain enforced.

The four targeted Telegram failure reproductions covered rendering errors dropping text, invalid display settings preventing runtime delivery, reminder exceptions skipping the outbox, and a poller processing new commands after shutdown. The Telegram repair suite passed 83 focused tests. Historical evidence includes 70 polling timeout strings, 32 owner delivery timeout strings, one forced shutdown record and 60 missing-pandas engine tracebacks. The historical transport failure does not establish a commit as the cause.

The updated Client fixed a reserved response discarded during reconnect, fail-open malformed risk policy fields, shifted history, expired-session retry handling and failed status before a heartbeat. The 45 Client tests, source and frozen UI checks and real in-process Owner–Client API test passed with simulated execution. A stale ACK after manual Admin review is a separate protocol question and still needs investigation.

The launcher now unifies source and state paths, reports stale and failed heartbeat states, and retries only owned Telegram workers that crash, with a bounded backoff. Standalone, worker and path checks passed 16 targeted tests. The isolated Client/Owner contract passed on the combined tree. The current phase is final owner test/build verification and offline staging at the requested Desktop path.
