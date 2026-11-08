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

## Verified recovery and handover

**Checkpoint:** November 9, 2026, 00:14 EAT (Africa/Kampala). Source repairs, isolated verification and offline owner staging have been completed. Production cutover requires explicit approval.

| Repository | Recovery branch | Tested application source |
| --- | --- | --- |
| [GOLD_AI](https://github.com/TRomeoPrince/GOLD_AI/tree/recovery/azt-system-20261108) | `recovery/azt-system-20261108` | `661edd1eeb7d84efa4411fdcb1c05b8a85114ef7` |
| [GOLD_AI_client](https://github.com/TRomeoPrince/GOLD_AI_client/tree/recovery/azt-2026-11-08) | `recovery/azt-2026-11-08` | `f6af047287e0e23cac45e626a3b4c3ab35a80021`; packaging and docs at `38d7e54fba60411ddf60f2d8b0bedd5c28ee8591` |

Both recovery branches were pushed. The owner branch tip after handover is a documentation commit on top of the tested code. Remote main was inspected at `c5bb4a3` for Owner and `ad49d96` for Client. The recovery was based on the already integrated November 4 revisions. No historical commit was blamed for the entire outage. The Oct 28 Client source `f369e40` contains the discarded-reconnect-response behavior that was reproduced against the current reservation API.

### Files changed

Paths are relative to the named checkout.

| Files | Purpose |
| --- | --- |
| Owner `server/owner_paths.py`, `server/credential_vault.py`, `server/hosted_manager.py`, `server/store.py` | Consistent owner, project, state and DB paths; validation of stored risk values in the store |
| Owner `server/admin_launcher.py`, `server/admin_workspace.py` | Owned-process status, API health, limited Telegram crash recovery, and global policy availability instead of a fictional risk process |
| Owner `server/app.py`, `server/hosted_executor.py`, `server/signal_engine.py` | Fail-closed policy responses and sizing, calibrated daily risk history, SQLite lock retries using durable signal keys and cooperative status |
| Owner `server/client_telegram.py`, `server/client_notifications.py`, `server/telegram_delivery.py` | Local poller mutex, orderly stop, text fallback, and independent outbox processing |
| Owner `scripts/prepare_owner_install.py`, `scripts/restart_admin.ps1`, `START_GOLD_AI.bat`, `server/run_owner_stack.bat`, `build/build_admin.bat`, `.github/workflows/build-windows-admin.yml`, `.gitignore` | Read-only backup and exclusive offline install, current AZT launch/build paths and Windows CI artifact naming |
| Owner `tests/test_azt_business.py`, `tests/test_personal_trading.py`, `tests/test_standalone_admin_db.py`, `tests/test_telegram_sidecars.py`, `tests/test_azt_notifications_cards.py`, `tests/test_client_telegram.py`, `tests/test_telegram_event_queue.py`, `tests/test_telegram_presentation.py` | Regression coverage for the changes above |
| Owner `AZT_RECOVERY_PROGRESS.md`, `AZT_CONTINUE_PROMPT.md` | Checkpoint and exact continuation instructions |
| Client `app.py`, `client/manager.py`, `client/runtime.py`, `client/executor.py` | Worker status, reconnect reservation, risk validation and calibrated daily loss/profit |
| Client `tests/test_client_safety.py`, `tests/integration_contract.py` | Risk, outage, authorization, dispatch, mock execution and durable ACK tests |
| Client `.gitignore`, `build/build_client.bat`, `build/package_client.bat`, `AZT_CLIENT.md`, `CUSTOMER_README.txt` | Rebuild, packaging, and customer setup |

Relocations: `backtest_sweep_flip.py` → `research/backtest_sweep_flip.py`. Its module help passed with `python -m research.backtest_sweep_flip --help`. `ADMIN_BUILD_RESULT.md` → `Docs/archive/ADMIN_BUILD_RESULT.md`. Git history and tracked references were checked before moving either file. There were no deletions. The Headway runner still imports the demo helper, so both remain at their existing entry points.

### Verification and artifacts

- Owner: `python -m unittest discover -s tests -q` under the owner virtual environment with a temporary DB and disabled Telegram credentials. **251 passed, 0 failed, 0 skipped.** Earlier baseline passed 237 tests. Deliberately reproduced defect cases failed on the baseline and passed after repair.
- Client: `python -m unittest discover -s tests -q` under its own virtual environment. **45 passed, 0 failed, 0 skipped.** Source and frozen GUI checks and a disabled frozen worker check passed. The disabled worker created no execution claim and returned STOPPED.
- In-process integration: from the Client checkout, run the owner virtual environment Python with `tests/integration_contract.py C:\Users\USER\Desktop\Bots\Forex\AMD1`. Passed pairing and account isolation, payments/referrals, history recovery, UTC trial expiry, transport outage, reauthorization and fresh reservation, mock USC order submission, durable ACK and duplicate suppression. Strategy publication and SQLite contention were exercised separately with deterministic engine fixtures.
- Admin frozen checks: set `GOLD_AI_TEST_EXE` to the recovery Admin path and run `tests/smoke_admin_exe.py`, `tests/smoke_admin_exe.py --standalone`, and `tests/smoke_personal_exe.py`. All passed. The GUI check exercised seven pages, engine Start/Stop/Start, Telegram-only reload, API health, preservation of seeded records and exit. Standalone used temporary AppData and bundled workers. The standalone API emitted its 10-second graceful-timeout log before exiting normally. No forced kill occurred in these checks.
- Frozen `--verify-signal-bundle` passed with pandas 2.3.3 and NumPy 2.5.4. The archive includes the three byte-matched approved image assets, current worker modules, and no owner DB, vault, personal settings or .env. Client archive inspection verified the required customer modules and assets.
- Build environment was Windows x64, Python 3.13.15, and PyInstaller 6.22.3 for Owner. Reproduction commands: `python -m PyInstaller --clean --noconfirm --distpath dist_recovery_20261109 --workpath build/azt_pyi/recovery_20261109 build/GOLD_AI_Admin.spec` in Owner, and `python -m PyInstaller --clean --noconfirm --distpath dist_rebuild_20261109 --workpath build/rebuild_20261109_pyi build/GOLD_AI_Client.spec` in Client. The updated Client packaging wrapper produced and checked the ZIP.
- Non-fatal diagnostics: PyInstaller reported optional Jinja2 missing, FastAPI TestClient emitted a Starlette deprecation warning, and a mocked Telegram card failure logged the expected text fallback. The binaries and tests above passed despite those messages. Remote CI and live broker/Telegram service checks were outside this verification.

| Artifact | Local path | SHA256 |
| --- | --- | --- |
| Admin | `C:\Users\USER\Desktop\Gold_AI\AZT_Admin.exe` | `A47B2574CBABE530C8BA4312DFAB12135624AC2CB1D729DC4D7FEFA4040645E7` |
| Client | `C:\Users\USER\Desktop\Bots\GOLD_AI_client\dist_rebuild_20261109\AZT_Client.exe` | `2EF8F7CBF4152A5E9A22918B046DD0F6E0966DC7E67707A236DC9133498E72A9` |
| Client distribution | `C:\Users\USER\Desktop\Bots\GOLD_AI_client\release\AZT_Client.zip` | `FE9753C92535F028C051FB930AA41DB19201D269156749DC26D4E57500788305` |

### Installation and safety

- The authoritative owner installation was staged at `C:\Users\USER\Desktop\Gold_AI`. Its source archive includes Admin, API, engine, risk, hosted and personal infrastructure, Telegram and maintenance, scripts and assets. The prior local Admin/Client executables and APK were retained and verified byte-identical.
- The new installation virtual environment was created at its final path and populated with the versions in the tested owner environment. Its `python -m pip check` passed.
- Re-ran the isolated Admin smoke from the actual Desktop installation and installed Python. It passed with API, engine, external Telegram worker reload and cooperative shutdown. The loopback probe logged one Windows connection reset and the API used its configured 10-second graceful shutdown window. The API endpoint closed, the launcher exited with code zero, and no worker needed a forced kill.
- The read-only SQLite backup and copied owner state are at `C:\Users\USER\AppData\Local\AZT-Recovery-Backups\20261109-owner-before-cutover`. The SQLite backup passed `PRAGMA quick_check`. The old AppData database and config hashes matched before and after staging. The installed database matches the checked backup. Configuration was copied verbatim, including credentials. No secrets are included in the Git branches or binary archives.
- The launch wrapper sets all five owner paths under the Desktop installation, points the database at `server\gold_ai_server.db`, and selects source Telegram workers when the installation virtual environment is available. Run the reload command from the installation directory. Account mutex files remain at the shared Windows location to protect against duplicate execution across versions.
- All runtime checks used isolated temporary paths, simulated MT5 and mocked Telegram. The existing production database was opened read-only only for backup. No live order, real Telegram test send, production restart or merge to main occurred.

For the first production start, obtain approval, check that the old owner and workers are stopped, and confirm that the staging snapshot is current. Then run:

```powershell
Set-Location 'C:\Users\USER\Desktop\Gold_AI'
& '.\START_GOLD_AI.bat'
```

For later Telegram source reloads from the installed directory:

```powershell
& '.\.venv\Scripts\python.exe' -m server.telegram_admin reload
```

To reproduce the offline staging on an unused destination, run `scripts/prepare_owner_install.py --revision 661edd1 --source <existing-owner-home> --target <unused-install-home> --backup <new-private-backup-directory> --exe <verified-AZT_Admin.exe>` with the owner Python. Create a new virtual environment at the target and install the verified owner dependencies. Do not rerun the installer over this prepared installation.

### Remaining work

1. Obtain approval for the first production start. Confirm the staged DB is current if any old installation was run after the snapshot. Inspect the staged API and worker statuses only during an approved cutover.
2. Reproduce stale Client ACK after Admin resolves a reserved delivery as `ERROR_REVIEW`. Extend the current account-scoped API with an explicit terminal reconciliation result only if the reproduction confirms a permanent retry loop. Preserve both durable ledgers, account binding and fresh-signal gating.
3. Verify real Telegram authentication/delivery and live broker connectivity only with explicit approval. The simulated history offset matches the current AZT clock model. Different broker behavior still needs a read-only broker check. The Telegram mutex covers updated pollers on the same Windows host.
4. Review both recovery branches with the user before merging. The previous GitHub release assets remain the historical release; the recovery binaries are at the local paths above.

The short Codex window showed 68% consumed and the weekly window 11% at the last check before handover. This checkpoint reserves capacity for final validation and the continuation documents.
