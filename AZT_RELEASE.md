# AGORA ZION TRADER (AZT) release - 28 October 2026

## Delivered applications

| Application | Final Windows EXE | SHA256 |
| --- | --- | --- |
| Admin | C:\Users\USER\Desktop\Bots\Forex\AMD1\dist_azt\AZT_Admin.exe | EDB3A78A8C328EE656220627A771396BAB717538BCB717D8E19628C48A54C340 |
| Client | C:\Users\USER\Desktop\Bots\GOLD_AI_client\dist_azt\AZT_Client.exe | DA2951C1A804C3E7398EE711F76C073CF724B151E2B9F9BCCF7B5B507B8C91D9 |

Both builds PASS: clean PyInstaller 6.22.3, Python 3.13.15, Windows x64, single-file/windowed packaging using the existing spec files. The background and both official PnL templates were extracted from each EXE archive and matched byte-for-byte to the supplied originals. Private databases, credentials and profiles are not packaged.

Client final commit: 57ae8581816d6f142d1efc5697fbf30633fdf6b6 (runtime merge e07b483bf5d79e25629fb65b4d6d48d46669fde1). The Client repository's nine newer upstream commits through c409e0f were merged without rewriting history. Their strict policy risk cap, subscription wrapper, ngrok headers and build workflow were preserved/adapted. The Admin commit is the commit containing this report; obtain it with `git log -1 --format=%H -- AZT_RELEASE.md` or the final chat response.

## What changed

- Both apps have AZT branding, a dark navy/gold workspace derived from BACKGROUND.jpg, maximized/resizable startup, wrapping actions, scrollable pages and tables. Admin: Dashboard, Clients, Trades, Journal, Telegram, Risk, Settings. Client: Dashboard, Trades, Journal, Referrals, Payments. Detailed service counts/logs are on Telegram rather than a giant dashboard status strip.
- Admin dashboard cards show engine/personal/API/ngrok/Telegram/notification/news state, account PnL/positions, client counts and subscription alerts. Unknown account data stays unavailable rather than appearing as an invented live result.
- Client management supports edit, activate, pause, revoke, confirmed archive, renew/extend, risk, plans, account allowances and account enable/disable. Archive retains trade/payment/message history and revokes new access/sessions.
- In-app messages work without Telegram, with read/unread state, selected-client messages and broadcasts to active clients. Optional Telegram copies use a durable queue with delivery/retry/failure/held status and destination isolation. Failed command replies remain visible.
- Telegram preserves onboarding/help/status/subscription and adds positions, daily journal and PnL-card requests. Display uses each user's timezone. Linked chats and recent command/delivery details are available in Admin. Failed alert retries do not retry orders.
- Official PROFIT.jpg/LOSS.jpg generate output copies with actual observed trade values. Example values embedded in the supplied templates are covered completely; unknown entry/risk/strategy stays unknown. New observed open/closed events can queue cards; initial history sync does not flood old alerts. Closed result labels use actual broker reasons when available. Different currencies are never added into a misleading combined PnL total.
- Trades/journals use read-only broker snapshots, net closed PnL including costs, account scope and UTC storage with IANA display conversion. Recent broker history is synchronized while workers run (default lookback 30 days); previously captured history is retained in SQLite. No old trade is executed by history synchronization.
- Plans configure price/currency/duration/trial/account allowance. Expiry is enforced before new instructions/orders and monitored in the background. Reminder timing is configurable (default 3 days, 1 day, expiry). Paid renewal extends an active expiry; expired access restarts from approval time. An explicit client pause/revoke is not overridden by payment approval.
- Payments presents one selected method/network, amount due and copy action. The eight exact receiving options supplied by the owner are implemented. MTN/Binance use bounded PNG/JPEG proof; crypto methods accept a transaction hash. All submissions require manual review, and approving the same payment cannot extend access or award commission twice. No QR codes or pretend blockchain verification are included.
- Referrals have codes/usable invitation links, counts, active referrals, earned/pending rewards/history and configurable percentage/fixed rewards. Self-referrals/cycles and reassignment after payment are blocked. Rewards follow approved payments and are disabled until configured; prices remain unset until the owner chooses them.
- Promo/giveaway codes configure plan, duration, expiry, total uses, per-user account limit, enabled state and repeat-use policy. Concurrent redemption limits are transactional. Repeat use never multiplies account slots; gifts do not downgrade existing paid access. Admin can inspect redemptions and disable future use.
- Multiple Client-PC MT5 accounts run in separate hidden processes/terminal installations, with server-enforced user/plan/promo allowances. The existing hosted manager retains its per-client hosted-terminal workflow; increasing an allowance does not automatically provision extra hosted terminals.
- Market instructions are generic (GOLD/XAUUSD); each terminal independently resolves a validated local XAUUSD/GOLD symbol, including broker suffix/prefix variants. Owner-specific symbols are not forced onto customer brokers.
- Personal and client desired state survives temporary disconnects. Backoff, degraded alerts, recovery, identity checks, no-backlog cutoffs, 20-minute stale / 60-second future limits and durable claims remain enforced. Client Start also works while initially offline; rapid Stop/Start waits for the prior worker to exit. All execution routes on the same PC share the account lock. Personal execution remains independent of registration/subscriptions.
- Cross-PC duplicate prevention reserves an instruction in SQLite BEFORE returning it. Only one unresolved dispatch is allowed per MT5 account, preventing concurrent sizing races too. Lost responses are never automatically replayed/released. After 60 seconds, an unresolved delivery produces an in-app notification/owner event. Reconcile actual broker history in Clients -> Accounts -> Execution Review, then explicitly resolve it; this permits fresh signals without resending the uncertain instruction.
- Admin starts API, engine, Telegram, owner notifications and maintenance as hidden children. Personal execution remains explicitly enabled separately. Admin-started hosted workers now share its cooperative child lifecycle. Closing apps stops their owned workers; existing broker positions/SL/TP remain. Independently shared ngrok is preserved and reused.

