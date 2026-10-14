from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException

from .models import (
    AuthorizeRequest,
    AuthorizeResponse,
    ClientStatusResponse,
    TelegramRequest,
)
from .store import (
    bind_client,
    client_for_token,
    create_session,
    find_by_pairing_code,
)

app = FastAPI(title="GOLD_AI Owner Server", version="0.1.0")


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

    # First successful pairing can bind the customer's MT5 account.
    if client.mt5_login is None and req.mt5_login is not None:
        client = bind_client(
            client.id,
            req.mt5_login,
            req.mt5_server,
            req.telegram_username,
        )
    else:
        # Once bound, a different MT5 login/server is not silently accepted.
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
    token = authorization.removeprefix("Bearer ").strip()
    client = client_for_token(token)
    if client is None:
        raise HTTPException(status_code=401, detail="Invalid session.")
    return ClientStatusResponse(
        allowed=client.status == "ACTIVE",
        display_name=client.name,
        status=client.status,
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
