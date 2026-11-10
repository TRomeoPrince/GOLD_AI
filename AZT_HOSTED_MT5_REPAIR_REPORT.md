# AZT hosted MT5 startup repair

November 10, 2026, Africa/Kampala. Scope: Owner `hosted_2`, JustMarkets-Live7.

## Diagnosis

The user reported that manual authentication and synchronization succeeded, but the terminal disconnected shortly after pressing Start in AZT. The November 10 dedicated terminal journal contains authorization, trading-enabled and disconnection records. The AZT log records repeated starts and two explicit terminal permission failures. The old error combines terminal Algo Trading and Python API permission, so those traces cannot identify which flag failed. A terminal permission error also does not establish why the broker connection dropped.

Read-only Windows evidence showed a running terminal at the exact stored path, `C:\Users\USER\Desktop\Gold_AI\server\hosted_mt5\client_2\terminal64.exe`, with `/portable` in its command line. There was also a separate normal-mode MT5 at a different path. The stored worker PID matched a running `AZT_Admin.exe --service hosted_2` at inspection. No second hosted worker was established by that observation. Repeated log headers alone do not prove concurrent workers or automatic restart. The launcher automatically recovers Telegram roles, while a hosted SafetyStop exits the worker.

Two mocked baseline tests established that the initial attach could call `mt5.login()` after seeing a different account or missing account information. A missing account snapshot is compatible with a transient disconnection. Code inspection also showed that the account mutex was acquired after initialization and account selection, leaving a losing worker able to interact with MT5 before being rejected. These are verified startup hazards. Neither was proven to be the trigger in the live incident.

