# GOLD_AI single-window owner launcher

The button-enabled build for this update is dist_buttons/GOLD_AI_Admin.exe. The running original dist/GOLD_AI_Admin.exe was locked, so it was left untouched. Close the old Admin and owner stack before opening the new EXE. Both builds share the same project data and launcher lock. To make the existing shortcuts use the new build, close all Admin instances, then copy dist_buttons/GOLD_AI_Admin.exe over dist/GOLD_AI_Admin.exe.

Double-click dist\GOLD_AI_Admin.exe in this checkout. API and configured Telegram start immediately; the signal engine waits for Start Automated Trading. Stop Automated Trading stops signal generation while keeping the API and Telegram running. Already queued instructions and existing positions are unchanged. Both START_GOLD_AI.bat and server\run_owner_stack.bat now open that same app.

The EXE bundles the API, signal engine and client Telegram code. It is an owner application, not a distributable client: retain this checkout's server database, credential vault key and project .env. Hosted MT5 provisioning still uses the existing owner .venv and explicitly managed hosted workers. Those workers remain separately managed; closing Admin stops its API, signal engine and Telegram children, not pre-existing hosted MT5 terminals or ngrok.

Configuration is loaded from the checkout .env before importing services; existing environment variables take precedence. GOLD_AI_HOME can select another state/project folder. GOLD_AI_DB_PATH, GOLD_AI_STATE_DIR and GOLD_AI_PROJECT_ROOT are passed consistently to children. Default API binding is 127.0.0.1:8765 (GOLD_AI_API_PORT overrides the port). Never put secrets into the PyInstaller bundle.

Add GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN=your_token to .env, then reopen Admin. Missing token is shown as Not configured and does not stop the API or engine. Telegram's existing commands and client linking are unchanged.

The status strip reports child PID/exit and API health plus shared ngrok tunnels to the API port. Running means process alive, not proof of broker login or Telegram connectivity: inspect logs\signal_engine.log and logs\telegram.log for operational failures. logs\api.log holds API output. Services exiting unexpectedly remain stopped and visible; Start Automated Trading restarts the required services. Logs append across runs. A failed startup does not change client risk, subscription or execution policy.

Exit sends private stdin EOF to all owned children; the API drains, Telegram finishes its current request and the engine stops between work iterations and releases MT5. A 25-second fallback kills an unresponsive owned child and records it in logs\launcher.log. No unrelated process is killed. Duplicate Admin launches are blocked by a Windows file lock. If API port is occupied, no services start: close the old owner stack deliberately and click Retry. Old CMD windows are not automatically closed.

## Build and verify (PowerShell)

```powershell
Set-Location 'C:\Users\USER\Desktop\Bots\Forex\AMD1'
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r server\requirements.txt -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist --workpath build/admin_pyi build/GOLD_AI_Admin.spec
.\.venv\Scripts\python.exe tests\smoke_admin_exe.py
Start-Process '.\dist\GOLD_AI_Admin.exe'
```

Alternatively: cmd /c build\build_admin.bat. Close Admin before rebuilding. Do not run the old API watchdog at the same time.

## Shared ngrok startup

Use one ngrok agent with named tunnels in an explicit config outside all repositories. Other projects add their own tunnel/domain and port to that config; they do not reuse GOLD_AI's public hostname for an unrelated service. Account limits apply. The existing client URL is https://grandpa-skier-sphere.ngrok-free.dev, so retain that assigned hostname or rebuild clients for a new hostname.

The installer creates an independent SYSTEM scheduled task at Windows boot, with retry on failure, battery operation, no time limit and no visible console. Admin only reads ngrok's local inspection API. Closing Admin leaves ngrok running; the public endpoint cannot serve GOLD_AI until its API is running again.

1. Install ngrok from https://ngrok.com/download/windows if needed.
2. Copy scripts\shared-ngrok.example.yml to C:\ProgramData\Shared-ngrok\ngrok.yml and privately replace the token. Keep it out of Git. Restrict file access to your Windows account, Administrators and SYSTEM. Ensure SYSTEM can read the chosen ngrok executable and config.
3. Close an old manually launched ngrok agent before starting the shared task. Do not install a second task/service for the same agent.
4. In elevated PowerShell:

