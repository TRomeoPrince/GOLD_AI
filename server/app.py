from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException

from .models import (
    AuthorizeRequest,
    AuthorizeResponse,
    ClientStatusResponse,
    MobileOverviewResponse,
    TelegramRequest,
    TradeInstructionResponse,
    TradeAckRequest,
)
from .store import (
    bind_client,
    client_for_token,
    create_session,
    find_by_pairing_code,
    next_instruction,
    acknowledge_instruction,
    news_lock_enabled,
)

app = FastAPI(title="GOLD_AI Owner Server", version="0.2.0")


def _client_from_authorization(authorization: str):
    token = authorization.removeprefix("Bearer ").strip()
    client = client_for_token(token)
    if client is None:
        raise HTTPException(status_code=401, detail="Invalid session.")
    return client


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "GOLD_AI Owner Server"}


@app.post("/v1/client/authorize", response_model=AuthorizeResponse)
def authorize(req: AuthorizeRequest) -> AuthorizeResponse:
    client = find_by_pairing_code(req.pairing_code)
    if client is None:
        return AuthorizeResponse(
            allowed=False,
            status="UNKNOWN",
            message="Invalid pairing code.",
        )

    if client.mt5_login is None and req.mt5_login is not None:
        client = bind_client(
            client.id,
            req.mt5_login,
            req.mt5_server,
            req.telegram_username,
        )
    else:
        if (
            client.mt5_login is not None
            and req.mt5_login is not None
            and int(client.mt5_login) != int(req.mt5_login)
        ):
            return AuthorizeResponse(
                allowed=False,
                display_name=client.name,
                status="ACCOUNT_MISMATCH",
                message="This GOLD_AI access is bound to another MT5 account.",
            )
        if (
            client.mt5_server
            and req.mt5_server
            and client.mt5_server.lower() != req.mt5_server.strip().lower()
        ):
            return AuthorizeResponse(
                allowed=False,
                display_name=client.name,
                status="SERVER_MISMATCH",
                message="This GOLD_AI access is bound to another MT5 server.",
            )

    if req.telegram_username.strip():
        client = bind_client(
            client.id,
            client.mt5_login,
            client.mt5_server,
            req.telegram_username,
        )

    allowed = client.status == "ACTIVE"
    token = create_session(client.id) if allowed else ""
    return AuthorizeResponse(
        allowed=allowed,
        display_name=client.name,
        status=client.status,
        message="Authorized." if allowed else f"Access is {client.status}.",
        session_token=token,
    )


@app.get("/v1/client/status", response_model=ClientStatusResponse)
def client_status(authorization: str = Header(default="")) -> ClientStatusResponse:
    client = _client_from_authorization(authorization)
    return ClientStatusResponse(
        allowed=client.status == "ACTIVE",
        display_name=client.name,
        status=client.status,
    )


@app.get("/v1/mobile/overview", response_model=MobileOverviewResponse)
def mobile_overview(authorization: str = Header(default="")) -> MobileOverviewResponse:
    client = _client_from_authorization(authorization)
    return MobileOverviewResponse(
        allowed=client.status == "ACTIVE",
        display_name=client.name,
        status=client.status,
        mt5_login=client.mt5_login,
        mt5_server=client.mt5_server,
        telegram_username=client.telegram_username,
        risk_per_trade_pct=client.risk_per_trade_pct,
        max_open_risk_pct=client.max_open_risk_pct,
        max_daily_loss_pct=client.max_daily_loss_pct,
        news_lock=news_lock_enabled(),
    )


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


@app.get("/v1/instructions/next", response_model=TradeInstructionResponse)
def get_next_instruction(authorization: str = Header(default="")) -> TradeInstructionResponse:
    client = _client_from_authorization(authorization)
    if client.status != "ACTIVE":
        raise HTTPException(
            status_code=403,
            detail=f"Client access is {client.status}.",
        )

    row = next_instruction(client.id)
    if row is None:
        return TradeInstructionResponse(available=False)

    import json
    return TradeInstructionResponse(
        available=True,
        instruction_id=int(row["id"]),
        signal_key=str(row["signal_key"]),
        payload=json.loads(str(row["payload_json"])),
    )


@app.post("/v1/instructions/ack")
def ack_instruction(req: TradeAckRequest, authorization: str = Header(default="")) -> dict:
    client = _client_from_authorization(authorization)

    ok = acknowledge_instruction(client.id, req.instruction_id, req.status, req.message)
    if not ok:
        raise HTTPException(status_code=404, detail="Instruction not pending or not found.")
    return {"ok": True}
