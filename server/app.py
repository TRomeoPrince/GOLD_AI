from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
import html
import json
import logging
import re
from datetime import datetime, timezone
from . import azt_store

from .models import (
    AuthorizeRequest,
    AuthorizeResponse,
    ClientStatusResponse,
    HostedAccountRequest,
    MobileOverviewResponse,
    RenewalRequest,
    TelegramRequest,
    TradeInstructionResponse,
    TradeAckRequest,
    AZTPaymentRequest, AZTCodeRequest, AZTPreferencesRequest, AZTTelemetryRequest,
)
from .store import (
    bind_client,
    client_for_token,
    create_session,
    find_by_pairing_code,
    next_instruction,
    acknowledge_instruction,
    create_payment_request,
    effective_risk_policy,
    hosted_account_for_client,
    latest_payment_request,
    news_lock_enabled,
    subscription_access,
    subscription_for_client,
    upsert_hosted_account,
)

app = FastAPI(title="AGORA ZION TRADER Owner Server", version="1.0.0")


def _client_from_authorization(authorization: str):
    token = authorization.removeprefix("Bearer ").strip()
    client = client_for_token(token)
    if client is None:
        raise HTTPException(status_code=401, detail="Invalid session.")
    return client


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "AGORA ZION TRADER Owner Server", "legacy_service": "GOLD_AI Owner Server"}


@app.post("/v1/client/authorize", response_model=AuthorizeResponse)
def authorize(req: AuthorizeRequest) -> AuthorizeResponse:
    client = find_by_pairing_code(req.pairing_code)
    if client is None:
        return AuthorizeResponse(
            allowed=False,
            status="UNKNOWN",
            message="Invalid pairing code.",
        )

    account = None
    try:
        if req.mt5_login is not None:
            account = azt_store.authorize_account(client.id, req.mt5_login, req.mt5_server)
        if req.telegram_username.strip():
            azt_store.edit_client(client.id, telegram_username=req.telegram_username)
        if req.referral_code:
            azt_store.link_referral(client.id, req.referral_code)
    except ValueError as exc:
        return AuthorizeResponse(allowed=False, display_name=client.name, status="ACCOUNT_NOT_AUTHORIZED", message=str(exc))
    summary = azt_store.subscription_summary(client.id)
    # Inactive clients retain read/payment access. Every executable route checks
    # the current subscription and account, independently of this token grant.
    token = create_session(client.id, account["id"] if account else None)
    allowed = summary["allowed"] and account is not None
    return AuthorizeResponse(
        allowed=allowed,
        display_name=client.name,
        status=summary["effective_status"],
        message="Authorized." if allowed else f"Read-only access: {summary['reason'] if account else 'MT5 account not connected'}.",
        session_token=token,
        account_id=account["id"] if account else None,
        max_mt5_accounts=summary["max_mt5_accounts"], display_timezone=summary["display_timezone"],
        subscription_status=summary["effective_status"], expires_utc=summary["subscription"]["expires_utc"],
    )


@app.get("/v1/client/status", response_model=ClientStatusResponse)
def client_status(authorization: str = Header(default="")) -> ClientStatusResponse:
    client = _client_from_authorization(authorization)
    access = azt_store.subscription_summary(client.id)
    return ClientStatusResponse(
        allowed=access["allowed"],
        display_name=client.name,
        status=access["effective_status"],
    )


@app.get("/v1/client/risk-policy")
def client_risk_policy(authorization: str = Header(default="")) -> dict:
    client = _client_from_authorization(authorization)
    _trade_context(authorization)
    if news_lock_enabled():
        raise HTTPException(status_code=409, detail="NEWS_LOCK: New entries are temporarily blocked.")
    return {**effective_risk_policy(client), "max_single_risk_pct": 2.0, "news_lock": False}


