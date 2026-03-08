from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlencode
import urllib.error
import urllib.request

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.services.integrations.credential_store import IntegrationCredentialStore


class GoogleOAuthTokenService:
    def __init__(self, settings: Settings | None = None, db: Session | None = None):
        self.settings = settings or get_settings()
        self.db = db
        self.credential_store = IntegrationCredentialStore(db=db, settings=self.settings) if db is not None else None
        self._access_token: str | None = self.settings.google_calendar_access_token
        self._refresh_token: str | None = self.settings.google_calendar_refresh_token
        self._expires_at: datetime | None = None

    def can_refresh(self) -> bool:
        self._load_tokens_from_store()
        return bool(
            self.settings.google_client_id
            and self.settings.google_client_secret
            and self._refresh_token
        )

    def get_access_token(self, force_refresh: bool = False) -> str:
        self._load_tokens_from_store()
        if not force_refresh and self._has_valid_cached_token():
            return self._access_token or ""

        if self.can_refresh():
            self._refresh_access_token()
            if self._access_token:
                return self._access_token

        # Fallback path for static manually-managed access token
        fallback_access = self._access_token or self.settings.google_calendar_access_token
        if fallback_access:
            self._access_token = fallback_access
            self._expires_at = None
            return self._access_token

        raise RuntimeError(
            "Google Calendar token unavailable. Configure Google OAuth integration or set "
            "APP_GOOGLE_CALENDAR_ACCESS_TOKEN / APP_GOOGLE_CALENDAR_REFRESH_TOKEN."
        )

    def _has_valid_cached_token(self) -> bool:
        if not self._access_token:
            return False
        if self._expires_at is None:
            return True
        return datetime.now(timezone.utc) < self._expires_at

    def _refresh_access_token(self) -> None:
        if not self.can_refresh():
            raise RuntimeError("OAuth refresh is not configured for Google Calendar.")

        form_data = urlencode(
            {
                "client_id": self.settings.google_client_id or "",
                "client_secret": self.settings.google_client_secret or "",
                "refresh_token": self._refresh_token or "",
                "grant_type": "refresh_token",
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
            raise RuntimeError(f"Google OAuth token refresh failed (HTTP {exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Google OAuth token endpoint connection error: {exc.reason}") from exc

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Google OAuth token endpoint returned non-JSON response.") from exc

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise RuntimeError("Google OAuth token refresh response does not include a valid access_token.")

        refresh_token_raw = payload.get("refresh_token")
        if isinstance(refresh_token_raw, str) and refresh_token_raw.strip():
            self._refresh_token = refresh_token_raw.strip()

        expires_in_raw = payload.get("expires_in")
        expires_in = 3600
        if isinstance(expires_in_raw, (int, float)):
            expires_in = max(60, int(expires_in_raw))

        token_type = payload.get("token_type")
        token_type_str = token_type.strip() if isinstance(token_type, str) and token_type.strip() else None
        scope_text = payload.get("scope")
        scopes = scope_text if isinstance(scope_text, str) and scope_text.strip() else self.settings.google_calendar_scopes

        self._access_token = access_token.strip()
        # keep a small buffer to avoid using tokens close to expiration
        self._expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(30, expires_in - 30))

        if self.credential_store and self.credential_store.crypto.is_configured():
            self.credential_store.upsert_google_credentials(
                access_token=self._access_token,
                refresh_token=self._refresh_token,
                token_type=token_type_str,
                scopes=scopes,
                expires_at=self._expires_at,
                metadata=payload,
            )

    def _load_tokens_from_store(self) -> None:
        if self.credential_store is None:
            return
        if not self.credential_store.crypto.is_configured():
            return

        credentials = self.credential_store.get_google_credentials()
        if credentials is None:
            return

        if credentials.access_token:
            self._access_token = credentials.access_token
        if credentials.refresh_token:
            self._refresh_token = credentials.refresh_token

        expires_at = credentials.expires_at
        if isinstance(expires_at, datetime):
            self._expires_at = _normalize_datetime(expires_at)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
