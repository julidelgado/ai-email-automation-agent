from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class GoogleIntegrationStatusResponse(BaseModel):
    provider: str
    connected: bool
    oauth_ready: bool
    encryption_ready: bool
    calendar_enabled: bool
    account_id: str | None
    expires_at: datetime | None
    scopes: list[str]
    has_refresh_token: bool


class GoogleIntegrationConnectResponse(BaseModel):
    provider: str
    auth_url: str


class GoogleIntegrationDisconnectResponse(BaseModel):
    status: str
    provider: str
    disconnected_count: int

