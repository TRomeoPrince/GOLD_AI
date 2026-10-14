from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class AuthorizeRequest(BaseModel):
    pairing_code: str
    mt5_login: Optional[int] = None
    mt5_server: str = ""
    telegram_username: str = ""


class AuthorizeResponse(BaseModel):
    allowed: bool
    display_name: str = ""
    status: str = "UNKNOWN"
    message: str = ""
    session_token: str = ""


class TelegramRequest(BaseModel):
    pairing_code: str
    telegram_username: str


class ClientStatusResponse(BaseModel):
    allowed: bool
    display_name: str
    status: str


class TradeInstructionResponse(BaseModel):
    available: bool
    instruction_id: int = 0
    signal_key: str = ""
    payload: dict = {}


class TradeAckRequest(BaseModel):
    instruction_id: int
    status: str
    message: str = ""
