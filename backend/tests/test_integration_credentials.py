from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.models.integration_credential import IntegrationCredential
from app.services.integrations.credential_store import IntegrationCredentialStore


def test_google_credential_store_encrypts_and_roundtrips_tokens(db_session):
    settings = get_settings().model_copy(deep=True)
    settings.credentials_encryption_key = "phase6-test-encryption-key"

    store = IntegrationCredentialStore(db_session, settings=settings)
    expires_at = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)

    store.upsert_google_credentials(
        access_token="access-token-plain",
        refresh_token="refresh-token-plain",
        token_type="Bearer",
        scopes=["scope.one", "scope.two"],
        expires_at=expires_at,
        metadata={"source": "unit-test"},
    )

    row = db_session.execute(select(IntegrationCredential)).scalar_one()
    assert row.encrypted_access_token is not None
    assert row.encrypted_refresh_token is not None
    assert "access-token-plain" not in row.encrypted_access_token
    assert "refresh-token-plain" not in row.encrypted_refresh_token

    loaded = store.get_google_credentials()
    assert loaded is not None
    assert loaded.access_token == "access-token-plain"
    assert loaded.refresh_token == "refresh-token-plain"
    assert loaded.scopes == ["scope.one", "scope.two"]
    assert loaded.expires_at is not None

