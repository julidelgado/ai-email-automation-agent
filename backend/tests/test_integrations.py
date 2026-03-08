from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse
import urllib.request

from sqlalchemy import select

from app.config import get_settings
from app.models.integration_credential import IntegrationCredential
from app.services.integrations import google_oauth_service


class _DummyResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _build_phase6_settings():
    settings = get_settings().model_copy(deep=True)
    settings.credentials_encryption_key = "phase6-api-test-key"
    settings.google_client_id = "google-client-id"
    settings.google_client_secret = "google-client-secret"
    settings.google_redirect_uri = "http://testserver/api/v1/integrations/google/callback"
    settings.google_calendar_scopes = "https://www.googleapis.com/auth/calendar.events"
    settings.google_calendar_enabled = True
    return settings


def test_google_connect_returns_authorize_url(client, monkeypatch):
    settings = _build_phase6_settings()
    monkeypatch.setattr(google_oauth_service, "get_settings", lambda: settings)

    response = client.get("/api/v1/integrations/google/connect")
    payload = response.json()

    assert response.status_code == 200
    assert payload["provider"] == "google_calendar"
    parsed = urlparse(payload["auth_url"])
    query = parse_qs(parsed.query)
    assert query["client_id"] == [settings.google_client_id]
    assert query["redirect_uri"] == [settings.google_redirect_uri]
    assert query["response_type"] == ["code"]
    assert query["access_type"] == ["offline"]
    assert query["scope"] == [settings.google_calendar_scopes]
    assert query["state"][0]


def test_google_callback_persists_tokens_and_disconnects(client, db_session, monkeypatch):
    settings = _build_phase6_settings()
    monkeypatch.setattr(google_oauth_service, "get_settings", lambda: settings)

    connect_response = client.get("/api/v1/integrations/google/connect")
    state = parse_qs(urlparse(connect_response.json()["auth_url"]).query)["state"][0]

    def fake_urlopen(request, timeout=0):
        assert request.full_url == settings.google_oauth_token_url
        return _DummyResponse(
            {
                "access_token": "oauth-access-token",
                "refresh_token": "oauth-refresh-token",
                "token_type": "Bearer",
                "expires_in": 1800,
                "scope": settings.google_calendar_scopes,
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    callback_response = client.get(
        "/api/v1/integrations/google/callback",
        params={"code": "oauth-code", "state": state},
        follow_redirects=False,
    )

    assert callback_response.status_code == 303
    assert "google_oauth=connected" in callback_response.headers["location"]

    record = db_session.execute(select(IntegrationCredential)).scalar_one()
    assert record.provider == "google_calendar"
    assert record.encrypted_access_token is not None
    assert record.encrypted_refresh_token is not None
    assert "oauth-access-token" not in record.encrypted_access_token
    assert "oauth-refresh-token" not in record.encrypted_refresh_token

    status_response = client.get("/api/v1/integrations/google/status")
    status_payload = status_response.json()
    assert status_response.status_code == 200
    assert status_payload["connected"] is True
    assert status_payload["has_refresh_token"] is True

    disconnect_response = client.post("/api/v1/integrations/google/disconnect")
    disconnect_payload = disconnect_response.json()
    assert disconnect_response.status_code == 200
    assert disconnect_payload["status"] == "ok"
    assert disconnect_payload["disconnected_count"] >= 1

    disconnected_status = client.get("/api/v1/integrations/google/status").json()
    assert disconnected_status["connected"] is False