@app.get("/v1/mobile/overview", response_model=MobileOverviewResponse)
def mobile_overview(authorization: str = Header(default="")) -> MobileOverviewResponse:
    client = _client_from_authorization(authorization)
    hosted = hosted_account_for_client(client.id)
    risk = effective_risk_policy(client)
    subscription = subscription_for_client(client.id)
    subscription_state = subscription_access(client.id)
    payment = latest_payment_request(client.id)
    return MobileOverviewResponse(
        allowed=client.status == "ACTIVE",
        display_name=client.name,
        status=client.status,
        mt5_login=client.mt5_login,
        mt5_server=client.mt5_server,
        telegram_username=client.telegram_username,
        risk_per_trade_pct=risk["risk_per_trade_pct"],
        max_open_risk_pct=risk["max_open_risk_pct"],
        max_daily_loss_pct=risk["max_daily_loss_pct"],
        daily_profit_target_enabled=risk["daily_profit_target_enabled"],
        daily_profit_target_pct=risk["daily_profit_target_pct"],
        news_lock=news_lock_enabled(),
        hosted_mt5_status=(hosted or {}).get("status", ""),
        hosted_mt5_login=(hosted or {}).get("mt5_login"),
        hosted_mt5_server=(hosted or {}).get("mt5_server", ""),
        subscription_plan=subscription.get("plan_code", "STARTER"),
        subscription_status=subscription.get("status", "TRIAL"),
        subscription_expires_utc=subscription.get("expires_utc", ""),
        latest_payment_status=(payment or {}).get("status", ""),
        latest_payment_checkout_url=(payment or {}).get("checkout_url", ""),
        subscription_trading_allowed=bool(subscription_state["allowed"]),
        subscription_access_reason=str(subscription_state["reason"]),
    )


@app.get("/v1/mobile/subscription")
def mobile_subscription(authorization: str = Header(default="")) -> dict:
    client = _client_from_authorization(authorization)
    subscription = subscription_for_client(client.id)
    payment = latest_payment_request(client.id)
    return {
        "subscription": subscription,
        "latest_payment": payment,
    }


@app.post("/v1/mobile/subscription/renew")
def mobile_subscription_renew(
    req: RenewalRequest,
    authorization: str = Header(default=""),
) -> dict:
    client = _client_from_authorization(authorization)
    current = subscription_for_client(client.id)
    plan_code = (req.plan_code or current.get("plan_code") or "STARTER").upper().strip()

    request = create_payment_request(
        client.id,
        plan_code=plan_code,
        amount=0.0,
        currency="USD",
        provider="UNSET",
    )
    return {
        "ok": True,
        "payment_request_id": request["id"],
        "status": request["status"],
        "plan_code": request["plan_code"],
        "checkout_url": request["checkout_url"],
        "message": (
            "Renewal request created. Checkout will become available after "
            "the payment provider is configured."
        ),
    }


@app.post("/v1/mobile/hosted-account")
def submit_hosted_account(
    req: HostedAccountRequest,
    authorization: str = Header(default=""),
) -> dict:
    client = _client_from_authorization(authorization)
    if client.status != "ACTIVE":
        raise HTTPException(status_code=403, detail=f"Client access is {client.status}.")

    try:
        record = upsert_hosted_account(
            client.id,
            req.mt5_login,
            req.mt5_server,
            req.trading_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "ok": True,
        "status": record["status"],
        "mt5_login": record["mt5_login"],
        "mt5_server": record["mt5_server"],
        "message": "Hosted MT5 request received securely.",
    }


@app.post("/v1/client/telegram")
def telegram(req: TelegramRequest) -> dict:
    client = find_by_pairing_code(req.pairing_code)
    if client is None:
        raise HTTPException(status_code=404, detail="Unknown pairing code.")

    client = bind_client(
        client.id,
        client.mt5_login,
        client.mt5_server,
        req.telegram_username,
    )
    return {
        "ok": True,
        "display_name": client.name,
        "telegram_username": client.telegram_username,
        "telegram_bot": "https://t.me/Princetradingbot",
        "next_step": "Send /start to @Princetradingbot.",
    }


def _trade_context(authorization):
    token = authorization.removeprefix("Bearer ").strip()
    access = azt_store.trade_access(token)
    if not access["allowed"]:
        raise HTTPException(status_code=403, detail=access["reason"])
    return access["context"]


@app.get("/v1/instructions/next", response_model=TradeInstructionResponse)
def get_next_instruction(authorization: str = Header(default=""), since: str = "") -> TradeInstructionResponse:
    client = _client_from_authorization(authorization)
    if client.status != "ACTIVE":
        raise HTTPException(
            status_code=403,
            detail=f"Client access is {client.status}.",
        )
    if client.execution_mode != "CLIENT_PC":
        raise HTTPException(
            status_code=403,
            detail="This client is configured for HOSTED execution.",
        )

    access = subscription_access(client.id)
    if not access["allowed"]:
        raise HTTPException(
            status_code=403,
            detail=(
                "Subscription inactive or expired. Renew from the AZT Client Payments page. "
                f"Reason: {access['reason']}."
            ),
        )

    context = _trade_context(authorization)
    if news_lock_enabled():
        return TradeInstructionResponse(available=False)
    try:
        # An unmodified old client cannot drain queued pre-session trades. New
        # clients send a later boundary on every Start/reconnect as well.
        boundary = max(azt_store.utc_iso(since), context["created_utc"]) if since else context["created_utc"]
        row = azt_store.next_account_instruction(client.id, context["account_id"], boundary)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if row is None:
        return TradeInstructionResponse(available=False)

    import json
    return TradeInstructionResponse(
        available=True,
        instruction_id=int(row["id"]),
        signal_key=str(row["signal_key"]),
        payload=json.loads(str(row["payload_json"])),
        created_utc=str(row["created_utc"]),
    )