Portable mode remains enabled for this dedicated installation. The observed process mode supports retaining the existing contract, but does not prove the mode of the earlier manual launch or that both sessions shared one data directory. MetaTrader documents that initialization can launch a terminal and that terminal information exposes installation and data paths. [MT5 initialize](https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py) · [MT5 terminal info](https://www.mql5.com/en/docs/python_metatrader5/mt5terminalinfo_py)

## Repair

- `server/hosted_worker.py::connect_mt5` requires an absolute existing terminal file and attaches without decrypting credentials or calling broker login. A terminal that needs authentication must be signed in to manually with the expected account in its dedicated portable profile.
- `verify_hosted_account` checks connection, account and server, then checks the returned installation and portable data directories. It reports separate terminal Algo Trading, Python API and broker permission failures. Missing connection state follows the existing bounded backoff.
- `run` acquires the existing shared account mutex before initialization, retains it across retries, rejects configuration changes during reconnect, and releases it after IPC shutdown. A losing worker does not clear the active worker's status. Reconnect still advances the fresh-instruction cutoff. No changes to risk limits, claims, execution, acknowledgment, journals or broker positions.
- `tests/test_hosted_mt5_attach.py` adds nine mocked cases for exact portable attach, wrong path/profile, account switching, missing account, disconnect, recovery, permissions, duplicate ownership and shutdown. `tests/test_azt_trading.py` supplies the hosted fixture for the existing startup-backlog test. Existing supervisor tests exercise reuse of an already-running worker.

## Validation and Git

- Before repair: `python -m unittest tests.test_hosted_mt5_attach -q` reproduced both unwanted broker-login calls, 2 failures.
- After repair: `python -m unittest discover -s tests -q` from the Owner virtual environment, with a temporary Owner DB/state and Telegram disabled. **260 passed, 0 failed, 0 skipped.** The test suite uses mocked MT5. Normal-mode hosted attachment is deliberately rejected when its data directory differs. No API contract changed, so the separate Client contract was outside this run.
- Windows build passed with `python -m PyInstaller --clean --noconfirm --distpath dist/hosted_fix_20261110 --workpath build/azt_pyi/hosted_fix_20261110 build/GOLD_AI_Admin.spec`. Artifact: `C:\Users\USER\Desktop\Bots\Forex\AMD1\dist\hosted_fix_20261110\AZT_Admin.exe`. SHA256 `1A6249570FE0CED91E3CB4FA6059F5B68B91D7F51D41F6D21D0E3EB13C234EF8`.
- `GOLD_AI_TEST_EXE` set to that binary and `python tests/smoke_admin_exe.py` passed. The loopback health probe logged a Windows connection reset, followed by successful health responses and cooperative shutdown. Archive inspection verified the patched hosted worker, and launching `--service hosted_2` with a temporary empty DB and an open supervisor pipe exited safely before any MT5 attach. The first probe with stdin closed did not exercise the expected failure path. The corrected probe passed.
- Branch `fix/hosted-mt5-start-20261110`, repair `71f485e2fe9dc6f133169ea616d9bb06a415542f`. Forked from Owner main `c0f7263742438a33fc1c9ba41dedfcfd972655fd`, whose only change from protected Owner `825795d84b8c3dd63b864024fc2641720b269e06` was the baseline document. Protected Client `38d7e54fba60411ddf60f2d8b0bedd5c28ee8591` was retained. No merge, PR or live deployment.

## Original cutover plan (historical)

1. Highest priority: after explicit approval, have the operator stop the current hosted worker cooperatively and verify that its PID and any duplicate have exited. Keep the broker terminal and existing positions under operator control. Verify the dedicated terminal shortcut/process mode and its **File → Open Data Folder** result before attempting another start.
2. Verify the expected account and server locally. Check the terminal Algo Trading and external Python API settings and broker-side account permissions without bypassing a restriction. Record sanitized timestamps and flag states, never credentials or login numbers.
3. After an approved binary cutover, perform one controlled attach observation with trade dispatch disabled. Compare terminal PID, installation/data paths, connection and permission flags, AZT log, and terminal journal before and after. A mode mismatch, provider network disconnect, or permission change still needs independent evidence. If disconnect recurs, stop and preserve logs rather than retrying repeatedly.

At this stage, the Desktop installation still held the prior verified recovery binary. Diagnostics used read-only process information, log summaries and a read-only SQLite lookup of the hosted path and PID. No live attach, login, position change, order, restart or database write was performed. Codex usage was visible; 5% of the short window had been consumed at the intermediate check.

## Follow-up on the false account-change stop

The active Admin was launched from the repair build directory and resolved its runtime home to AppData. The AppData database stored the same login that the dedicated MT5 journal authorized at 04:53:24, but stored `Justmarkets-live7` while the broker reported `JustMarkets-Live7`. The Desktop database and journal showed the same capitalization difference. The prior exact string comparison reproduced the false SafetyStop with simulated MT5. The repeated log headers correspond to separate worker starts. The Admin's automatic restart loop covers Telegram services only.

The worker now accepts ASCII capitalization differences on initial attach after verifying the numeric login. When the saved and reported spellings differ, it holds both account locks before becoming active. This preserves exclusion against Personal Trading and older workers that use the broker's reported spelling. Subsequent checks pin that exact reported identity. Existing journal and execution-claim keys keep their saved spelling. The portable-path and trading-permission checks still apply.

Four regression tests cover case-only attach, a different server and a Unicode lookalike, a busy account lock, and holding both locks through shutdown. All 264 Owner tests passed with a temporary database and simulated MT5.

The Desktop and AppData databases were inspected read-only at this stage. The Admin and hosted terminal continued running until the later approved cutover.

The Windows build and isolated Admin startup/shutdown test passed. All 13 hosted attachment tests also passed against the worker code extracted from the EXE. Build SHA256 `B031B03CDD4C7394447150C36737434DD9020A73218B43F3DB39A6D97FD3AF25`.

## Desktop cutover and verification

Recorded 2026-11-10 05:57:27 EAT (UTC+03:00). The approved cutover closed the old Admin and its workers cooperatively. The verified case-fix build from `d72c474` is installed as `%USERPROFILE%\Desktop\Gold_AI\AZT_Admin.exe`. Launch through `START_GOLD_AI.bat` to pin the Owner home, database, and external Telegram runtime to the Desktop installation.

Both SQLite databases were backed up and checked before merging. The Desktop database supplied client records, pairings, subscriptions, bindings, pending history, and the hosted vault/profile association. Reconciliation carried over the newer personal execution claim and trade records from AppData, retained older trade metadata where the refreshed records omitted it, and preserved delivered Telegram entries as sent. It kept the newer 5% personal maximum open risk setting. The merged database passed integrity and foreign-key checks. The retained backup set includes both AppData snapshots, the original Desktop files, the verified merge, and the reconciliation script.

During readiness verification, News Lock blocked entries. The first read-only IPC check timed out during terminal startup. The Desktop journal then showed authorization and synchronization, and attachment to the running terminal confirmed the expected login, server, installation path, and portable data path. The permission check correctly reported Algo Trading off. After the terminal was ready, `hosted_2` reached Active and its heartbeat advanced. It marked 10 expired instructions skipped and preserved the existing review record. The API, GOLD feed, ngrok route, and Telegram were verified. The readiness checks placed no orders.

At the later read-only observation, the GOLD engine was scanning, `hosted_2` was Active, Personal MT5 was Ready, and News Lock was off. The hosted queue had no pending instructions. The notifications worker had delivered a recent alert. The dashboard Failed badge reflected six older alerts that had exhausted retries. The cleanup recycled the draft merge, redundant rollback copies, and duplicate local handoffs while retaining the verified backups and runtime.

[Current continuation prompt](AZT_CONTINUATION_PROMPT_UPDATED_AT_2026-11-10_05-57-27_EAT.md)
