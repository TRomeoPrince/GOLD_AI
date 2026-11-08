# Resume AZT after the verified November 9 recovery

Read `AZT_RECOVERY_PROGRESS.md` in the [Owner recovery branch](https://github.com/TRomeoPrince/GOLD_AI/tree/recovery/azt-system-20261108) first. Use the latest checkpoint and verify both working trees with `git status --short --branch` and `git log -3 --oneline`.

- Owner source: `C:\Users\USER\Desktop\Bots\Forex\AMD1`, branch `recovery/azt-system-20261108`, tested application source `661edd1eeb7d84efa4411fdcb1c05b8a85114ef7` plus a later handover documentation commit.
- Client source: `C:\Users\USER\Desktop\Bots\GOLD_AI_client`, branch `recovery/azt-2026-11-08`, tested runtime `f6af047287e0e23cac45e626a3b4c3ab35a80021`, packaging head `38d7e54fba60411ddf60f2d8b0bedd5c28ee8591`. [Client recovery branch](https://github.com/TRomeoPrince/GOLD_AI_client/tree/recovery/azt-2026-11-08)
- The owner installation is staged at `C:\Users\USER\Desktop\Gold_AI` with the verified Admin EXE, owner source, .venv, configuration and a checked SQLite copy. The checked backup is at `C:\Users\USER\AppData\Local\AZT-Recovery-Backups\20261109-owner-before-cutover`. Keep both installations offline until the user authorizes production startup. The previous AppData source and older Desktop binaries were retained.

The baseline work is complete. Owner 251 tests, Client 45 tests, isolated Windows launches and the actual in-process Owner–Client API contract passed. See the report for exact commands, warnings and SHA256 values. Avoid repeating builds unless executable source or dependencies change.

The next technical investigation is stale acknowledgment after manual reconciliation. In a temporary DB, reserve a signal, record a pending Client ACK, and have Admin reconcile that delivery to `ERROR_REVIEW` before Client flushes the ACK. Start with:

- `server/app.py` in Owner, function `ack_instruction`.
- `server/azt_store.py` in Owner, functions `acknowledge_account_instruction` and the Admin reconciliation logic.
- `client/runtime.py` in Client, method `flush_acks`.
- `tests/integration_contract.py` in Client, the existing isolated FastAPI contract harness.

Check whether a late HTTP 404 permanently blocks delivery progress. If confirmed, implement an explicit authenticated, account-scoped reconciliation result and an idempotent Client transition that preserves both ledgers and still prevents replay. Distinguish an already reconciled delivery from a missing, unauthorized or wrong-account delivery. Add a focused regression and rerun the combined API contract. Treat this as a new repair, since the previous session identified the possibility and did not claim it was fixed.

For a user-approved production cutover, recheck for existing owner workers and API listeners, and check whether AppData state changed after the backup. Preserve any newer data before activation. After approval, start with `& 'C:\Users\USER\Desktop\Gold_AI\START_GOLD_AI.bat'`. Verify status and log paths from the staged installation. Real Telegram delivery, live broker connectivity, and starting production trading require separate explicit approval. All development tests use temporary state, simulated MT5 and mocked Telegram. Never place live test orders, overwrite production credentials, erase pending/uncertain claims, weaken risk limits or merge to main without approval.

Keep work on recovery branches. Record remaining usage and update both checkpoint documents with exact changes, tested commits, commands and remaining issues before stopping.