@app.post("/v1/instructions/ack")
def ack_instruction(req: TradeAckRequest, authorization: str = Header(default="")) -> dict:
    client = _client_from_authorization(authorization)
    context = azt_store.session_context(authorization.removeprefix("Bearer ").strip())
    if not context or not context["account_id"]:
        raise HTTPException(status_code=403, detail="MT5 account is not authorized.")
    try:
        ok = azt_store.acknowledge_account_instruction(client.id, context["account_id"], req.instruction_id, req.status, req.message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if not ok:
        raise HTTPException(status_code=404, detail="Instruction not pending or not found.")
    if req.status.upper() == "EXECUTED":
        try:
            from . import store, trade_telemetry
            ticket = re.search(r"(?:^|[;|\s])ticket=(\d+)", req.message)
            risk = re.search(r"(?:^|[;|\s])risk=(\d+(?:\.\d+)?)", req.message)
            if ticket and int(ticket[1]) > 0:
                with store.connect() as con:
                    instruction = con.execute("SELECT payload_json FROM instructions WHERE id=? AND client_id=?", (req.instruction_id, client.id)).fetchone()
                if instruction:
                    trade_telemetry.record_execution(client.id, f"{context['server']}|{context['login']}", ticket[1], json.loads(instruction[0]), risk_pct=float(risk[1]) if risk else None, database=store.DB_PATH)
        except Exception as exc:
            logging.warning("Trade acknowledgment saved but telemetry metadata unavailable (%s).", type(exc).__name__)
    return {"ok": True}


def _business(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/v1/azt/overview")
def azt_overview(authorization: str = Header(default="")):
    client = _client_from_authorization(authorization)
    from . import trade_telemetry
    result = azt_store.overview(client.id)
    from .store import DB_PATH
    result["telemetry"] = trade_telemetry.overview(client.id, result["display_timezone"], database=DB_PATH)
    return result


@app.get("/v1/azt/plans")
def azt_plans(authorization: str = Header(default="")):
    _client_from_authorization(authorization)
    return {"plans": [p for p in azt_store.plans() if p["enabled"]]}


@app.get("/v1/azt/accounts")
def azt_accounts(authorization: str = Header(default="")):
    client = _client_from_authorization(authorization)
    return {"accounts": azt_store.list_accounts(client.id), "max_mt5_accounts": azt_store.subscription_summary(client.id)["max_mt5_accounts"]}


@app.get("/v1/azt/messages")
def azt_messages(authorization: str = Header(default=""), unread_only: bool = False):
    client = _client_from_authorization(authorization)
    return {"messages": azt_store.messages(client.id, unread_only)}


@app.post("/v1/azt/messages/{message_id}/read")
def azt_message_read(message_id: int, authorization: str = Header(default="")):
    client = _client_from_authorization(authorization)
    if not azt_store.mark_message_read(client.id, message_id):
        raise HTTPException(status_code=404, detail="Message not found.")
    return {"ok": True}


@app.get("/v1/azt/preferences")
def azt_preferences(authorization: str = Header(default="")):
    client = _client_from_authorization(authorization)
    return azt_store.preferences(client.id)


@app.post("/v1/azt/preferences")
def azt_set_preferences(req: AZTPreferencesRequest, authorization: str = Header(default="")):
    client = _client_from_authorization(authorization)
    return _business(azt_store.set_preferences, client.id, req.display_timezone)


@app.get("/v1/azt/payment-methods")
def azt_payment_methods(authorization: str = Header(default="")):
    _client_from_authorization(authorization)
    return {"methods": azt_store.payment_methods(), "warning": azt_store.PAYMENT_WARNING}


@app.get("/v1/azt/payments")
def azt_payments(authorization: str = Header(default="")):
    client = _client_from_authorization(authorization)
    rows = azt_store.list_payments(client.id)
    # The client already owns the uploaded proof; omit large blobs from routine
    # refreshes. Owner review retains the original bounded proof in the DB.
    return {"payments": [{k: v for k, v in row.items() if k != "proof"} for row in rows]}


@app.post("/v1/azt/payments")
def azt_submit_payment(req: AZTPaymentRequest, authorization: str = Header(default="")):
    client = _client_from_authorization(authorization)
    row = _business(azt_store.submit_payment, client.id, req.plan_code, req.method, proof=req.proof, transaction_hash=req.transaction_hash)
    return {k: v for k, v in row.items() if k != "proof"}


@app.get("/v1/azt/referrals")
def azt_referrals(request: Request, authorization: str = Header(default="")):
    client = _client_from_authorization(authorization)
    result = azt_store.referral_summary(client.id)
    result["link"] = str(request.base_url).rstrip("/") + result["link"]
    return result


@app.get("/ref/{code}", response_class=HTMLResponse)
def referral_invitation(code: str):
    # This public invitation exposes only a referral code. Registration,
    # payments, profile data and all Admin actions remain separately protected.
    with azt_store._db() as con:
        row = con.execute("SELECT r.code FROM referral_codes r JOIN clients c ON c.id=r.client_id WHERE r.code=? AND c.archived_utc=''", (code.upper().strip(),)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Referral code not found.")
    safe = html.escape(row["code"])
    return HTMLResponse(f"<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>AGORA ZION TRADER referral</title></head><body style='background:#071911;color:#eaf0e6;font:18px system-ui;padding:8vw;max-width:760px'><h1 style='color:#d9b968'>AGORA ZION TRADER</h1><h2>Your referral invitation</h2><p>Referral code: <strong>{safe}</strong></p><p>Open the AZT Client app, connect using your own pairing code, then enter this referral code on the Referrals page before your first paid subscription is approved.</p><p>Contact your service provider for the Client app and your individual pairing code. This invitation does not grant trading access or activate a paid subscription.</p></body></html>")


@app.post("/v1/azt/referrals/link")
def azt_referral_link(req: AZTCodeRequest, authorization: str = Header(default="")):
    client = _client_from_authorization(authorization)
    return _business(azt_store.link_referral, client.id, req.code)


@app.post("/v1/azt/promos/redeem")
def azt_promo_redeem(req: AZTCodeRequest, authorization: str = Header(default="")):
    client = _client_from_authorization(authorization)
    return _business(azt_store.redeem_promo, client.id, req.code)


@app.get("/v1/azt/trades")
def azt_trades(authorization: str = Header(default="")):
    client = _client_from_authorization(authorization)
    from . import trade_telemetry
    tz = azt_store.preferences(client.id)["display_timezone"]
    from .store import DB_PATH
    result = trade_telemetry.overview(client.id, tz, database=DB_PATH)
    return {"positions": result["positions"], "trades": trade_telemetry.list_trades(client.id, state="CLOSED", database=DB_PATH), "display_timezone": tz, "accounts": result["accounts"]}


@app.get("/v1/azt/journal")
def azt_journal(authorization: str = Header(default=""), date: str | None = None):
    client = _client_from_authorization(authorization)
    from . import trade_telemetry
    from .store import DB_PATH
    return _business(trade_telemetry.daily_journal, client.id, date, azt_store.preferences(client.id)["display_timezone"], database=DB_PATH)


@app.post("/v1/client/telemetry")
@app.post("/v1/azt/telemetry")
def azt_telemetry(req: AZTTelemetryRequest, authorization: str = Header(default="")):
    client = _client_from_authorization(authorization)
    token = authorization.removeprefix("Bearer ").strip()
    context = azt_store.session_context(token)
    if not context or not context["account_id"] or context["account_status"] != "ACTIVE":
        raise HTTPException(status_code=403, detail="MT5 account is not authorized.")
    account_key = f"{context['server']}|{context['login']}"
    account = req.snapshot.get("account", {})
    if not isinstance(account, dict):
        raise HTTPException(status_code=400, detail="Invalid telemetry account summary.")
    try:
        matches = int(account.get("login", 0) or 0) == context["login"] and str(account.get("server", "")) == context["server"]
    except (TypeError, ValueError):
        matches = False
    if not matches:
        raise HTTPException(status_code=400, detail="Telemetry account does not match the authenticated MT5 account.")
    from . import trade_telemetry
    from .store import DB_PATH
    result = _business(trade_telemetry.ingest_snapshot, client.id, account_key, req.snapshot, database=DB_PATH)
    for state, trades in (("open", result.get("new_open", [])), ("closed", result.get("new_closed", [])), ("sl_updated", result.get('new_stop_updates', []))):
        for trade in trades:
            try:
                from .client_notifications import enqueue_trade_event
                enqueue_trade_event(client.id, trade, event_key=trade.get('event_key') or f"{state}:{account_key}:{trade.get('ticket','')}", database=DB_PATH)
            except Exception:
                # Trade telemetry is committed regardless of notification I/O.
                pass
    return result
