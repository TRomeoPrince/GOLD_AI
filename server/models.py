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


class MobileOverviewResponse(BaseModel):
    allowed: bool
    display_name: str
    status: str
    mt5_login: Optional[int] = None
    mt5_server: str = ""
    telegram_username: str = ""
    risk_per_trade_pct: float
    max_open_risk_pct: float
    max_daily_loss_pct: float
    daily_profit_target_enabled: bool = False
    daily_profit_target_pct: float = 0.0
    news_lock: bool
    hosted_mt5_status: str = ""
    hosted_mt5_login: Optional[int] = None
    hosted_mt5_server: str = ""
    subscription_plan: str = "STARTER"
    subscription_status: str = "TRIAL"
    subscription_expires_utc: str = ""
    latest_payment_status: str = ""
    latest_payment_checkout_url: str = ""


class HostedAccountRequest(BaseModel):
    mt5_login: int
    mt5_server: str
    trading_password: str


class TradeInstructionResponse(BaseModel):
    available: bool
    instruction_id: int = 0
    signal_key: str = ""
    payload: dict = {}


class TradeAckRequest(BaseModel):
    instruction_id: int
    status: str
    message: str = ""


class RenewalRequest(BaseModel):
    plan_code: str = "STARTER"
