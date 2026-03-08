from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets
from urllib.parse import urlencode
import urllib.error
import urllib.request

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.services.integrations.credential_store import (
    GOOGLE_CALENDAR_PROVIDER,
    GOOGLE_DEFAULT_ACCOUNT_ID,
    IntegrationCredentialStore,
)


@dataclass
class GoogleConnectionStatus:
    connected: bool
    oauth_ready: bool
    encryption_ready: bool
    calendar_enabled: bool
    account_id: str | None
    expires_at: datetime | None
    scopes: list[str]
    has_refresh_token: bool


@dataclass
class GoogleTokenExchangeResult:
    access_token: str
    refresh_token: str | None
    token_type: str | None
    scopes: list[str]
    expires_at: datetime | None
    raw_payload: dict


class GoogleOAuthIntegrationService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self.store = IntegrationCredentialStore(db=db, settings=self.settings)

    def get_status(self) -> GoogleConnectionStatus:
        credentials = None
        if self.store.crypto.is_configured():
            try:
                credentials = self.store.get_google_credentials()
            except RuntimeError:
                credentials = None

        has_refresh_token = bool(credentials and credentials.refresh_token)
        return GoogleConnectionStatus(
            connected=bool(credentials and (credentials.access_token or credentials.refresh_token)),
            oauth_ready=self._oauth_configured(),
            encryption_ready=self.store.crypto.is_configured(),
            calendar_enabled=self.settings.google_calendar_enabled,
            account_id=credentials.account_id if credentials else GOOGLE_DEFAULT_ACCOUNT_ID,
            expires_at=credentials.expires_at if credentials else None,
            scopes=credentials.scopes if credentials else _parse_scope_text(self.settings.google_calendar_scopes),
            has_refresh_token=has_refresh_token,
        )

    def build_connect_url(self) -> str:
        self._ensure_connect_ready()
        state = self._issue_state()
        params = {
            "client_id": self.settings.google_client_id or "",
            "redirect_uri": self.settings.google_redirect_uri or "",
            "response_type": "code",
            "scope": self.settings.google_calendar_scopes,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
        return f"{self.settings.google_oauth_authorize_url}?{urlencode(params)}"

    def handle_callback(self, *, code: str, state: str) -> GoogleTokenExchangeResult:
        self._ensure_connect_ready()
        self._verify_state(state)
        token_result = self._exchange_code_for_tokens(code)

        self.store.upsert_google_credentials(
            access_token=token_result.access_token,
            refresh_token=token_result.refresh_token,
            token_type=token_result.token_type,
            scopes=token_result.scopes,
            expires_at=token_result.expires_at,
            metadata=token_result.raw_payload,
            account_id=GOOGLE_DEFAULT_ACCOUNT_ID,
        )
        return token_result

    def disconnect(self) -> int:
        return self.store.deactivate_provider(GOOGLE_CALENDAR_PROVIDER)

    def _oauth_configured(self) -> bool:
        return bool(
            self.settings.google_client_id
            and self.settings.google_client_secret
            and self.settings.google_redirect_uri
        )

    def _ensure_connect_ready(self) -> None:
        if not self._oauth_configured():
            raise RuntimeError(
                "Google OAuth is not configured. Set APP_GOOGLE_CLIENT_ID, APP_GOOGLE_CLIENT_SECRET, and APP_GOOGLE_REDIRECT_URI."
            )
        if not self.store.crypto.is_configured():
            raise RuntimeError("Credential encryption key missing. Set APP_CREDENTIALS_ENCRYPTION_KEY.")

    def _issue_state(self) -> str:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        payload = {
            "iat": timestamp,
            "nonce": secrets.token_urlsafe(12),
        }
        payload_text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        payload_b64 = _urlsafe_b64encode(payload_text.encode("utf-8"))
        signature = hmac.new(self._state_key(), payload_b64.encode("ascii"), hashlib.sha256).digest()
        return f"{payload_b64}.{_urlsafe_b64encode(signature)}"

    def _verify_state(self, state: str) -> None:
        try:
            payload_b64, signature_b64 = state.split(".", maxsplit=1)
        except ValueError as exc:
            raise RuntimeError("OAuth state is malformed.") from exc

        expected = hmac.new(self._state_key(), payload_b64.encode("ascii"), hashlib.sha256).digest()
        provided = _urlsafe_b64decode(signature_b64)
        if not hmac.compare_digest(expected, provided):
            raise RuntimeError("OAuth state signature is invalid.")

        payload_bytes = _urlsafe_b64decode(payload_b64)
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("OAuth state payload is invalid.") from exc

        issued_at = payload.get("iat")
        if not isinstance(issued_at, int):
            raise RuntimeError("OAuth state does not include a valid issue timestamp.")

        now = int(datetime.now(timezone.utc).timestamp())
        max_age = max(60, self.settings.google_oauth_state_ttl_seconds)
        if issued_at > now + 30 or (now - issued_at) > max_age:
            raise RuntimeError("OAuth state has expired. Start the connection again.")

    def _state_key(self) -> bytes:
        key_material = (self.settings.credentials_encryption_key or "").strip()
        if not key_material:
            raise RuntimeError("Credential encryption key missing. Set APP_CREDENTIALS_ENCRYPTION_KEY.")
        return hashlib.sha256(f"{key_material}:oauth_state".encode("utf-8")).digest()

    def _exchange_code_for_tokens(self, code: str) -> GoogleTokenExchangeResult:
        form_data = urlencode(
            {
                "code": code,
                "client_id": self.settings.google_client_id or "",
                "client_secret": self.settings.google_client_secret or "",
                "redirect_uri": self.settings.google_redirect_uri or "",
                "grant_type": "authorization_code",
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            url=self.settings.google_oauth_token_url,
            data=form_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Google OAuth code exchange failed (HTTP {exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Google OAuth token endpoint connection error: {exc.reason}") from exc

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Google OAuth token endpoint returned non-JSON response.") from exc

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise RuntimeError("Google OAuth response missing access_token.")

        refresh_token_raw = payload.get("refresh_token")
        refresh_token = refresh_token_raw.strip() if isinstance(refresh_token_raw, str) and refresh_token_raw.strip() else None

        scope_text = payload.get("scope")
        scopes = _parse_scope_text(scope_text if isinstance(scope_text, str) else self.settings.google_calendar_scopes)

        expires_at = None
        expires_in_raw = payload.get("expires_in")
        if isinstance(expires_in_raw, (int, float)):
            expires_seconds = max(60, int(expires_in_raw))
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)

        token_type = payload.get("token_type")
        token_type_str = token_type.strip() if isinstance(token_type, str) and token_type.strip() else None

        return GoogleTokenExchangeResult(
            access_token=access_token.strip(),
            refresh_token=refresh_token,
            token_type=token_type_str,
            scopes=scopes,
            expires_at=expires_at,
            raw_payload=payload,
        )


def _parse_scope_text(scope_text: str | None) -> list[str]:
    if not scope_text:
        return []
    return [part.strip() for part in scope_text.split() if part.strip()]


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