## Database and local-state migration

Migration is additive/idempotent and runs automatically on first new Admin startup. Before upgrading an existing legacy owner database, SQLite creates a unique backup beside it:

`C:\Users\USER\Desktop\Bots\Forex\AMD1\server\gold_ai_server.pre_azt_<UTC timestamp>_<unique id>.backup.db`

The backup is taken before schema changes. Failure to create it stops migration. Existing client/risk/subscription rows, encrypted hosted credentials, queues and execution journals are retained. Explicit subscription expiry dates are preserved. Legacy TRIAL access with blank expiry becomes a finite configured trial (default seven days from upgrade); legacy ACTIVE access with blank expiry receives its plan duration (default 30 days from upgrade). Review these timers after upgrade. No real owner DB was migrated during testing.

Extended columns: clients archived_utc/display_timezone/max_mt5_accounts; sessions account_id; subscriptions max_mt5_accounts/access_kind; payment_requests method/proof/transaction_hash/duration_days/max_mt5_accounts/review_note/approved_utc; owner_telegram_outbox media_path.

New business tables: azt_plans, client_mt5_accounts, account_instruction_deliveries (including dispatched_utc), azt_messages, azt_events, referral_codes, referral_links, referral_rewards, promo_codes, promo_redemptions. Additional notification/telemetry tables: azt_telegram_delivery, azt_telegram_commands, azt_account_snapshots, azt_trades, azt_execution_details. Indexes protect account identity and event/reward/redemption/delivery uniqueness.

Owner workspace settings use server/workspace_settings.json. Existing .env names, personal_account.json, gold_ai_server.db and account-lock paths remain compatible. Client profiles remain under `%USERPROFILE%\.gold_ai_client`, with atomic settings/desired-state files, runtime logs and execution_ledger.db. Do not delete execution journals to retry uncertain submissions.

## Validation