```powershell
Set-Location 'C:\Users\USER\Desktop\Bots\Forex\AMD1'
$ngrokExe = (Get-Command ngrok.exe).Source
.\scripts\install_shared_ngrok.ps1 -NgrokExe $ngrokExe -ConfigPath 'C:\ProgramData\Shared-ngrok\ngrok.yml' -StartNow
Get-ScheduledTaskInfo -TaskName 'Shared-ngrok'
Invoke-RestMethod 'http://127.0.0.1:4040/api/tunnels'
```

ngrok logs go to C:\ProgramData\Shared-ngrok\ngrok.log. The helper validates config and refuses to overwrite an existing task. To edit tunnels, update config and use Stop-ScheduledTask then Start-ScheduledTask. To remove:

```powershell
Stop-ScheduledTask -TaskName 'Shared-ngrok'
Unregister-ScheduledTask -TaskName 'Shared-ngrok' -Confirm:$false
```

The Start ngrok button first reuses an agent detected on localhost:4040. Otherwise it starts the installed Shared-ngrok task. If that task is absent, it launches a hidden independent ngrok process using the current account's existing ngrok authentication. With default settings, that process forwards the assigned GOLD_AI hostname to the API port. Set GOLD_AI_NGROK_EXE to an absolute ngrok path if it is not on PATH. Set GOLD_AI_NGROK_CONFIG to an external shared config to launch all named tunnels instead, or GOLD_AI_NGROK_URL to select the assigned URL for the single-tunnel fallback. No token is displayed or embedded. A running agent without a GOLD_AI tunnel is reported instead of launching a competing agent. A task permission failure is shown in Admin; the button does not elevate or install tasks. Independent fallback output is in logs/ngrok.log. Shared task logs remain in ProgramData. Closing Admin leaves either tunnel running.

No task is installed by building or opening Admin. Installation is a separate explicit setup step. ngrok docs: https://ngrok.com/docs/agent/config/v2/ and https://ngrok.com/download/windows.

## Current GOLD_AI_client source inspection

Inspected client source commit: de0ad7df5e105444e9f4f21024e974b8592cfd18.

Repository: C:\Users\USER\Desktop\Bots\GOLD_AI_client. No client files changed. This describes checked-out source, not independently verified provenance of older EXEs copied elsewhere.

- Windowed, one-file PyInstaller executable of app.py with MT5/numpy included. It contains execution logic, not the owner's strategy engine or API. It needs a local installed/logged-in MT5 terminal and Algo Trading enabled.
- Opening loads ~/.gold_ai_client/profile.json, forces the hard-coded public ngrok URL, and attempts MT5 detection after 250ms. It fills account login/server and balance. It does not auto-authorize or begin trading simply by opening.
- Save persists pairing code, profile/client ID, account/server and Telegram preference. Connect / Authorize saves and POSTs /v1/client/authorize. Successful authorization keeps a session token in memory and starts one daemon polling thread. There is no separate heartbeat.
- GET /v1/instructions/next uses Bearer token. Empty queue waits 2 seconds; errors retry after 3 seconds. HTTP 403 clears the token and stops new instructions until reauthorized. Other errors (including HTTP 401) retry. Subscription/access enforcement depends on the owner API; this UI has no dedicated subscription dashboard.
- TEST instructions are acknowledged TEST_OK. Other instructions resolve broker symbols, check MT5/Algo Trading, validate live price between SL and TP, calculate lots, try supported filling modes and send a market order with broker SL/TP. It acknowledges EXECUTED or REJECTED and displays the result. Exceptions before acknowledgment retry the loop; there is no client-side durable execution ledger shown here.
- Actual local sizing constants: target 0.9% equity, maximum single-trade/minimum-lot adaptation 15%, maximum total open risk 40% counting only magic 560090. It does not consume an instruction's risk_policy or enforce daily-loss/profit limits locally. This differs from the owner's current hard 2% policy. This launcher change deliberately preserves existing behavior; upgrading client policy enforcement is separate work.
- Telegram checkbox is saved locally, but authorize sends username, not telegram_enabled. Notification delivery/linking is server-side; checkbox alone does not guarantee disabling delivery.
- Closing sets the stop flag, calls mt5.shutdown and destroys the UI. It does not join the daemon worker, close existing positions or remove broker-side SL/TP. No trailing/ongoing position-management loop exists in this client source.
