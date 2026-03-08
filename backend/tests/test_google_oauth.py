from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

from app.config import get_settings
from app.services.actions.google_calendar_client import GoogleCalendarClient
from app.services.actions.google_oauth_token_service import GoogleOAuthTokenService
from app.services.integrations.credential_store import IntegrationCredentialStore


class _DummyResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_google_oauth_token_service_refreshes_access_token(monkeypatch):
    settings = get_settings().model_copy(deep=True)
    settings.google_client_id = "client-id"
    settings.google_client_secret = "client-secret"
    settings.google_calendar_refresh_token = "refresh-token"
    settings.google_calendar_access_token = None

    calls = {"count": 0}

    def fake_urlopen(request, timeout=0):
        calls["count"] += 1
        assert request.full_url == settings.google_oauth_token_url
        return _DummyResponse({"access_token": "fresh-token", "expires_in": 1200})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    service = GoogleOAuthTokenService(settings)
    token_one = service.get_access_token()
    token_two = service.get_access_token()

    assert token_one == "fresh-token"
    assert token_two == "fresh-token"
    assert calls["count"] == 1


def test_google_calendar_client_retries_after_unauthorized(monkeypatch):
    settings = get_settings().model_copy(deep=True)
    settings.google_calendar_enabled = True
    settings.google_calendar_access_token = "expired-token"
    settings.google_client_id = "client-id"
    settings.google_client_secret = "client-secret"
    settings.google_calendar_refresh_token = "refresh-token"

    calls: list[str] = []

    def fake_urlopen(request, timeout=0):
        url = request.full_url
        if url.endswith("/events"):
            auth_header = request.headers.get("Authorization", "")
            calls.append(f"events:{auth_header}")
            if "expired-token" in auth_header:
                raise urllib.error.HTTPError(
                    url=url,
                    code=401,
                    msg="Unauthorized",
                    hdrs=None,
                    fp=io.BytesIO(b'{"error":"invalid_token"}'),
                )
            return _DummyResponse(
                {
                    "id": "evt_001",
                    "htmlLink": "https://calendar.google.com/event?eid=evt_001",
                    "start": {"dateTime": "2026-03-10T10:00:00+00:00"},
                    "end": {"dateTime": "2026-03-10T10:30:00+00:00"},
                }
            )
        if url == settings.google_oauth_token_url:
            calls.append("token")
            return _DummyResponse({"access_token": "fresh-token", "expires_in": 3600})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    token_service = GoogleOAuthTokenService(settings)
    client = GoogleCalendarClient(settings=settings, token_service=token_service)

    result = client.create_event(
        summary="Test Meeting",
        description="Description",
        start_iso="2026-03-10T10:00:00+00:00",
        end_iso="2026-03-10T10:30:00+00:00",
        timezone_name="UTC",
    )

    assert result["id"] == "evt_001"
    assert calls[0].startswith("events:Bearer expired-token")
    assert calls[1] == "token"
    assert calls[2].startswith("events:Bearer fresh-token")


def test_google_oauth_token_service_refreshes_using_db_credentials(db_session, monkeypatch):
    settings = get_settings().model_copy(deep=True)
    settings.credentials_encryption_key = "phase6-db-token-key"
    settings.google_client_id = "client-id"
    settings.google_client_secret = "client-secret"
    settings.google_calendar_access_token = None
    settings.google_calendar_refresh_token = None

    store = IntegrationCredentialStore(db_session, settings=settings)
    store.upsert_google_credentials(
        access_token="stale-token",
        refresh_token="db-refresh-token",
        token_type="Bearer",
        scopes=settings.google_calendar_scopes,
        expires_at=None,
        metadata={"seed": True},
    )

    def fake_urlopen(request, timeout=0):
        assert request.full_url == settings.google_oauth_token_url
        return _DummyResponse({"access_token": "db-fresh-token", "expires_in": 3600, "token_type": "Bearer"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    service = GoogleOAuthTokenService(settings=settings, db=db_session)
    token = service.get_access_token(force_refresh=True)

    assert token == "db-fresh-token"
    refreshed = store.get_google_credentials()
    assert refreshed is not None
    assert refreshed.access_token == "db-fresh-token"
    assert refreshed.refresh_token == "db-refresh-token"