- PASS: full owner suite, 167 tests, including all existing tests and business/ASGI, UTC/symbol, reconnect, duplicate/backlog, payment/promo/expiry/account-limit, notification/card and hosted lifecycle checks.
- PASS: full Client suite, 33 tests, including a broker minimum of 1.5% rejected under a 0.9% policy, nonfinite risk rejection, durable claims, initial offline Start, rapid Stop/Start and final Stop/account checks after a slow policy request.
- PASS: isolated real Client API wrapper/FastAPI contract with a temporary DB: auth, preferences, subscription/expiry, plans/methods, messages/read, manual payments/approval, referrals/promos, telemetry/trades/journal and no-backlog query. No external server was used.
- PASS: source and packaged Admin lifecycle: API health, engine Start/Stop/Start, personal controller/settings path, all seven pages at common laptop sizes, seeded client/risk/subscription preservation and clean child/API shutdown without a forced launcher kill.
- PASS: source and final packaged Client UI: five pages with populated fixtures at 1024x768, 1280x800, 1366x768 and 1440x900; Start/Stop footer remains reachable and payment details appear only for the selected method/network.
- PASS: frozen personal-worker missing-settings path rejects safely without attaching MT5.
- PASS: packaged asset byte hashes and absence of private app state; original templates unchanged; git diff checks.
- Isolated source previews of both apps were also visually inspected with the computer-use skill. Preview windows had no trading account/services enabled.
- No live order, actual MT5 connection, real payment, Telegram test message, production app restart or production database migration was performed in verification. Broker execution was simulated/mocked only.

## Exact verification and build commands

Owner checkout:

```powershell
Set-Location 'C:\Users\USER\Desktop\Bots\Forex\AMD1'
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe tests\smoke_admin_exe.py --source
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --distpath dist_azt --workpath build/azt_pyi build/GOLD_AI_Admin.spec
.venv\Scripts\python.exe tests\smoke_admin_exe.py
.venv\Scripts\python.exe tests\smoke_personal_exe.py
```

Client checkout and shared contract:

```powershell
Set-Location 'C:\Users\USER\Desktop\Bots\GOLD_AI_client'
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe tests\smoke_client_exe.py --source
C:\Users\USER\Desktop\Bots\Forex\AMD1\.venv\Scripts\python.exe tests\integration_contract.py 'C:\Users\USER\Desktop\Bots\Forex\AMD1'
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --distpath dist_azt --workpath build/azt_pyi build/GOLD_AI_Client.spec
.venv\Scripts\python.exe tests\smoke_client_exe.py
```

For rebuilding from source, install each checkout's requirements first with `.venv\Scripts\python.exe -m pip install -r requirements.txt`. Owner requirements include server runtime, Pillow, timezone data and PyInstaller. Normal EXE users do not need that step.

## Upgrade and run

1. Stop any legacy hosted workers from the older Admin first; the new Admin deliberately refuses to take ownership of a still-running independent old worker. Close the old Admin/Client windows cleanly.
2. Keep AZT_Admin.exe in the stated dist_azt directory so it continues loading this owner's existing configuration/data. Opening it performs the additive migration/backup and starts background infrastructure. Personal trading remains off until Start My MT5 Trading.
3. In Admin -> Clients -> Plans & Referrals, configure the actual agreed prices, currencies, durations and limits. No price/commission was invented. Configure referral rewards separately when ready. Existing ngrok task/configuration is reused; this update did not install or change the shared task.
4. Distribute the new Client EXE to customer PCs. Existing profiles migrate automatically. Add/detect each intended MT5 terminal, verify its account, connect/refresh, then Start the selected account. Each extra concurrent account requires a separate terminal installation and an authorized server allowance.
5. Client Start choices persist across app restarts; use Stop before closing if an account should not resume next time. Temporary disconnects retain the desired state. Expired/revoked access and serious safety failures disable new trading; after renewal/access restoration, explicitly enable trading again as needed.

Paste these PowerShell commands to close only visible old/new app windows from the two checkouts, wait for cooperative shutdown and launch the new builds. They never force-kill a trading worker. If an old EXE was copied elsewhere, close that window manually first. No .ps1 script or execution-policy change is required.

