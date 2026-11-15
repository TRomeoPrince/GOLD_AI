# AZT Friends Trial — 14 days (owner-side)

This change adds `days=14` to the **existing** one-time distributor entitlement while leaving the legacy 30-day default unchanged. Neither paid subscriptions nor active 30-day distributor trials are shortened. The owner server remains the source of truth for UTC activation and expiry.

## Before issuing

1. Use the intended owner server environment and back up its SQLite database. Changes remain on the feature branch pending verification/review.
2. Create one client per friend and generate their individual pairing codes via the existing owner workflow.
3. Switch each selected client to `CLIENT_PC` execution mode. Confirm no active paid subscription for these client IDs.
4. Issue once:

```powershell
python -m server.trial_licenses issue --client-id 123 --days 14
python -m server.trial_licenses status --client-id 123
```

The issued row stays `PENDING_FIRST_PAIR`. The first **valid MT5 account pairing** records `activated_utc` and `expires_utc` on the server. Repeated starts, logins, reinstalling the client and changing the PC clock cannot renew the server lease. After the UTC deadline, the server denies fresh instructions and risk-policy requests, while existing broker SL/TP remain at the broker.

## Auto-uninstall

The separate `AZT_Friends_Trial_Setup.exe` installer creates a per-user application in LocalAppData. After the client receives the authenticated 14-day lease in its overview it installs a disclosed Task Scheduler check every 30 minutes. After the deadline this check safely runs the Windows uninstaller for **only the trial edition**. It does not delete MT5, ledger, logs, profile or broker-side orders. It waits for the AZT client/worker to close rather than force-killing a process mid-trade.

Windows must be running and the user signed in for local uninstallation. When offline, server expiry still prevents new trades. If scheduled-task registration fails, troubleshoot Windows Task Scheduler or uninstall manually via Windows Settings. The local cleanup clock is not a trading-license authority.

## Validation

```powershell
python -m unittest tests.test_distributor_trials tests.test_distributor_trial_http -v
```

Before distributing: merge/deploy the owner code, confirm the 14-day client ID is issued, review the Windows trial CI build and installation evidence, and use a DEMO MT5 account for end-to-end verification. No live market orders are required.
