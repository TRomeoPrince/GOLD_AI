from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class AuthorizeRequest(BaseModel):
    pairing_code: str
    mt5_login: Optional[int] = None
    mt5_server: str = ""
    telegram_username: str = ""
    display_timezone: str = "UTC"
    referral_code: str = ""


class AuthorizeResponse(BaseModel):
    allowed: bool
    display_name: str = ""
    status: str = "UNKNOWN"
    message: str = ""
    session_token: str = ""
    account_id: Optional[int] = None
    max_mt5_accounts: int = 1
    display_timezone: str = "UTC"
    subscription_status: str = ""
    expires_utc: str = ""


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
    subscription_trading_allowed: bool = True
    subscription_access_reason: str = "OK"


class HostedAccountRequest(BaseModel):
    mt5_login: int
    mt5_server: str
    trading_password: str


class TradeInstructionResponse(BaseModel):
    available: bool
    blocked_reason: str = ""
    instruction_id: int = 0
    signal_key: str = ""
    payload: dict = {}
    created_utc: str = ""


class TradeAckRequest(BaseModel):
    instruction_id: int
    status: str
    message: str = ""


class RenewalRequest(BaseModel):
    plan_code: str = "STARTER"


class AZTPaymentRequest(BaseModel):
    plan_code: str = Field(max_length=40)
    method: str = Field(max_length=40)
    proof: str = Field(default="", max_length=7200000)
    transaction_hash: str = Field(default="", max_length=200)


class AZTCodeRequest(BaseModel):
    code: str = Field(max_length=100)


class AZTPreferencesRequest(BaseModel):
    display_timezone: str = Field(default="UTC", max_length=100)


class AZTTelemetryRequest(BaseModel):
    snapshot: dict = Field(default_factory=dict)
