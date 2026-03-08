from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models.integration_credential import IntegrationCredential
from app.services.integrations.crypto import CredentialCryptoService

GOOGLE_CALENDAR_PROVIDER = "google_calendar"
GOOGLE_DEFAULT_ACCOUNT_ID = "default"


@dataclass
class GoogleCredentialRecord:
    credential_id: int
    account_id: str | None
    access_token: str | None
    refresh_token: str | None
    token_type: str | None
    scopes: list[str]
    expires_at: datetime | None
    metadata: dict[str, Any] | list[Any] | None


class IntegrationCredentialStore:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        crypto_service: CredentialCryptoService | None = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.crypto = crypto_service or CredentialCryptoService(self.settings)

    def get_google_credentials(self, account_id: str = GOOGLE_DEFAULT_ACCOUNT_ID) -> GoogleCredentialRecord | None:
        record = self._find_active(provider=GOOGLE_CALENDAR_PROVIDER, account_id=account_id)
        if record is None:
            return None

        access_token = self.crypto.decrypt(record.encrypted_access_token) if record.encrypted_access_token else None
        refresh_token = self.crypto.decrypt(record.encrypted_refresh_token) if record.encrypted_refresh_token else None

        return GoogleCredentialRecord(
            credential_id=record.id,
            account_id=record.account_id,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=record.token_type,
            scopes=_parse_scopes(record.scopes),
            expires_at=record.expires_at,
            metadata=record.metadata_json,
        )

    def upsert_google_credentials(
        self,
        *,
        access_token: str | None,
        refresh_token: str | None,
        token_type: str | None,
        scopes: str | list[str] | None,
        expires_at: datetime | None,
        metadata: dict[str, Any] | list[Any] | None = None,
        account_id: str = GOOGLE_DEFAULT_ACCOUNT_ID,
    ) -> IntegrationCredential:
        self.crypto.require_configured()
        record = self._find_active(provider=GOOGLE_CALENDAR_PROVIDER, account_id=account_id)
        if record is None:
            record = IntegrationCredential(
                provider=GOOGLE_CALENDAR_PROVIDER,
                account_id=account_id,
                is_active=True,
            )

        if access_token is not None:
            record.encrypted_access_token = self.crypto.encrypt(access_token)
        if refresh_token is not None:
            record.encrypted_refresh_token = self.crypto.encrypt(refresh_token)
        record.token_type = token_type
        record.scopes = _normalize_scopes(scopes)
        record.expires_at = expires_at
        record.metadata_json = metadata
        record.is_active = True

        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def deactivate_provider(self, provider: str) -> int:
        statement = (
            select(IntegrationCredential)
            .where(IntegrationCredential.provider == provider, IntegrationCredential.is_active.is_(True))
            .order_by(IntegrationCredential.updated_at.desc(), IntegrationCredential.id.desc())
        )
        records = list(self.db.scalars(statement))
        for record in records:
            record.is_active = False
            self.db.add(record)
        if records:
            self.db.commit()
        return len(records)

    def _find_active(self, *, provider: str, account_id: str | None) -> IntegrationCredential | None:
        statement = (
            select(IntegrationCredential)
            .where(
                IntegrationCredential.provider == provider,
                IntegrationCredential.is_active.is_(True),
            )
            .order_by(IntegrationCredential.updated_at.desc(), IntegrationCredential.id.desc())
        )
        if account_id is not None:
            statement = statement.where(IntegrationCredential.account_id == account_id)
        return self.db.scalars(statement).first()


def _normalize_scopes(scopes: str | list[str] | None) -> str | None:
    if scopes is None:
        return None
    if isinstance(scopes, str):
        cleaned = " ".join(part for part in scopes.strip().split() if part)
        return cleaned or None
    ordered = [part.strip() for part in scopes if isinstance(part, str) and part.strip()]
    return " ".join(ordered) or None


def _parse_scopes(scopes_text: str | None) -> list[str]:
    if not scopes_text:
        return []
    return [part for part in scopes_text.split() if part]
