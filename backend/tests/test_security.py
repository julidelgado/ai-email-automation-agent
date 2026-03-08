from __future__ import annotations

from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


@contextmanager
def _secured_client(monkeypatch):
    monkeypatch.setenv("APP_SECURITY_BASIC_AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_SECURITY_BASIC_AUTH_USERNAME", "admin")
    monkeypatch.setenv("APP_SECURITY_BASIC_AUTH_PASSWORD", "secret-pass")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def test_dashboard_requires_basic_auth_when_enabled(monkeypatch):
    with _secured_client(monkeypatch) as client:
        response = client.get("/dashboard")
        assert response.status_code == 401
        assert "Basic" in (response.headers.get("www-authenticate", ""))


def test_api_requires_basic_auth_when_enabled(monkeypatch):
    with _secured_client(monkeypatch) as client:
        response = client.get("/api/v1/rules")
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required."


def test_health_endpoint_remains_public_with_basic_auth_enabled(monkeypatch):
    with _secured_client(monkeypatch) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_dashboard_allows_access_with_valid_credentials(monkeypatch):
    with _secured_client(monkeypatch) as client:
        response = client.get("/dashboard", auth=("admin", "secret-pass"))
        assert response.status_code == 200
        assert "Action Review Dashboard" in response.text


def test_metrics_page_requires_basic_auth_when_enabled(monkeypatch):
    with _secured_client(monkeypatch) as client:
        response = client.get("/metrics")
        assert response.status_code == 401


def test_metrics_page_allows_access_with_valid_credentials(monkeypatch):
    with _secured_client(monkeypatch) as client:
        response = client.get("/metrics", auth=("admin", "secret-pass"))
        assert response.status_code == 200
        assert "Metrics Dashboard" in response.text


def test_settings_load_secret_from_file(tmp_path, monkeypatch):
    secret_file = tmp_path / "smtp_password.txt"
    secret_file.write_text("secret-from-file\n", encoding="utf-8")
    monkeypatch.setenv("APP_SMTP_PASSWORD", "")
    monkeypatch.setenv("APP_SMTP_PASSWORD_FILE", str(secret_file))
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.smtp_password == "secret-from-file"
    get_settings.cache_clear()