```powershell
function Close-AztCheckoutWindow {
    param([string]$Checkout)
    $aztWindows = Get-Process -Name GOLD_AI_Admin,AZT_Admin,GOLD_AI_Client,AZT_Client -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and $_.Path.StartsWith($Checkout + '\', [System.StringComparison]::OrdinalIgnoreCase) -and $_.MainWindowHandle -ne 0
    }
    foreach ($aztWindow in $aztWindows) {
        if (-not $aztWindow.CloseMainWindow()) { throw 'Close the old app window manually, then retry.' }
        if (-not $aztWindow.WaitForExit(45000)) { throw 'The old app is still shutting down. Do not start a second copy.' }
    }
}
$aztOwner = 'C:\Users\USER\Desktop\Bots\Forex\AMD1'
$aztClient = 'C:\Users\USER\Desktop\Bots\GOLD_AI_client'
Close-AztCheckoutWindow -Checkout $aztClient
Close-AztCheckoutWindow -Checkout $aztOwner
Start-Process -FilePath "$aztOwner\dist_azt\AZT_Admin.exe" -WorkingDirectory $aztOwner
Start-Process -FilePath "$aztClient\dist_azt\AZT_Client.exe" -WorkingDirectory $aztClient
```

If the old windows are already closed, the two direct launch commands are:

```powershell
Start-Process 'C:\Users\USER\Desktop\Bots\Forex\AMD1\dist_azt\AZT_Admin.exe'
Start-Process 'C:\Users\USER\Desktop\Bots\GOLD_AI_client\dist_azt\AZT_Client.exe'
```

## Configurable items and external integrations

Subscription prices/currency and referral reward values still need the owner's commercial decisions in Admin. Manual proof/hash review is implemented; no external credentials are needed for that workflow. Flutterwave, MTN MoMo API, blockchain verification and Binance Pay automation remain future integrations as requested. They have not been fabricated. Referral rewards are accounting records, not automatic transfers of funds.

The preserved hosted manager is one hosted terminal per client; multi-account execution in this release uses separate Client-PC terminals. Extra hosted-instance provisioning is not automatic. Journal/history completeness depends on the snapshots workers have observed; no invented history is shown. Broker/server display time can be selected through a known IANA timezone; no unverified broker DST timezone is guessed.

## Exact changed files

Owner root: `C:\Users\USER\Desktop\Bots\Forex\AMD1`

- .gitignore
- README.md
- AZT_RELEASE.md
- requirements.txt
- build/GOLD_AI_Admin.spec
- broker/mt5_client.py
- broker/symbols.py
- server/admin_gui.py
- server/admin_workspace.py
- server/admin_launcher.py
- server/app.py
- server/models.py
- server/store.py
- server/azt_store.py
- server/ui_theme.py
- server/workspace_settings.py
- server/personal_store.py
- server/personal_worker.py
- server/hosted_executor.py
- server/hosted_manager.py
- server/hosted_worker.py
- server/signal_engine.py
- server/client_telegram.py
- server/telegram_notifications.py
- server/client_notifications.py
- server/reconnect.py
- server/trade_telemetry.py
- server/pnl_cards.py
- server/requirements.txt
- IMAGES/BACKGROUND/BACKGROUND.jpg
- IMAGES/PnL_CARDS/PROFIT.jpg
- IMAGES/PnL_CARDS/LOSS.jpg
- tests/smoke_admin_exe.py
- tests/smoke_personal_exe.py
- tests/test_client_telegram.py
- tests/test_personal_telegram_hooks.py
- tests/test_azt_business.py
- tests/test_azt_hosted_supervision.py
- tests/test_azt_notifications_cards.py
- tests/test_azt_trading.py
- tests/preview_admin.py

Client root: `C:\Users\USER\Desktop\Bots\GOLD_AI_client`

- .github/workflows/build-windows-client.yml
- .gitignore
- README.md
- AZT_CLIENT.md
- app.py
- requirements.txt
- build/GOLD_AI_Client.spec
- assets/BACKGROUND.jpg
- assets/PROFIT.jpg
- assets/LOSS.jpg
- client/api.py
- client/models.py
- client/storage.py
- client/executor.py
- client/runtime.py
- client/manager.py
- client/ledger.py
- client/clock.py
- client/symbols.py
- client/telemetry.py
- client/timezones.py
- client/instance.py
- tests/test_client_safety.py
- tests/integration_contract.py
- tests/smoke_client_exe.py
- tests/preview_client.py

Unrelated reports/data, older builds, planning notes and synced project sources were not overwritten or committed. EXE build outputs stay local; source/specs/assets/tests are versioned.
