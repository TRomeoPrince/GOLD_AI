# AZT standalone Admin recovery and 30-day distributor trial

## Recovering a clean Admin-only installation

The old Admin EXE crashed with sqlite3.OperationalError because its frozen
launcher wrote GOLD_AI_DB_PATH to a server directory that did not exist.

The corrected executable chooses a durable writable owner home:
%LOCALAPPDATA%\GOLD_AI
and stores its SQLite file in:
%LOCALAPPDATA%\GOLD_AI\server\gold_ai_server.db

The lock file and logs are in the owner home. A compatible legacy project
root containing an existing server/gold_ai_server.db wins over that fallback,
so a populated existing DB is not silently replaced. Explicit GOLD_AI_HOME,
GOLD_AI_DB_PATH and GOLD_AI_STATE_DIR environment configuration is respected.

Never delete the live database or credential_vault.key in this directory.
Keep backups of existing trading/client/payment data before upgrades.
The EXE packages the Admin Python code and images; it does NOT contain the
private .env, MT5 passwords, personal_account.json, historical journals or
external Telegram venv. Reconfigure these in the new owner home when necessary.

## Separate owner-issued distributor 30-day trial

The distributor trial is a separate database entitlement. It does not rewrite
existing paid subscription plans or affect other clients.

In AZT Admin > Clients, add a new client then select them and click
"Issue 30-Day Trial". This operation is one-time per client ID. Copy pairing.

Share ONLY AZT_Trial_Client.exe plus the client's pairing code, NEVER Admin.
The recipient pairs with your HTTPS AZT server, using their MT5 terminal
and matching MT5 login/server. The first successful pairing records the
activation UTC timestamp on the owner database, and expiry is exactly 30*24
hours after that. Subsequent pairing or reinstall cannot reset the deadline.

Your Admin controls:
- Issue 30-Day Trial: one-time, cannot reset prior use
- Revoke Trial: immediately blocks new entries, even before day 30
- Convert Trial: removes separate distributor cap, but does not automatically
  grant a paid subscription; approve/renew their plan separately

Backend checks distributor eligibility for each new instruction and again for
risk-policy authorization before the client submits a broker order. Changing
the recipient's Windows date/time or deleting the local profile does not
extend the server record. An unreachable server means no new authorized
instructions; the broker keeps existing positions, stop loss and take profit.

Expired customers may still open the app and access messages, payments and
renewal information. Normal payment approval does NOT secretly reset a
distributor trial. Convert explicitly and then approve a normal subscription.

## Source protection

The distributed Windows client contains no protected trading strategy rules.
Those remain on the owner server. PyInstaller is a convenient packaging tool,
not an anti-reverse-engineering guarantee. The important enforcement is the
server-side UTC trial and server-side signal authorizations.

## Release verification

Build the owner from fix/admin-standalone-db-utc-trial-20261030, and the
customer Client from feature/utc-30day-trial-client-20261030 in its separate
repository. Both remain isolated until approved. The GitHub Actions workflows
run regression tests and output installable Windows EXEs. No live trades are
placed during tests.
