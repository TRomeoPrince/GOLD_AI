# #WORKING — AZT Recovery Baseline and Project Handover

> **Reference marker:** `#WORKING`
> **Recorded:** 2026-11-09 (Africa/Kampala)
> **Meaning:** the currently recovered, merged, **offline-tested** state of AGORA ZION TRADER (AZT). This is a reproducible code baseline, **not** a guarantee of successful live trading, MT5 connectivity, or Telegram delivery.

## 1. Immutable source snapshot — DO NOT LOSE THESE SHAs

| Component | Repository | Exact recovery baseline commit |
| --- | --- | --- |
| Owner / Admin / API / Telegram / signal engine | [TRomeoPrince/GOLD_AI](https://github.com/TRomeoPrince/GOLD_AI) | [`825795d84b8c3dd63b864024fc2641720b269e06`](https://github.com/TRomeoPrince/GOLD_AI/commit/825795d84b8c3dd63b864024fc2641720b269e06) |
| Windows Client | [TRomeoPrince/GOLD_AI_client](https://github.com/TRomeoPrince/GOLD_AI_client) | [`38d7e54fba60411ddf60f2d8b0bedd5c28ee8591`](https://github.com/TRomeoPrince/GOLD_AI_client/commit/38d7e54fba60411ddf60f2d8b0bedd5c28ee8591) |

Both exact snapshots were confirmed identical to their respective `main` branch HEADs **before this handover documentation was committed**. Subsequently `main` may move. Always compare to the **full SHAs above**, not whatever `main` points to later. This Markdown handover adds documentation only to the Owner repository and does not change the recovery application code.

**Instruction for future chats:** Whenever the user says **`#WORKING`**, interpret that as **this exact two-repository commit pair**, unless they explicitly announce a newer `#WORKING` baseline. Do not infer that a later commit, build, tag, or local installation is the same state.

## 2. Project and architecture

AZT, formerly GOLD_AI, comprises:

- **Owner/Admin:** Windows GUI supervising the FastAPI service, signal engine, risk-policy enforcement, personal MT5 execution, hosted execution, Telegram command polling, trade-event notifications, maintenance, subscription and account administration, manual payments, referrals, promo/trials, journaling and PnL views.
- **Client:** Separate Windows GUI and MT5 execution workers for individually authorized accounts, risk-policy retrieval, subscriptions, connection recovery, execution acknowledgment, journal, payments, messages and referrals.
- **State and safety:** SQLite account, delivery, trade, subscription and notification records; durable reservation/claim and acknowledgment logic; account-scoped authorization, account locks and no backlog/replay of stale or uncertain trade instructions.
- **Symbols and currency:** Broker-local XAUUSD/GOLD symbol resolution, UTC-based broker timing, per-account/native-currency presentation, including USC instead of incorrectly showing USD.
- **Android:** A separate planned companion. No claim that an Android APK was completed or verified during this recovery.

The Owner and Client are separate GitHub repositories. Do not merge their Git histories or replace either with the other.

## 3. Current progress: verified offline recovery

The November 8–9 recovery effort reports:

- **Owner:** 251 automated tests passed, 0 failed, 0 skipped.
- **Client:** 45 automated tests passed, 0 failed, 0 skipped.
- **Integration:** isolated in-process Owner–Client API contract passed using mock execution and temporary SQLite state.
- **Windows:** Admin and Client were built with PyInstaller and exercised through source/frozen smoke checks. Admin GUI navigation, API/engine Start–Stop–Start, Telegram-only reload, packaged assets, cooperative shutdown and standalone startup passed in isolated environments.
- **Owner fixes:** prevent malformed/corrupt risk policies from expanding limits; reject broker-minimum lot/risk violations; correct simulated daily-loss timing; retry SQLite contention safely; handle Telegram poller shutdown, notification fallback and queue processing; report actual worker heartbeat states and retry only owned Telegram workers.
- **Client fixes:** reconnect/reserved response handling, fail-closed risk parsing, daily risk/history timing, expired-session recovery and accurate worker status; repaired standalone build and packaging entry points.
- **Repository organization:** moved `backtest_sweep_flip.py` to `research/`, and `ADMIN_BUILD_RESULT.md` to `Docs/archive/`. Retained demo helpers still imported by active tooling. No confirmed-useful files deleted.

These are the *recorded results* of the recovery run; the current chat independently verified the GitHub SHAs and branch comparisons, **not** the Windows test execution or locally staged binary checks.

## 4. Windows installation and local backups

**Authoritative intended Owner installation:**

```text
C:\Users\USER\Desktop\Gold_AI
```

The recovery report says this folder was staged with `AZT_Admin.exe`, Owner source, a working `.venv`, Telegram workers, copied configuration and a checked SQLite snapshot. **Staging is not the same as an approved live cutover.**

**Reported local pre-cutover backup:**

```text
C:\Users\USER\AppData\Local\AZT-Recovery-Backups\20261109-owner-before-cutover
```

Preserve all original AppData state, backups, `.env`, encryption keys, personal-account configuration, runtime logs, MT5 installations and both account-delivery ledgers. These are **local files**, not automatically included when cloning GitHub.

**Reported local build artifacts (not GitHub release downloads):**

| Artifact | Path | Reported SHA256 |
| --- | --- | --- |
| Admin | `C:\Users\USER\Desktop\Gold_AI\AZT_Admin.exe` | `A47B2574CBABE530C8BA4312DFAB12135624AC2CB1D729DC4D7FEFA4040645E7` |
| Client | `C:\Users\USER\Desktop\Bots\GOLD_AI_client\dist_rebuild_20261109\AZT_Client.exe` | `2EF8F7CBF4152A5E9A22918B046DD0F6E0966DC7E67707A236DC9133498E72A9` |
| Client ZIP | `C:\Users\USER\Desktop\Bots\GOLD_AI_client\release\AZT_Client.zip` | `FE9753C92535F028C051FB930AA41DB19201D269156749DC26D4E57500788305` |

All paths and binary hashes in this section come from the prior Work recovery report; local files have **not** been accessed or reverified during the creation of this document.

## 5. What remains incomplete

1. **Live cutover:** first approved production startup of the staged Owner installation, confirming no old workers/API listeners are active and checking for AppData changes after the backup. Start the Admin only when authorized.
2. **One unresolved protocol issue:** reproduce a late Client ACK after Admin manually resolves a reserved instruction as `ERROR_REVIEW`. Investigate `server/app.py::ack_instruction`, Owner `server/azt_store.py` acknowledgment/reconciliation, Client `client/runtime.py::flush_acks`, and `tests/integration_contract.py`. Preserve account scope, idempotence and both ledgers. Do not replay uncertain orders.
3. **Real connectivity:** read-only MT5 connection verification and controlled Telegram authentication/delivery test require explicit approval; no live trade or real Telegram test send was performed in the recovered offline test suite.
4. **CI:** no independently confirmed PR-triggered workflow run for the recovery tips in the current GitHub check; local Windows test results were documented separately.
5. **Future development:** Android companion, additional trading management/trailing rules and other AZT enhancements should start from `#WORKING` with focused regression tests, not replace it.

## 6. Safety rules for future changes

- Create a **new branch** from the exact baseline commit for each experiment; do not reset or force-push `main`.
- Keep `#WORKING` unchanged as a historical reference. Assign a **new** versioned baseline only after successful tests and an explicit user decision.
- Run mock/simulation-based tests first. Never send real orders, modify positions, message Telegram recipients or start production without authorization.
- Preserve risk ceilings, daily-loss rules, account identity, subscriptions, no-stale/no-backlog, durable claims, manual reconciliation and no replay after uncertain execution.
- Keep Owner and Client revisions compatible. Verify both suites and their API contract before merging.
- **Code rollback is not data rollback.** Do not replace an active SQLite DB with an older snapshot unless deliberately approved after reconciling newer trades, subscriptions, payments, and pending execution states.
- For debugging, record the current branch, `git rev-parse HEAD`, `git status`, logs, build hashes and the observed fault, then compare against the pinned `#WORKING` SHAs.

### How to inspect the historical baseline safely

```powershell
# Owner — read-only checkout in a separate directory
git clone https://github.com/TRomeoPrince/GOLD_AI.git AZT_OWNER_WORKING_REFERENCE
Set-Location AZT_OWNER_WORKING_REFERENCE
git checkout --detach 825795d84b8c3dd63b864024fc2641720b269e06

# Client — perform separately in another directory
git clone https://github.com/TRomeoPrince/GOLD_AI_client.git AZT_CLIENT_WORKING_REFERENCE
Set-Location AZT_CLIENT_WORKING_REFERENCE
git checkout --detach 38d7e54fba60411ddf60f2d8b0bedd5c28ee8591
```

**Do not run these detached reference checkouts against production databases or workers.** A reference checkout is only for source comparison, not a fully installed runtime.

## 7. New-project transfer instructions

Start a new ChatGPT project with this exact orientation:

> Continue **AGORA ZION TRADER (AZT)**. Read `WORKING_BASELINE.md`, `AZT_RECOVERY_PROGRESS.md`, `AZT_CONTINUE_PROMPT.md` in the Owner repo and `AZT_CLIENT.md` in the Client repo. The label **#WORKING** identifies Owner commit `825795d84b8c3dd63b864024fc2641720b269e06` and Client commit `38d7e54fba60411ddf60f2d8b0bedd5c28ee8591`. These are offline-tested recovery snapshots, not proven live deployment. Inspect current `main` before changing anything, retain both baselines for comparison, and prioritize resolving stale ACK/manual-reconciliation behavior and approved read-only service verification. Use a new branch, run simulated Owner, Client and integration tests, preserve state and risk protections, and save an accurate handover before limits are reached.

## 8. Related documentation

- [AZT recovery progress](AZT_RECOVERY_PROGRESS.md) — detailed defects, tests, files, artifacts, migration and remaining work.
- [AZT continuation prompt](AZT_CONTINUE_PROMPT.md) — focused next debugging task.
- [Original AZT release notes](AZT_RELEASE.md).
- [Telegram update notes](TELEGRAM_UPDATE.md).
- [Client notes](https://github.com/TRomeoPrince/GOLD_AI_client/blob/main/AZT_CLIENT.md).

**Status:** **#WORKING = verified recovery-source baseline + mocked/isolated Windows validation; live production behavior pending approval and observation.**
